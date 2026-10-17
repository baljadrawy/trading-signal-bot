'use strict';
(function () {
  const meta = (n) => document.querySelector(`meta[name="${n}"]`).content;
  const csrf = meta('a59-csrf'), expires = Number(meta('a59-expires'));
  const $ = (id) => document.getElementById(id);
  const LABEL = { ok: 'سليمة', warn: 'تحذير', error: 'خطأ', unknown: 'غير معروفة' };
  let skew = 0, timer = null, ended = false;

  function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
  function row(level, name, info) { const li = el('li'); const l = el('span'); l.append(el('span', 'dot ' + level), document.createTextNode(' ' + name)); li.append(l, el('span', 'tag', info)); return li; }
  function fill(id, items) { const box = $(id); box.replaceChildren(...(items.length ? items : [el('li', 'tag', 'لا توجد بيانات')])); }
  function age(s) { if (s === null || s === undefined) return '—'; if (s < 90) return s + ' ث'; if (s < 5400) return Math.round(s / 60) + ' د'; return Math.round(s / 3600) + ' س'; }
  function banner(level, text) { const b = $('banner'); if (!text) { b.hidden = true; return; } b.hidden = false; b.className = 'banner ' + level; b.textContent = text; }
  function setOverall(level) { $('overall').className = 'dot ' + level; }

  function end(text) {
    ended = true; clearInterval(timer); setOverall('unknown'); banner('error', text);
    ['services', 'positions', 'outbox'].forEach((id) => $(id).replaceChildren()); $('signals').replaceChildren();
    $('close').disabled = true;
  }

  function render(s) {
    skew = s.server_time - Date.now() / 1000;
    if (!s.ok) { setOverall('error'); banner('error', 'تعذّر قراءة البيانات. المعروض فارغ عمداً؛ لا تعتمد على أي حالة خضراء.'); return; }
    const d = s.data;
    const stale = (s.server_time - s.fetched_at) > s.stale_after_s;
    setOverall(stale ? 'warn' : d.overall);
    banner(d.overall === 'ok' && !stale ? '' : 'warn', d.overall === 'ok' && !stale ? '' : 'توجد عناصر تحتاج انتباهاً (حالة غير سليمة أو بيانات قديمة).');
    fill('services', d.services.map((x) => row(x.level, x.name, LABEL[x.level] + ' · آخر نجاح قبل ' + age(x.age_s))));
    fill('positions', d.positions.map((p) => row('unknown', p.symbol + ' · ' + p.timeframe, 'مفتوحة منذ ' + age(p.opened_age_s))));
    fill('outbox', d.outbox.map((o) => row(o.level, o.event_type, o.status + ' · ' + o.events)));
    const r = d.risk; $('risk').replaceChildren(el('span', 'dot ' + r.level), document.createTextNode(' ' + (r.paused === null ? 'غير معروفة' : r.paused ? 'التداول الورقي موقوف: ' + (r.reason || '') : 'يعمل')));
    $('schema').textContent = d.schema_version ?? '—';
    const max = Math.max(1, ...d.signals_hourly.map((h) => h.signals || 0));
    $('signals').replaceChildren(...d.signals_hourly.slice().reverse().map((h) => { const b = el('span'); b.style.height = (100 * (h.signals || 0) / max) + '%'; b.title = String(h.signals); return b; }));
    $('fetched').textContent = new Date(s.fetched_at * 1000).toLocaleTimeString('ar');
  }

  async function poll() {
    if (ended) return;
    try {
      const r = await fetch('/api/state', { headers: { 'X-A59-Request': '1' }, credentials: 'same-origin', cache: 'no-store' });
      if (r.status === 401) return end('انتهت الجلسة أو أُغلقت. اطلب رابطاً جديداً من تيليجرام.');
      render(await r.json());
    } catch (e) { setOverall('error'); banner('error', 'انقطع الاتصال باللوحة. البيانات المعروضة قد تكون قديمة.'); }
  }

  function tick() {
    const left = Math.max(0, Math.round(expires - (Date.now() / 1000 + skew)));
    $('countdown').textContent = Math.floor(left / 60) + ':' + String(left % 60).padStart(2, '0');
    if (left <= 0 && !ended) end('انتهت مدة الجلسة (15 دقيقة كحد أقصى).');
  }

  $('close').addEventListener('click', async () => {
    try { await fetch('/api/close', { method: 'POST', headers: { 'X-CSRF-Token': csrf }, credentials: 'same-origin' }); } catch (e) { /* listener stops */ }
    end('أُغلقت اللوحة وأُلغيت الجلسة.');
  });
  poll(); timer = setInterval(poll, 15000); setInterval(tick, 1000); tick();
})();
