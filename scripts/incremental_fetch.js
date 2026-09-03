// Fetch first page (200 messages) for a room, filter by cutoff date
// Required in localStorage: __fetchId (int), __cutoffDate (ISO date or empty), __roomInfo (dict), appToken
async function fetchOnePage() {
  const id = parseInt(localStorage.getItem('__fetchId') || '0', 10);
  const cutoff = localStorage.getItem('__cutoffDate') || '';
  const t = localStorage.getItem('appToken');
  const room = JSON.parse(localStorage.getItem('__roomInfo') || 'null');
  if (!room || room.id !== id) return JSON.stringify({ok: false, id, reason: 'no room info'});
  const extractTimes = (text) => {
    if (!text) return [];
    const found = new Set();
    const m1 = text.match(/\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b/g); if (m1) m1.forEach(t => found.add(t));
    const m2 = text.match(/\b\d{1,2}[/-]\d{1,2}\b/g); if (m2) m2.forEach(t => found.add(t));
    return Array.from(found);
  };
  try {
    const url = 'https://gudao.gonm2.cn/api/rooms/' + id + '/messages?limit=200';
    const r = await fetch(url, {headers: {'Authorization': 'Bearer ' + t}});
    if (!r.ok) throw new Error('status ' + r.status);
    const d = await r.json();
    if (!d || !d.length) return JSON.stringify({ok: false, id, name: room.name, reason: 'empty'});
    const msgs = [];
    for (const m of d) {
      if (cutoff && m.created_at <= cutoff) break;
      const c = m.full_content || m.preview_text || '';
      msgs.push({id: m.id, date: m.created_at, content: c});
    }
    if (msgs.length === 0) return JSON.stringify({ok: false, id, name: room.name, reason: 'no new'});
    const rows = msgs.map(m => {
      const c = m.content;
      const timesIn = extractTimes(c).join('|');
      const summary = c.split(/\r?\n[-]+\r?\n/)[0].replace(/\s+/g,' ').trim().slice(0,180);
      const cleanContent = c.replace(/\r?\n/g, ' ').replace(/"/g, '""');
      return [m.date, '', '', '', summary, timesIn, '', cleanContent];
    });
    const csv = '\ufeff' + rows.map(r => r.map(v => '"' + String(v ?? '').replace(/"/g, '""') + '"').join(',')).join('\r\n');
    const bytes = new TextEncoder().encode(csv);
    let bin = '';
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return JSON.stringify({ok: true, id, name: room.name, count: rows.length, b64: btoa(bin), newest: msgs[0].date});
  } catch (e) {
    return JSON.stringify({ok: false, id, name: room.name, reason: 'exception: ' + e.message});
  }
}
localStorage.setItem('__onePageFn', fetchOnePage.toString());
fetchOnePage();
