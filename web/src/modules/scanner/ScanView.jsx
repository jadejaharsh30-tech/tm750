/* Today's ATH hits, with the four strategies and the profit verdict.

   The row worth acting on is every flag green AND profit at a record: price
   at an all-time high, confirmed on the close, relative strength also at a
   high, and earnings at records on both horizons. Everything else on this
   screen exists to make that row easy to find. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { scannerApi } from '../../api/scanner';
import { Empty, ErrorState } from '../../components/ui';

const POLL_MS = 2000;

/* Three states, not two. A company outside the profit universe has not
   failed the test -- it was never given it -- so it must never wear the same
   colour as a genuine negative. */
const PROFIT = {
  at_ath: { label: 'At ATH', cls: 'ok' },
  not_at_ath: { label: 'Not at ATH', cls: 'no' },
  no_data: { label: '\u2014', cls: 'none' },
};

function Flag({ value }) {
  if (value === 'Y') return <span className="sflag y">Y</span>;
  if (value === 'N') return <span className="sflag n">N</span>;
  return <span className="sflag na">n/a</span>;
}

function ProfitCell({ state, stale, resultDate, fetchedAt }) {
  const spec = PROFIT[state] ?? PROFIT.no_data;
  const title = stale
    ? `Result filed ${resultDate}; profit data fetched ${fetchedAt?.slice(0, 10)}`
      + ' \u2014 this verdict may describe the previous quarter.'
    : undefined;
  return (
    <span className={`sverdict ${spec.cls}`} title={title}>
      {spec.label}
      {stale && <span className="sstale" aria-label="may be out of date">!</span>}
    </span>
  );
}

function num(v, dp = 2) {
  if (v === null || v === undefined) return '\u2014';
  return v.toLocaleString('en-IN', { minimumFractionDigits: dp,
                                     maximumFractionDigits: dp });
}

