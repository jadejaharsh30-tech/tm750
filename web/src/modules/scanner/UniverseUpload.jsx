/* The scan list, and the profit data the verdict reads from.

   Upload merges: symbols absent from a new file are reported, never deleted,
   so a truncated export cannot silently shrink the universe. Hand-mapped
   ISINs persist, so the handful of renames are a one-time chore rather than
   a recurring one. */
import { useCallback, useEffect, useState } from 'react';
import { scannerApi } from '../../api/scanner';
import { ErrorState, Loading } from '../../components/ui';

export default function UniverseUpload() {
  const [uni, setUni] = useState(null);
  const [profit, setProfit] = useState(null);
  const [error, setError] = useState(null);
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(null);
  const [maps, setMaps] = useState({});

  const load = useCallback(() => {
    setError(null);
    scannerApi.universe().then(setUni).catch(setError);
    scannerApi.profitStatus().then(setProfit).catch(() => setProfit(null));
  }, []);

  useEffect(load, [load]);

  const upload = async (file) => {
    if (!file) return;
    setBusy('upload'); setError(null); setReport(null);
    try {
      setReport(await scannerApi.uploadUniverse(file));
      load();
    } catch (e) { setError(e); } finally { setBusy(null); }
  };

  const fetchProfit = async () => {
    setBusy('profit'); setError(null);
    try {
      const out = await scannerApi.refreshProfit();
      setReport({ profitMsg:
        `Fetched ${out.companies} companies in ${out.seconds}s.` });
      load();
    } catch (e) { setError(e); } finally { setBusy(null); }
  };

  const mapOne = async (symbol) => {
    const isin = (maps[symbol] ?? '').trim().toUpperCase();
    if (isin.length !== 12) {
      setError(new Error(`An ISIN is 12 characters. Got ${isin.length}.`));
      return;
    }
    try {
      await scannerApi.mapSymbol(symbol, isin);
      setMaps({ ...maps, [symbol]: '' });
      load();
    } catch (e) { setError(e); }
  };

  const confirmRemoval = async (symbols) => {
    setBusy('remove');
    try {
      await scannerApi.removeSymbols(symbols);
      setReport(null);
      load();
    } catch (e) { setError(e); } finally { setBusy(null); }
  };

  const [resetPhrase, setResetPhrase] = useState('');
  const resetUniverse = async () => {
    setBusy('reset'); setError(null);
    try {
      const out = await scannerApi.resetUniverse();
      setReport({ profitMsg: `Cleared ${out.removed} symbols from the universe.` });
      setResetPhrase('');
      load();
    } catch (e) { setError(e); } finally { setBusy(null); }
  };

  const unresolved = uni?.unresolved ?? [];

  return (
    <div className="uni">
      <div className="card pad">
        <div className="card-head">
          <span className="eyebrow">Profit data</span>
        </div>
        <p className="subtle tight">
          Pulled straight from the two source sheets. The verdict compares the
          trailing twelve months against every reported financial year, so both
          feeds are needed.
        </p>
        <div className="uni-row">
          <button className="btn primary" onClick={fetchProfit}
                  disabled={busy === 'profit'}>
            {busy === 'profit' ? 'Fetching\u2026' : 'Fetch latest profit data'}
          </button>
          <span className="subtle num">
            {profit?.companies
              ? `${profit.companies.toLocaleString('en-IN')} companies, `
                + `fetched ${profit.fetched_at?.replace('T', ' ').slice(0, 16)}`
              : 'Never fetched'}
          </span>
        </div>
      </div>

      <div className="card pad">
        <div className="card-head">
          <span className="eyebrow">Universe</span>
        </div>
        <p className="subtle tight">
          An Excel file with a symbol column. Headers recognised: Symbol,
          Ticker, NSE Code, Original Symbol, Tradingsymbol. An exchange column
          is optional and defaults to NSE.
        </p>
        <div className="uni-row">
          <label className="btn subtle-btn">
            {busy === 'upload' ? 'Reading\u2026' : 'Choose Excel file'}
            <input type="file" accept=".xlsx,.xls" hidden
                   onChange={(e) => upload(e.target.files?.[0])} />
          </label>
          <span className="subtle num">
            {uni ? `${uni.rows.length} symbols in the scan list` : ''}
          </span>
        </div>
      </div>

      {error && <ErrorState error={error} onRetry={load} />}

      {report?.profitMsg && (
        <div className="banner compact">{report.profitMsg}</div>
      )}

      {report?.total !== undefined && (
        <div className="banner compact">
          {report.inserted} added, {report.updated} updated,{' '}
          {report.resolved} of {report.total} matched to the profit feed.
          {!report.feed_available && ' Fetch the profit data to match ISINs.'}
        </div>
      )}

      {report?.missing?.length > 0 && (
        <div className="card pad warn-card">
          <span className="eyebrow">
            {report.missing.length} symbols are in your saved universe but not
            in this file
          </span>
          <p className="subtle tight">
            Nothing has been removed. Confirm only if you meant to drop them.
          </p>
          <p className="mono tight">{report.missing.join(', ')}</p>
          <button className="btn warn" disabled={busy === 'remove'}
                  onClick={() => confirmRemoval(report.missing)}>
            Remove these {report.missing.length}
          </button>
        </div>
      )}

      {unresolved.length > 0 && (
        <div className="card pad">
          <div className="card-head">
            <span className="eyebrow">
              {unresolved.length} symbols need an ISIN
            </span>
          </div>
          <p className="subtle tight">
            These are renames, demergers and non-companies &mdash; the profit
            feed has no NSE code matching them. They still scan for price and
            all four strategies; only the profit column reads no data. Map one
            and it stays mapped.
          </p>
          <table className="stable">
            <tbody>
              {unresolved.map((u) => (
                <tr key={u.symbol}>
                  <td className="mono strong">{u.symbol}</td>
                  <td>
                    <input className="mdb-input mono" placeholder="INE000A01001"
                           aria-label={`ISIN for ${u.symbol}`}
                           value={maps[u.symbol] ?? ''}
                           onChange={(e) => setMaps(
                             { ...maps, [u.symbol]: e.target.value })} />
                  </td>
                  <td className="r">
                    <button className="btn subtle-btn sm"
                            onClick={() => mapOne(u.symbol)}>Map</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {uni === null && !error && <Loading label="Loading universe" />}

      {uni !== null && (
        <div className="card pad danger-card">
          <div className="card-head">
            <span className="eyebrow">Danger zone</span>
          </div>
          <p className="subtle tight">
            Clears the symbol list entirely, so you can upload a clean file
            from scratch. ATH prices and fetched profit data are not
            affected &mdash; only which symbols are being tracked.
          </p>
          <div className="uni-row">
            <input className="mdb-input" placeholder='Type RESET to enable'
                   value={resetPhrase}
                   aria-label="Type RESET to confirm"
                   onChange={(e) => setResetPhrase(e.target.value)} />
            <button className="btn danger"
                    disabled={resetPhrase.trim().toUpperCase() !== 'RESET'
                             || busy === 'reset'}
                    onClick={resetUniverse}>
              {busy === 'reset' ? 'Clearing\u2026' : 'Clear entire universe'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
