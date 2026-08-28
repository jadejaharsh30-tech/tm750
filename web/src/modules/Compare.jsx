/* Compare.

   The naive version dumps every metric in catalog order and leaves you to
   find the differences. This leads with them: metrics are ranked by how far
   apart the companies actually are, so the rows that distinguish them come
   first and the rows where they agree fall to the bottom.

   Best-in-row comes from the catalog's polarity, resolved server-side. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { formatValue } from '../lib/format';
import {
  CompanySearch, Empty, ErrorState, Loading, TierChip,
} from '../components/ui';

const SEGMENT_ORDER = [
  'Valuation', 'Profitability', 'Growth', 'Performance', 'Trend & Momentum',
  'Technicals', 'Balance Sheet', 'Income Statement', 'Cash Flow', 'Dividend',
  'Ownership', 'History', 'Forecasts', 'Overview', 'Per Share',
];

export default function Compare({ initialSymbols = [], onOpenCompany }) {
  const [symbols, setSymbols] = useState(initialSymbols);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [mode, setMode] = useState('differences');
  const [segment, setSegment] = useState('Valuation');

  const load = useCallback(() => {
    if (symbols.length < 2) { setData(null); return undefined; }
    let cancelled = false;
    setError(null); setData(null);
    api.compare(symbols)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e));
    return () => { cancelled = true; };
  }, [symbols]);

  useEffect(() => load(), [load]);

  function add(sym) {
    setSymbols((s) => (s.includes(sym) || s.length >= 6 ? s : [...s, sym]));
  }
  function remove(sym) { setSymbols((s) => s.filter((x) => x !== sym)); }

  /* Spread: how far apart the companies are on a metric, normalised so a
     ratio and a percentage can be ranked against each other. Metrics where
     everyone agrees are not worth the top of the table. */
  const ranked = useMemo(() => {
    if (!data) return [];
    const out = [];
    for (const [seg, items] of Object.entries(data.metrics ?? {})) {
      for (const m of items) {
        const nums = m.values.filter((v) => typeof v === 'number');
        if (nums.length < 2) continue;
        const lo = Math.min(...nums);
        const hi = Math.max(...nums);
        const base = Math.max(Math.abs(lo), Math.abs(hi));
        if (base === 0) continue;
        out.push({ ...m, segment: seg, spread: (hi - lo) / base });
      }
    }
    return out.sort((a, b) => b.spread - a.spread);
  }, [data]);

  const segments = useMemo(() => {
    const present = Object.keys(data?.metrics ?? {});
    return SEGMENT_ORDER.filter((s) => present.includes(s))
      .concat(present.filter((s) => !SEGMENT_ORDER.includes(s)));
  }, [data]);

  const rows = mode === 'differences'
    ? ranked.slice(0, 30)
    : (data?.metrics?.[segment] ?? []);

  return (
    <div className="module">
      <header className="module-head">
        <div>
          <div className="eyebrow">Two to six companies</div>
          <h1>Compare</h1>
        </div>
        <div className="head-actions">
          <CompanySearch onPick={add} placeholder="Add a company" />
        </div>
      </header>

      {/* Selected companies */}
      <div className="cmp-picks">
        {symbols.map((s) => (
          <span className="cmp-pick" key={s}>
            <span className="mono strong">{s}</span>
            <button onClick={() => remove(s)} aria-label={`Remove ${s}`}>×</button>
          </span>
        ))}
        {symbols.length < 2 && (
          <span className="subtle">
            Add {2 - symbols.length} more to compare
          </span>
        )}
        {symbols.length >= 6 && <span className="subtle">Maximum six</span>}
      </div>

      {symbols.length < 2 && (
        <Empty title="Nothing to compare yet"
               hint="Search above to add companies, or open one from the grid and come back." />
      )}

      {error && <ErrorState error={error} onRetry={load} />}
      {symbols.length >= 2 && !data && !error && <Loading label="Comparing" />}

      {data && (
        <>
          {data.missing?.length > 0 && (
            <div className="banner compact">
              <strong>Not found:</strong> {data.missing.join(', ')}. Check the
              symbol, or search for the company by name.
            </div>
          )}

          {/* Identity header */}
          <div className="cmp-head" style={cols(data.symbols.length)}>
            <span />
            {data.symbols.map((s, i) => (
              <button className="cmp-col" key={s}
                      onClick={() => onOpenCompany?.(s)}>
                <span className="mono strong">{s}</span>
                <span className="subtle ellipsis">{data.names[i]}</span>
                <span className="subtle">{data.sectors[i]}</span>
              </button>
            ))}
          </div>

          <nav className="tabs">
            <button className={`tab ${mode === 'differences' ? 'active' : ''}`}
                    onClick={() => setMode('differences')}>
              Biggest differences
            </button>
            <button className={`tab ${mode === 'segment' ? 'active' : ''}`}
                    onClick={() => setMode('segment')}>
              By segment
            </button>
            {mode === 'segment' && (
              <select className="filter-op cmp-seg" value={segment}
                      onChange={(e) => setSegment(e.target.value)}>
                {segments.map((s) => (
                  <option key={s} value={s}>
                    {s} ({data.metrics[s].length})
                  </option>
                ))}
              </select>
            )}
          </nav>

          {mode === 'differences' && (
            <p className="muted tight">
              Ranked by how far apart these companies are, widest first.
              Metrics where they agree fall to the bottom and are not shown.
            </p>
          )}

          <div className="cmp-table">
            {rows.map((m) => (
              <div className="cmp-row" key={m.name}
                   style={cols(data.symbols.length)}>
                <span className="cmp-label ellipsis" title={m.name}>
                  {m.label}
                  {mode === 'differences' && (
                    <span className="subtle cmp-seg-tag">{m.segment}</span>
                  )}
                </span>
                {m.values.map((v, i) => {
                  const masked = data.masked?.[data.symbols[i]]?.includes(m.name);
                  return (
                    <span key={i}
                          className={`num cmp-val ${m.best_index === i ? 'best' : ''}`}>
                      {masked
                        ? <span className="subtle"
                                title="Not meaningful for financials">n/a</span>
                        : formatValue(v, m)}
                    </span>
                  );
                })}
              </div>
            ))}
            {rows.length === 0 && (
              <Empty title="No comparable metrics"
                     hint="These companies have no overlapping data in this segment." />
            )}
          </div>

          <p className="note">
            Highlighted values are best in row, using each metric's polarity —
            lowest wins on P/E, highest wins on ROE. Metrics with no meaningful
            direction are never highlighted.
          </p>
        </>
      )}
    </div>
  );
}

function cols(n) {
  return { gridTemplateColumns: `minmax(160px, 1.4fr) repeat(${n}, minmax(90px, 1fr))` };
}