export default function ScanView() {
  const [status, setStatus] = useState(null);
  const [data, setData] = useState(null);
  const [hasFetched, setHasFetched] = useState(false);
  const [error, setError] = useState(null);
  const [excluded, setExcluded] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);
  const timer = useRef(null);

  const loadResults = useCallback(() => {
    scannerApi.results()
      .then((d) => { setData(d); setHasFetched(true); setExcluded(new Set()); })
      .catch(setError);
  }, []);

  /* Watches an IN-FLIGHT scan to completion, then loads results. Only ever
     called when a scan is known to be running -- just started by this tab,
     or already running when the page loaded -- never on a bare mount with
     nothing in flight. That distinction is the whole point: a scan finishing
     should show fresh results immediately, but loading the page must not
     silently redisplay whatever the LAST scan happened to leave behind,
     since that could be hours or days old and easy to mistake for current. */
  const watchUntilDone = useCallback(() => {
    scannerApi.status()
      .then((s) => {
        setStatus(s);
        if (s.running) {
          timer.current = setTimeout(watchUntilDone, POLL_MS);
        } else {
          loadResults();
        }
      })
      .catch(setError);
  }, [loadResults]);

  useEffect(() => {
    let cancelled = false;
    scannerApi.status()
      .then((s) => {
        if (cancelled) return;
        setStatus(s);
        if (s.running) watchUntilDone();
      })
      .catch((e) => !cancelled && setError(e));
    return () => { cancelled = true; clearTimeout(timer.current); };
  }, [watchUntilDone]);

  const start = async () => {
    setError(null); setNote(null);
    try {
      await scannerApi.runScan();
      watchUntilDone();
    } catch (e) { setError(e); }
  };

  const sync = async () => {
    const rows = data?.rows ?? [];
    const symbols = rows.map((r) => r.symbol).filter((s) => !excluded.has(s));
    if (!symbols.length) {
      setNote('Nothing selected. Tick at least one row to sync.');
      return;
    }
    setBusy(true); setError(null);
    try {
      const out = await scannerApi.sync(symbols);
      setNote(`Promoted ${out.promoted} of ${symbols.length}.`
              + ' Today\u2019s highs are now tomorrow\u2019s trigger prices.');
      loadResults();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  const toggle = (symbol) => setExcluded((prev) => {
    const next = new Set(prev);
    if (next.has(symbol)) next.delete(symbol); else next.add(symbol);
    return next;
  });

  const rows = data?.rows ?? [];
  const running = status?.running;
  const pct = status?.total ? Math.round((status.progress / status.total) * 100) : 0;
  const allOn = rows.length > 0 && excluded.size === 0;

  return (
    <div className="scan">
      <div className="scan-bar">
        <button className="btn primary" onClick={start} disabled={running}>
          {running ? 'Scanning\u2026' : 'Run ATH scan'}
        </button>
        <button className="btn subtle-btn" onClick={loadResults} disabled={running}>
          Refresh
        </button>
        <button className="btn warn" onClick={sync}
                disabled={running || busy || !rows.length}>
          EOD sync
        </button>
        <span className="scan-msg subtle">{status?.message ?? 'Idle'}</span>
      </div>

      {running && (
        <div className="scan-progress" role="progressbar" aria-valuenow={pct}>
          <div className="scan-progress-fill" style={{ width: `${pct}%` }} />
          <span className="scan-progress-pct num">{pct}%</span>
        </div>
      )}

      {error && <ErrorState error={error} onRetry={loadResults} />}
      {note && <div className="banner compact">{note}</div>}

      {data?.post_sync && (
        <div className="banner compact">
          Post-sync re-scan. Every trigger already equals today&rsquo;s high, so
          <strong> Close &gt; ATH</strong> cannot fire on any row. Expected, not a fault.
        </div>
      )}

      {!hasFetched && !running && !error && (
        <Empty title="Results not loaded"
               hint="Press Refresh to see the last scan, or Run ATH scan to start a new one." />
      )}

      {hasFetched && rows.length === 0 && (
        <Empty title="No ATH hits yet"
               hint="Run a scan, or upload a universe on the Universe tab first." />
      )}

      {hasFetched && rows.length > 0 && (
        <>
          <div className="scan-head">
            <span className="eyebrow">New ATH hits today</span>
            <span className="subtle num">
              {rows.length - excluded.size} of {rows.length} selected for sync
            </span>
          </div>

          <table className="stable">
            <thead>
              <tr>
                <th className="sel">
                  <input type="checkbox" checked={allOn}
                         aria-label="Select all rows"
                         onChange={() => setExcluded(allOn
                           ? new Set(rows.map((r) => r.symbol)) : new Set())} />
                </th>
                <th>Symbol</th>
                <th className="r">New ATH</th>
                <th className="r">Trigger</th>
                <th className="c">ATH O.P.</th>
                <th className="c">Green candle</th>
                <th className="c">Close &gt; ATH</th>
                <th className="c">Profit</th>
                <th className="r">Curr RS</th>
                <th className="r">ATH RS</th>
                <th className="r">Result due</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.symbol}
                    className={excluded.has(r.symbol) ? 'off' : undefined}>
                  <td className="sel">
                    <input type="checkbox" checked={!excluded.has(r.symbol)}
                           aria-label={`Include ${r.symbol} in sync`}
                           onChange={() => toggle(r.symbol)} />
                  </td>
                  <td className="mono strong">{r.symbol}</td>
                  <td className="r num strong">{num(r.new_ath_price)}</td>
                  <td className="r num subtle">{num(r.trigger_price)}</td>
                  <td className="c"><Flag value={r.ath_outperformance} /></td>
                  <td className="c"><Flag value={r.green_candle} /></td>
                  <td className="c"><Flag value={r.close_gt_ath} /></td>
                  <td className="c">
                    <ProfitCell state={r.profit_state} stale={r.profit_stale}
                                resultDate={r.result_date}
                                fetchedAt={data.profit_fetched_at} />
                  </td>
                  <td className="r num">{num(r.current_rs)}</td>
                  <td className="r num subtle">{num(r.ath_rs)}</td>
                  <td className="r subtle">{r.result_date ?? '\u2014'}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="subtle tight">
            {data.profit_fetched_at
              ? `Profit data fetched ${data.profit_fetched_at.replace('T', ' ').slice(0, 16)}.`
              : 'No profit data fetched yet \u2014 every verdict reads as no data.'}
          </p>
        </>
      )}
    </div>
  );
}
