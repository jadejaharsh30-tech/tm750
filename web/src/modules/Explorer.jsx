/* Explorer.

   Cross-sectional aggregation: pick a dimension, pick a metric, see how the
   groups line up. The sort is on the chosen metric, so the ranking is the
   answer rather than something you assemble by reading.

   Financial companies are excluded from ROCE/ROIC medians server-side, and
   the API says so -- that note is surfaced rather than swallowed. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { useCatalog } from '../lib/catalog';
import { formatValue } from '../lib/format';
import { ErrorState, Loading, TierChip } from '../components/ui';

const DIMENSIONS = [
  { id: 'sector', label: 'Sector' },
  { id: 'industry', label: 'Industry' },
  { id: 'tier', label: 'Cap tier' },
];

/* Metrics worth ranking groups on. Kept short: a forty-column aggregation
   table is a data dump, not a view. */
const METRICS = [
  { name: 'pe_ratio_median', label: 'Median P/E', src: 'pe_ratio' },
  { name: 'peg_ratio_median', label: 'Median PEG', src: 'peg_ratio' },
  { name: 'price_to_book_median', label: 'Median P/B', src: 'price_to_book' },
  { name: 'roe_median', label: 'Median ROE', src: 'roe' },
  { name: 'roce_median', label: 'Median ROCE', src: 'roce' },
  { name: 'perf_1y_pct_median', label: '1Y return', src: 'perf_1y_pct' },
  { name: 'perf_3m_pct_median', label: '3M return', src: 'perf_3m_pct' },
  { name: 'momentum_12_1_pct_median', label: '12-1 momentum',
    src: 'momentum_12_1_pct' },
  { name: 'dist_ath_pct_median', label: 'From all-time high',
    src: 'dist_ath_pct' },
  { name: 'dist_52w_high_pct_median', label: 'From 52W high',
    src: 'dist_52w_high_pct' },
  { name: 'rsi_14_median', label: 'RSI 14', src: 'rsi_14' },
  { name: 'fii_holding_median', label: 'FII holding', src: 'fii_holding' },
  { name: 'dii_holding_median', label: 'DII holding', src: 'dii_holding' },
  { name: 'promoter_holding_median', label: 'Promoter holding',
    src: 'promoter_holding' },
  { name: 'dividend_yield_median', label: 'Dividend yield',
    src: 'dividend_yield' },
  { name: 'revenue_growth_ttm_yoy_median', label: 'Revenue growth TTM',
    src: 'revenue_growth_ttm_yoy' },
  { name: 'pat_cagr_5y_pct_median', label: 'PAT CAGR 5Y',
    src: 'pat_cagr_5y_pct' },
  { name: 'pct_above_ema200', label: '% above EMA200', src: null },
  { name: 'pct_ema_stacked', label: '% in full EMA stack', src: null },
  { name: 'mcap_lakh_cr', label: 'Total market cap', src: null },
];

