/* Scanner endpoints.

   Kept separate from api/client.js because the scanner is a self-contained
   module -- its own store, its own cadence, its own universe. If it ever
   becomes its own service, only this file changes.

   BASE matches api/client.js's convention exactly: in dev, Vite proxies /api
   to 127.0.0.1:8000, so the browser stays on one origin and CORS never
   appears. Getting this wrong doesn't fail loudly -- a GET falls through to
   Vite's SPA fallback and returns index.html, which then fails to parse as
   JSON ("Unexpected token '<'"); a POST returns a bare 404. Both are this
   one line being wrong, not a backend problem. */
const BASE = import.meta.env.VITE_API_BASE ?? '/api';

async function req(path, opts = {}) {
  const res = await fetch(`${BASE}/scanner${path}`, opts);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch { /* non-JSON error body; keep the status line */ }
    throw new Error(detail);
  }
  return res.json();
}

const json = (body) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export const scannerApi = {
  status: () => req('/status'),
  runScan: () => req('/scan', { method: 'POST' }),
  results: () => req('/results'),
  sync: (symbols) => req('/sync', json({ symbols })),

  athList: (q = '', limit = 1000) =>
    req(`/ath?q=${encodeURIComponent(q)}&limit=${limit}`),
  editAth: (symbol, price, date) => req('/ath/edit', json({ symbol, price, date })),
  athEvents: (symbol) => req(`/ath/events?symbol=${encodeURIComponent(symbol)}`),
  suspectedRepeatHalvings: () => req('/ath/suspected-repeat-halvings'),
  resetAth: (wipeEvents = false) =>
    req('/ath/reset', json({ confirm: true, wipe_events: wipeEvents })),

  universe: () => req('/universe'),
  uploadUniverse: (file) => {
    const form = new FormData();
    form.append('file', file);
    return req('/universe/upload', { method: 'POST', body: form });
  },
  mapSymbol: (symbol, isin) => req('/universe/map', json({ symbol, isin })),
  removeSymbols: (symbols) => req('/universe/remove', json({ symbols })),
  resetUniverse: () => req('/universe/reset', json({ confirm: true })),

  profitStatus: () => req('/profit/status'),
  refreshProfit: () => req('/profit/refresh', { method: 'POST' }),
};
