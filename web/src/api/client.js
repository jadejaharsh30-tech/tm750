/* Single place that knows where the API lives. In dev, Vite proxies /api to
   127.0.0.1:8000 so the browser stays on one origin and CORS never appears. */

const BASE = import.meta.env.VITE_API_BASE ?? '/api';

class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* Retries network failures and 5xx with a short backoff. 4xx is never retried:
   a rejected filter is a real answer, and repeating it just wastes time. */
async function request(path, options = {}, attempt = 0) {
  const MAX_RETRIES = 2;
  let res;

  try {
    const isForm = options.body instanceof FormData;
    res = await fetch(`${BASE}${path}`, {
      // FormData must set its own Content-Type so the multipart boundary is
      // included. Forcing application/json here breaks every upload.
      ...(isForm ? {} : { headers: { 'Content-Type': 'application/json' } }),
      ...options,
    });
  } catch (err) {
    if (attempt < MAX_RETRIES) {
      await sleep(180 * (attempt + 1));
      return request(path, options, attempt + 1);
    }
    throw new ApiError(
      'Cannot reach the API. Is uvicorn running on port 8000?', 0, String(err));
  }

  if (res.status >= 500 && attempt < MAX_RETRIES) {
    await sleep(180 * (attempt + 1));
    return request(path, options, attempt + 1);
  }

  if (!res.ok) {
    let detail = null;
    try { detail = (await res.json()).detail; } catch { /* non-JSON error */ }
    throw new ApiError(errorMessage(res.status, detail), res.status, detail);
  }

  try {
    return await res.json();
  } catch (err) {
    throw new ApiError('The API returned a malformed response.', res.status,
                       String(err));
  }
}

/* React StrictMode double-invokes effects in development, so every screen
   fires each request twice. Identical in-flight GETs share one promise. */
const inflight = new Map();

function dedup(key, fn) {
  if (inflight.has(key)) return inflight.get(key);
  const p = fn().finally(() => inflight.delete(key));
  inflight.set(key, p);
  return p;
}

/* Errors explain what happened and what to do, in the interface's voice. */
function errorMessage(status, detail) {
  if (status === 404) return 'Not found.';
  if (status === 422) {
    const first = Array.isArray(detail) ? detail[0]?.msg : detail;
    return first ? `Invalid request: ${first}` : 'Invalid request.';
  }
  if (status === 400) return typeof detail === 'string' ? detail : 'Bad request.';
  if (status >= 500) return 'The API failed on this request.';
  return `Request failed (${status}).`;
}

/* The snapshot the whole app is reading. Set once by the picker; every read
   below appends it, so a past date cannot be applied to some panels and
   missed by others. */
let asOf = null;

export function setAsOf(date) {
  asOf = date || null;
  inflight.clear();   // cached in-flight reads belong to the previous date
}

export function getAsOf() { return asOf; }

function withAsOf(path) {
  if (!asOf) return path;
  return path + (path.includes('?') ? '&' : '?') + `snapshot=${asOf}`;
}

const get = (path) => {
  const full = withAsOf(path);
  return dedup(full, () => request(full));
};

export const api = {
  health:     ()          => get('/health'),
  catalog:    ()          => get('/meta/catalog'),
  segments:   ()          => get('/meta/segments'),
  enums:      ()          => get('/meta/enums'),
  quality:    ()          => get('/meta/quality'),
  snapshots:  ()          => get('/meta/snapshots'),
  pulse:      ()          => get('/pulse'),
  profitAth:  ()          => get('/pulse/profit-ath'),
  breadth:    (by = 'sector') => get(`/pulse/breadth?by=${by}`),
  valuation:  ()          => get('/pulse/valuation'),
  flows:      ()          => get('/pulse/flows'),
  factors:    ()          => get('/pulse/factors'),
  drawdown:   ()          => get('/pulse/drawdown'),
  search:     (q, limit = 10) =>
    get(`/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  company:    (sym)       => get(`/companies/${encodeURIComponent(sym)}`),
  history:    (sym, freq = 'Q') =>
    get(`/companies/${encodeURIComponent(sym)}/history?freq=${freq}`),
  movers:     (field, n = 10, tier = null) =>
    get(`/movers?field=${field}&n=${n}${tier ? `&tier=${tier}` : ''}`),
  explore:    (dim, metrics = null) =>
    get(`/explore/${dim}${metrics ? `?metrics=${metrics.join(',')}` : ''}`),
  factorOverlap: ()       => get('/explore/factors/overlap'),

  // ---- history
  historySnapshots: ()    => get('/history/snapshots'),
  companySeries: (sym, metrics = null) =>
    get(`/history/company/${encodeURIComponent(sym)}` +
        (metrics ? `?metrics=${metrics.join(',')}` : '')),
  universeSeries: (metric = 'perf_1y_pct') =>
    get(`/history/universe?metric=${metric}`),
  changes: (metric = 'price', n = 15, from = null, to = null) =>
    get(`/history/changes?metric=${metric}&n=${n}` +
        (from ? `&from=${from}` : '') + (to ? `&to=${to}` : '')),
  universeChanges: ()     => get('/history/universe-changes'),
  screenChanges: (filters) =>
    request('/history/screen-changes', {
      method: 'POST', body: JSON.stringify({ filters }) }),

  // ---- admin
  adminSnapshots: ()      => get('/admin/snapshots'),
  uploadPreview: (form)   =>
    request('/admin/preview', { method: 'POST', body: form, headers: {} }),
  upload: (form)          =>
    request('/admin/upload', { method: 'POST', body: form, headers: {} }),
  deleteSnapshot: (date)  =>
    request(`/admin/snapshots/${date}`, { method: 'DELETE' }),
  screen:     (body)      =>
    request(withAsOf('/screen'),
            { method: 'POST', body: JSON.stringify(body) }),
  compare:    (symbols, segments = null) =>
    request(withAsOf('/compare'), { method: 'POST',
      body: JSON.stringify({ symbols, ...(segments ? { segments } : {}) }) }),
};

export { ApiError };