export default function Explorer({ onOpenSegment }) {
  const catalog = useCatalog();
  const [dim, setDim] = useState('sector');
  const [metric, setMetric] = useState('pe_ratio_median');
  const [dir, setDir] = useState('desc');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [minN, setMinN] = useState(3);

  const load = useCallback(() => {
    let cancelled = false;
    setError(null); setData(null);
    api.explore(dim)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e));
    return () => { cancelled = true; };
  }, [dim]);

  useEffect(() => load(), [load]);

  const spec = METRICS.find((m) => m.name === metric) ?? METRICS[0];
  const colSpec = spec.src ? catalog.spec(spec.src)
                           : { fmt: '0.1f%', unit: 'pct' };

  const rows = useMemo(() => {
    const gs = (data?.groups ?? []).filter((g) => g.n >= minN);
    return [...gs].sort((a, b) => {
      const av = a[metric], bv = b[metric];
      if (av == null) return 1;
      if (bv == null) return -1;
      return dir === 'desc' ? bv - av : av - bv;
    });
  }, [data, metric, dir, minN]);

  const max = useMemo(
    () => Math.max(...rows.map((r) => Math.abs(r[metric] ?? 0)), 1), [rows, metric]);
  const anyNegative = rows.some((r) => (r[metric] ?? 0) < 0);

  return (
    <div className="module">
      <header className="module-head">
        <div>
          <div className="eyebrow">Cross-section</div>
          <h1>Explorer</h1>
        </div>
      </header>

      <div className="exp-controls">
        <div className="views">
          {DIMENSIONS.map((d) => (
            <button key={d.id} className={`view ${dim === d.id ? 'active' : ''}`}
                    onClick={() => setDim(d.id)}>
              {d.label}
            </button>
          ))}
        </div>

        <select className="filter-op exp-metric" value={metric}
                onChange={(e) => setMetric(e.target.value)}>
          {METRICS.map((m) => (
            <option key={m.name} value={m.name}>{m.label}</option>
          ))}
        </select>

        <button className="btn" onClick={() => setDir((d) => d === 'desc' ? 'asc' : 'desc')}>
          {dir === 'desc' ? 'Highest first' : 'Lowest first'}
        </button>

        {dim === 'industry' && (
          <label className="exp-min">
            <span className="subtle">Min companies</span>
            <input type="number" min="1" max="30" value={minN}
                   className="filter-val num"
                   onChange={(e) => setMinN(Number(e.target.value) || 1)} />
          </label>
        )}
      </div>

      {error && <ErrorState error={error} onRetry={load} />}
      {!data && !error && <Loading label="Loading cross-section" />}

      {data && (
        <>
          {data.note && (
            <div className="banner compact">{data.note}</div>
          )}

          <section className="card pad">
            <div className="card-head">
              <div className="eyebrow">
                {spec.label} by {dim} · {rows.length} groups
              </div>
              <span className="subtle num">
                {rows.reduce((a, r) => a + r.n, 0)} companies
              </span>
            </div>

            <div className="explist">
              {rows.map((g) => {
                const v = g[metric];
                const w = v == null ? 0 : (100 * Math.abs(v)) / max;
                return (
                  <div className="exprow" key={g.group}>
                    <button className="exprow-label exprow-link ellipsis"
                            title={`Open ${g.group}`}
                            onClick={() => onOpenSegment?.(dim, g.group)}>
                      {dim === 'tier' ? <TierChip tier={g.group} /> : g.group}
                    </button>
                    <span className="num subtle exprow-n">{g.n}</span>
                    <span className={`exprow-track ${anyNegative ? 'signed' : ''}`}>
                      <span className={`exprow-fill ${v < 0 ? 'neg' : ''}`}
                            style={{ width: `${w}%` }} />
                    </span>
                    <span className="num exprow-val">
                      {v == null ? '--' : formatValue(v, colSpec)}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Full table, so the chosen metric is not the only thing visible */}
          <section className="card pad">
            <div className="eyebrow">All metrics</div>
            <p className="muted tight">
              Median values per group. Scroll sideways for the rest.
            </p>
            <div className="exp-tablewrap">
              <table className="mini exp-table">
                <thead>
                  <tr>
                    <th>Group</th><th className="num">n</th>
                    <th className="num">P/E</th><th className="num">PEG</th>
                    <th className="num">P/B</th><th className="num">ROE</th>
                    <th className="num">1Y</th><th className="num">12-1</th>
                    <th className="num">From ATH</th><th className="num">RSI</th>
                    <th className="num">FII</th><th className="num">DII</th>
                    <th className="num">&gt;EMA200</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((g) => (
                    <tr key={g.group}>
                      <td className="ellipsis" title={g.group}>
                        <button className="exprow-link"
                                onClick={() => onOpenSegment?.(dim, g.group)}>
                          {dim === 'tier' ? <TierChip tier={g.group} /> : g.group}
                        </button>
                      </td>
                      <td className="num subtle">{g.n}</td>
                      <td className="num">{g.pe_ratio_median ?? '--'}</td>
                      <td className="num">{g.peg_ratio_median ?? '--'}</td>
                      <td className="num">{g.price_to_book_median ?? '--'}</td>
                      <td className="num">{g.roe_median ?? '--'}</td>
                      <td className={num(g.perf_1y_pct_median)}>
                        {fmt(g.perf_1y_pct_median)}
                      </td>
                      <td className={num(g.momentum_12_1_pct_median)}>
                        {fmt(g.momentum_12_1_pct_median)}
                      </td>
                      <td className="num down">{fmt(g.dist_ath_pct_median)}</td>
                      <td className="num">{g.rsi_14_median ?? '--'}</td>
                      <td className="num subtle">{g.fii_holding_median ?? '--'}</td>
                      <td className="num subtle">{g.dii_holding_median ?? '--'}</td>
                      <td className="num">{g.pct_above_ema200 ?? '--'}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

const num = (v) => `num ${v == null ? '' : v >= 0 ? 'up' : 'down'}`;
const fmt = (v) => (v == null ? '--' : `${v > 0 ? '+' : ''}${v}%`);
