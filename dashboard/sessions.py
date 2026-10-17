"""A59 session store: single-use login links and short-lived dashboard sessions (stdlib only).

Rules (all enforced here, in one SQLite database, under BEGIN IMMEDIATE so every check-and-set is atomic):
* A link is valid for LINK_TTL_S (60 s), once, and only in the generation it was issued in.
* A session ends at the window end: at most WINDOW_S (15 min) after the owner's Open. It is never extended.
* Every Open, Close and service start bumps the generation, which revokes every link and session issued before it.
  So at most one link and one session can ever be valid, and a restart can never restore access.
* Tokens and session ids are stored only as SHA-256 hashes; the plaintext exists only in the link and the cookie.
"""
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time

LINK_TTL_S = 60
WINDOW_S = 15 * 60


def _h(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class Store:
    def __init__(self, path: str, clock=time.time):
        self.clock = clock
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v INTEGER NOT NULL);
            INSERT OR IGNORE INTO meta (k, v) VALUES ('generation', 0);
            CREATE TABLE IF NOT EXISTS links (h TEXT PRIMARY KEY, gen INTEGER NOT NULL, issued REAL NOT NULL,
                                              expires REAL NOT NULL, window_end REAL NOT NULL, used INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (h TEXT PRIMARY KEY, gen INTEGER NOT NULL, expires REAL NOT NULL,
                                                 csrf TEXT NOT NULL, revoked INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS events (at REAL NOT NULL, gen INTEGER NOT NULL, event TEXT NOT NULL);
        """)

    # ------------------------------------------------------------------ internals
    def _tx(self):
        self.db.execute('BEGIN IMMEDIATE')

    def _gen(self) -> int:
        return self.db.execute("SELECT v FROM meta WHERE k='generation'").fetchone()[0]

    def _bump(self, event: str) -> int:
        gen = self._gen() + 1
        self.db.execute("UPDATE meta SET v=? WHERE k='generation'", (gen,))
        self.db.execute('UPDATE links SET used=1 WHERE used=0')
        self.db.execute('UPDATE sessions SET revoked=1 WHERE revoked=0')
        self.db.execute('INSERT INTO events (at, gen, event) VALUES (?, ?, ?)', (self.clock(), gen, event[:40]))
        return gen

    # ------------------------------------------------------------------ owner actions
    def revoke_all(self, reason: str) -> int:
        """Close: no link and no session issued so far stays valid. Returns the new generation."""
        with self._lock:
            self._tx()
            try:
                gen = self._bump(f'revoke:{reason}')
                self.db.execute('COMMIT')
                return gen
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def issue_link(self) -> tuple[str, float]:
        """Open: revoke everything earlier, then issue one link. Returns (token, window_end)."""
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._tx()
            try:
                gen = self._bump('open')
                now = self.clock()
                window_end = now + WINDOW_S
                self.db.execute('INSERT INTO links (h, gen, issued, expires, window_end, used) VALUES (?, ?, ?, ?, ?, 0)',
                                (_h(token), gen, now, now + LINK_TTL_S, window_end))
                self.db.execute('COMMIT')
                return token, window_end
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    # ------------------------------------------------------------------ browser actions
    def redeem(self, token: str):
        """Exchange a link for a session, at most once. Returns (session_id, csrf, expires) or None."""
        if not token or len(token) > 128:
            return None
        with self._lock:
            self._tx()
            try:
                now, gen = self.clock(), self._gen()
                cur = self.db.execute('UPDATE links SET used=1 WHERE h=? AND used=0 AND gen=? AND expires>?',
                                      (_h(token), gen, now))
                if cur.rowcount != 1:
                    self.db.execute('COMMIT')
                    return None
                window_end = self.db.execute('SELECT window_end FROM links WHERE h=?', (_h(token),)).fetchone()[0]
                if self.db.execute('SELECT count(*) FROM sessions WHERE gen=? AND revoked=0', (gen,)).fetchone()[0]:
                    self.db.execute('COMMIT')                 # unreachable by construction; refuse rather than add one
                    return None
                sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
                self.db.execute('INSERT INTO sessions (h, gen, expires, csrf, revoked) VALUES (?, ?, ?, ?, 0)',
                                (_h(sid), gen, window_end, csrf))
                self.db.execute('INSERT INTO events (at, gen, event) VALUES (?, ?, ?)', (now, gen, 'redeem'))
                self.db.execute('COMMIT')
                return sid, csrf, window_end
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def check(self, sid: str):
        """The live session for this cookie value, or None. Returns {'csrf', 'expires'}."""
        if not sid or len(sid) > 128:
            return None
        with self._lock:
            row = self.db.execute('SELECT csrf, expires FROM sessions WHERE h=? AND gen=? AND revoked=0 AND expires>?',
                                  (_h(sid), self._gen(), self.clock())).fetchone()
        return {'csrf': row[0], 'expires': row[1]} if row else None

    @staticmethod
    def csrf_ok(expected: str, given: str | None) -> bool:
        return bool(given) and hmac.compare_digest(expected, given)

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        with self._lock:
            now, gen = self.clock(), self._gen()
            link = self.db.execute('SELECT expires, window_end FROM links WHERE gen=? AND used=0 AND expires>?',
                                   (gen, now)).fetchone()
            sess = self.db.execute('SELECT expires FROM sessions WHERE gen=? AND revoked=0 AND expires>?',
                                   (gen, now)).fetchone()
        state = 'session_active' if sess else ('link_pending' if link else 'closed')
        return {'state': state, 'generation': gen,
                'link_expires_in_s': round(link[0] - now) if link else None,
                'session_expires_in_s': round(sess[0] - now) if sess else None}
