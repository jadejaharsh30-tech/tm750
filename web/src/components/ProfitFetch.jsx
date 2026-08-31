/* The global profit fetch, in the header so it is reachable from every page.

   It lives here rather than inside the Scanner because profit is no longer a
   scanner concern: the platform's build reads the same fetched workbooks, so
   burying the control in one module would misrepresent what it affects.

   The dot carries the state at a glance -- fresh today, stale, or never
   fetched -- so the header answers "is my profit data current" without
   anyone having to open a page to find out. */
import { useState } from 'react';
import { useProfitFeed, stampText } from '../lib/profit';

export default function ProfitFetch() {
  const { status, busy, stale, everFetched, fetchNow } = useProfitFeed();
  const [flash, setFlash] = useState(null);

  const tone = busy ? 'busy' : !everFetched ? 'never' : stale ? 'stale' : 'fresh';
  const stamp = stampText(status?.fetched_at);

  const title = busy
    ? 'Fetching both profit feeds — this takes about a minute'
    : !everFetched
      ? 'Profit data has never been fetched. Click to fetch.'
      : stale
        ? `Profit last fetched ${stamp} — not today. Click to refresh.`
        : `Profit fetched ${stamp}. Up to date.`;

  async function run() {
    setFlash(null);
    try {
      const out = await fetchNow();
      const n = out?.companies_y ?? out?.companies_q;
      setFlash({
        ok: true,
        text: `Fetched ${Number(n ?? 0).toLocaleString('en-IN')} companies `
              + `in ${out?.seconds ?? '?'}s`,
      });
    } catch (err) {
      setFlash({ ok: false, text: err?.message ?? 'Fetch failed' });
    }
    setTimeout(() => setFlash(null), 6000);
  }

  return (
    <span className="profitfetch">
      <button className={`btn profitbtn ${tone}`} onClick={run}
              disabled={busy} title={title}>
        <span className={`pf-dot ${tone}`} aria-hidden="true" />
        {busy ? 'Fetching…' : 'Profit'}
      </button>
      {flash && (
        <span className={`pf-flash ${flash.ok ? 'ok' : 'bad'}`} role="status">
          {flash.text}
        </span>
      )}
    </span>
  );
}

/** Inline freshness notice, for pages where stale profit changes what the
 *  page means -- Upload before a build, the Scanner before a scan. */
export function ProfitFreshness({ context = 'this' }) {
  const { status, busy, stale, everFetched, fetchNow } = useProfitFeed();
  const stamp = stampText(status?.fetched_at);

  if (!everFetched) {
    return (
      <div className="banner warn">
        <strong>Profit data has never been fetched.</strong>{' '}
        {context === 'upload'
          ? 'The build will fall back to whatever profit workbook was carried '
            + 'forward from a previous snapshot.'
          : 'Verdicts will read “no data” until you fetch.'}{' '}
        <button className="btn small" onClick={fetchNow} disabled={busy}>
          {busy ? 'Fetching…' : 'Fetch now'}
        </button>
      </div>
    );
  }

  if (!stale) return null;

  return (
    <div className="banner warn">
      <strong>Profit was last fetched {stamp}, not today.</strong>{' '}
      {context === 'upload'
        ? 'This snapshot will be built with that profit data.'
        : 'Scan verdicts will use that profit data.'}{' '}
      <button className="btn small" onClick={fetchNow} disabled={busy}>
        {busy ? 'Fetching…' : 'Fetch now'}
      </button>
    </div>
  );
}
