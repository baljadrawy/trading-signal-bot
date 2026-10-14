"""P2F 1.6.1 (A39): health separates the current operating condition from pending acknowledgements.
`state` must be unchanged in every case (fail closed); operational_state may be healthier ONLY when the sole hard
reasons are verified-historical conn_recovery_failed latches of connections that are data-live again. Deterministic,
no network (fake-connection collector of tests.test_regression_g2r)."""
import json
import os
import tempfile
import unittest

from p2_forward import app as A
from p2_forward.incidents import IncidentLog
from tests.test_regression_g2r import mk, healthy_collector, stop_writer, book, depth, mini


def _mk(d):
    c = mk(d, mode="continuous")
    c.incidents = IncidentLog(d, c.boot_id)
    c.ws_start_ms = A.now_ms() - 3_600_000
    return c


def _live(c, m, names=("conn0-book", "conn1-depth")):
    for n in names:
        c.activity[n].transitions.append((m - 100_000, True))
        c.activity[n].data(m - 50)


def _split(c, m, hard, state="DEGRADED", startup=()):
    return c.health_split(m, state, list(hard), list(startup))


class HealthAckSplit(unittest.TestCase):
    def test_recovered_connection_with_unacked_critical_is_operationally_healthy(self):
        with tempfile.TemporaryDirectory() as d:
            c = _mk(d); m = A.now_ms(); _live(c, m)
            c.incidents.raise_("conn_recovery_failed:conn0-book", "CRITICAL", {"cause": "outage_exceeded_limit"})
            s = _split(c, m, ["incident:conn_recovery_failed:conn0-book"])
            self.assertEqual(s["operational_state"], "HEALTHY")
            self.assertEqual(s["historical_reasons"], ["incident:conn_recovery_failed:conn0-book"])
            self.assertEqual(s["attention"], "ACK_REQUIRED")
            self.assertEqual([p["key"] for p in s["pending_ack"]], ["conn_recovery_failed:conn0-book"])

    def test_connection_still_down_keeps_operational_degraded(self):
        with tempfile.TemporaryDirectory() as d:
            c = _mk(d); m = A.now_ms(); _live(c, m, ("conn1-depth",))
            c.activity["conn0-book"].transitions.append((m - 900_000, True)); c.activity["conn0-book"].data(m - 800_000)
            c.incidents.raise_("conn_recovery_failed:conn0-book", "CRITICAL", {})
            s = _split(c, m, ["incident:conn_recovery_failed:conn0-book"])
            self.assertEqual(s["operational_state"], "DEGRADED")
            self.assertEqual(s["historical_reasons"], [])

    def test_active_outage_incident_or_timed_outage_keeps_degraded(self):
        with tempfile.TemporaryDirectory() as d:
            c = _mk(d); m = A.now_ms(); _live(c, m)
            c.incidents.raise_("conn_recovery_failed:conn0-book", "CRITICAL", {})
            c.incidents.raise_("conn_outage:conn0-book", "DEGRADED", {}, latched=False)
            hard = ["incident:conn_recovery_failed:conn0-book", "incident:conn_outage:conn0-book"]
            self.assertEqual(_split(c, m, hard)["operational_state"], "DEGRADED")
            c.incidents.resolve("conn_outage:conn0-book")
            c.conn_outage["conn0-book"] = {"start": m - 1000, "opened": False, "failed": False}
            self.assertEqual(_split(c, m, hard[:1])["operational_state"], "DEGRADED")

    def test_any_current_reason_keeps_degraded(self):
        with tempfile.TemporaryDirectory() as d:
            c = _mk(d); m = A.now_ms(); _live(c, m)
            c.incidents.raise_("conn_recovery_failed:conn0-book", "CRITICAL", {})
            s = _split(c, m, ["stale:gnsusdt@depth10", "incident:conn_recovery_failed:conn0-book"])
            self.assertEqual(s["operational_state"], "DEGRADED")
            self.assertEqual(s["operational_reasons"], ["stale:gnsusdt@depth10"])

    def test_other_latched_integrity_incidents_are_never_historical(self):
        with tempfile.TemporaryDirectory() as d:
            c = _mk(d); m = A.now_ms(); _live(c, m)
            for key in ("failclosed:writer_stalled", "external:seal-2026-10-06.json", "seq_reset",
                        "startup_failed", "clock_critical", "previous_run_stopped_failed"):
                c.incidents.raise_(key, "CRITICAL", {})
                s = _split(c, m, [f"incident:{key}"])
                self.assertEqual(s["operational_state"], "DEGRADED", key)

    def test_disk_or_ban_states_are_never_relaxed(self):
        with tempfile.TemporaryDirectory() as d:
            c = _mk(d); m = A.now_ms(); _live(c, m)
            c.incidents.raise_("conn_recovery_failed:conn0-book", "CRITICAL", {})
            for st in ("DEGRADED_DISK", "BANNED_418", "STOPPED", "FAILED"):
                self.assertEqual(_split(c, m, ["incident:conn_recovery_failed:conn0-book"], st)["operational_state"], st)

    def test_acknowledgement_clears_attention_and_keeps_history(self):
        with tempfile.TemporaryDirectory() as d:
            c = _mk(d); m = A.now_ms(); _live(c, m)
            inc = c.incidents.raise_("conn_recovery_failed:conn1-depth", "CRITICAL", {})
            c.incidents.raise_("observation_loss:tier0", "WARNING", {})
            with open(os.path.join(d, "incidents", "ack", inc["id"] + ".json"), "w") as fh:
                json.dump({"by": "owner", "ref": "test"}, fh)
            self.assertEqual(c.incidents.poll_acks(), 1)
            s = _split(c, m, [])
            self.assertEqual(s["attention"], "ACK_ADVISED")                       # WARNING latch still pending
            self.assertEqual([p["key"] for p in s["pending_ack"]], ["observation_loss:tier0"])
            kept = c.incidents.items[inc["id"]]
            self.assertTrue(kept["active"]); self.assertEqual(kept["ack"]["by"], "owner")   # history kept
            ev = [json.loads(l)["event"] for l in open(os.path.join(d, "incidents", "events.jsonl"))]
            self.assertEqual(ev.count("ack"), 1)

    def test_state_itself_is_unchanged_by_the_split(self):
        """health_eval keeps counting the unacknowledged CRITICAL (the watchdog, healthcheck and gate inputs)."""
        with tempfile.TemporaryDirectory() as d:
            c = _mk(d); m = A.now_ms(); _live(c, m)
            c.incidents.raise_("conn_recovery_failed:conn0-book", "CRITICAL", {})
            src = open(A.__file__, encoding="utf-8").read()
            self.assertIn('(hard if inc["severity"] in ("DEGRADED", "CRITICAL") else warn).append(f"incident:{inc[\'key\']}")',
                          src)
            self.assertIn('**self.health_split(m, state, hard, startup),', src)
            self.assertEqual(_split(c, m, [], "HEALTHY")["operational_state"], "HEALTHY")


class HealthEndToEnd(unittest.TestCase):
    """The full health() of a running continuous collector: `state` stays DEGRADED while an unacknowledged
    CRITICAL is pending; operational_state reports the recovered condition; acknowledgement restores HEALTHY."""
    def test_full_health_document(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d, mode="continuous")
            c.incidents = IncidentLog(d, c.boot_id)
            try:
                m = A.now_ms()
                for name in c.task_periods:                 # continuous mode has extra required tasks
                    c.beats[name] = A.time.monotonic()
                for conn in c.conns:
                    c.activity[conn.name].data(m - 20)
                for sym in ("btcusdt", "ethusdt"):
                    book(c, 2, m - 20, sym); depth(c, 2, m - 20, sym)
                mini(c, m - 20)
                base = c.health()
                self.assertEqual(base["state"], "HEALTHY", base["reasons"])
                inc = c.incidents.raise_("conn_recovery_failed:conn0-book", "CRITICAL", {"cause": "test"})
                h = c.health()
                self.assertEqual(h["state"], "DEGRADED")
                self.assertIn("incident:conn_recovery_failed:conn0-book", h["reasons"])
                self.assertEqual(h["operational_state"], base["state"])
                self.assertEqual(h["attention"], "ACK_REQUIRED")
                with open(os.path.join(d, "incidents", "ack", inc["id"] + ".json"), "w") as fh:
                    json.dump({"by": "owner", "ref": "t"}, fh)
                c.incidents.poll_acks()
                h2 = c.health()
                self.assertEqual(h2["state"], base["state"])
                self.assertEqual(h2["attention"], "NONE")
            finally:
                stop_writer(c)


if __name__ == "__main__":
    unittest.main()
