/* The grid. 750 rows against any subset of 462 columns.

   Named views do the work a 462-column picker cannot: each one answers a
   question rather than listing fields. The full picker is still there, but it
   is the second thing you reach for, not the first. */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { api } from '../api/client';
import { useCatalog } from '../lib/catalog';
import { formatValue, signClass } from '../lib/format';
import { ErrorState, Loading, RankBar, TierChip } from '../components/ui';
import Info from '../components/Info';

const ID = ['symbol', 'name', 'cap_tier'];

/* Header rows and body rows must size from the same source or they drift
   apart -- which is exactly what happens if one uses table layout and the
   other uses flex. Every cell, header and band width comes from here. */
function colWidth(spec) {
  switch (spec.name) {
    case 'symbol':   return 104;
    case 'name':     return 210;
    case 'cap_tier': return 78;
    default: break;
  }
  if (spec.unit === 'text') return 132;
  if (spec.unit === 'bool') return 84;
  if (spec.fmt === 'cr') return 132;
  return 112;
}

/* Each view is a question. Identity columns are prepended automatically. */
export const VIEWS = [
  {
    id: 'momentum', label: 'Momentum',
    hint: 'What is moving, and how far it has come',
    columns: ['market_cap', 'price', 'perf_1m_pct', 'perf_3m_pct',
              'perf_1y_pct', 'momentum_12_1_pct', 'dist_52w_high_pct',
              'dist_ath_pct', 'rsi_14'],
  },
  {
    id: 'trend', label: 'Trend',
    hint: 'Where price sits against its own moving averages',
    columns: ['market_cap', 'price', 'chg_1d_pct', 'above_ema_200',
              'above_sma_200', 'ema_stack_bullish', 'dist_ema_200_pct',
              'adx_14', 'atr_pct', 'technical_rating', 'ma_rating'],
  },
  {
    id: 'value', label: 'Value',
    hint: 'What you pay, against what the business earns',
    columns: ['market_cap', 'pe_ratio', 'peg_ratio', 'price_to_book',
              'enterprise_value_to_ebitda_ratio_trailing_12_months', 'earnings_yield_pct', 'dividend_yield',
              'pe_vs_own_5y_pct', 'pe_vs_industry_pct'],
  },
  {
    id: 'quality', label: 'Quality',
    hint: 'Returns on capital, and whether the balance sheet supports them',
    columns: ['market_cap', 'roe', 'roce', 'roic', 'pretax_margin_pct_trailing_12_months',
              'operating_margin_pct_annual', 'debt_to_equity', 'current_ratio_annual',
              'interest_coverage_trailing_12_months', 'piotroski_f_score'],
  },
  {
    id: 'growth', label: 'Growth',
    hint: 'Revenue and profit trajectory',
    columns: ['market_cap', 'revenue_growth_ttm_yoy',
              'net_income_growth_ttm_yoy', 'pat_cagr_3y_pct', 'pat_cagr_5y_pct',
              'pat_yoy_q_pct', 'profitable_fy', 'profit_streak_fy'],
  },
  {
    id: 'ownership', label: 'Ownership',
    hint: 'Who holds it, and whether that is changing',
    columns: ['market_cap', 'promoter_holding', 'pledged_percentage',
              'fii_holding', 'dii_holding', 'public_holding',
              'analyst_rating', 'target_price_1y'],
  },
];

export default function Grid({ onOpenCompany }) {
  const catalog = useCatalog();
  const [view, setView] = useState('momentum');
  const [custom, setCustom] = useState(null);   // non-null once user edits
  const [rows, setRows] = useState(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState(null);
  const [sort, setSort] = useState({ field: 'market_cap', dir: 'desc' });
  const [picker, setPicker] = useState(false);
  const [dense, setDense] = useState(true);
  const [tier, setTier] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const scrollRef = useRef(null);

  /* Only columns the catalog actually knows survive -- a view naming a column
     that was dropped for low coverage degrades quietly instead of 422-ing. */
  const columns = useMemo(() => {
    if (custom) return custom;
    const v = VIEWS.find((x) => x.id === view) ?? VIEWS[0];
    return [...ID, ...v.columns].filter((c) => !catalog.byName || catalog.byName[c]);
  }, [view, custom, catalog.byName]);

  const rankColumns = useMemo(() => {
    if (!catalog.byName) return [];
    return columns.map((c) => `pct_rank_${c}`).filter((r) => catalog.byName[r]);
  }, [columns, catalog.byName]);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setRows(null);
    api.screen({
      columns: [...columns, ...rankColumns],
      filters: tier ? [{ field: 'cap_tier', op: 'eq', value: tier }] : [],
      sort: [sort], limit: 750, include_total: true,
    })
      .then((r) => {
        if (cancelled) return;
        setRows(r.rows); setTotal(r.total);
      })
      .catch((e) => !cancelled && setError(e));
    return () => { cancelled = true; };
  }, [columns, rankColumns, sort, tier, reloadKey]);

  function toggleSort(field) {
    setSort((s) => s.field === field
      ? { field, dir: s.dir === 'desc' ? 'asc' : 'desc' }
      : { field, dir: 'desc' });
  }

  const virtualizer = useVirtualizer({
    count: rows?.length ?? 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => (dense ? 30 : 40),
    overscan: 14,
  });

  const specs = useMemo(
    () => columns.map((c) => catalog.spec(c)), [columns, catalog]);

  /* Segment bands above the header, so a wide table stays legible. */
  const bands = useMemo(() => {
    const out = [];
    for (const s of specs) {
      const seg = ID.includes(s.name) ? 'Company' : s.segment;
      const w = colWidth(s);
      const last = out[out.length - 1];
      if (last && last.segment === seg) last.width += w;
      else out.push({ segment: seg, width: w });
    }
    return out;
  }, [specs]);

  const tableWidth = useMemo(
    () => specs.reduce((a, s) => a + colWidth(s), 0), [specs]);

  const activeView = VIEWS.find((v) => v.id === view);

  return (
    <div className="module module-full">
      <header className="ghead">
        <div className="ghead-top">
          <nav className="views">
            {VIEWS.map((v) => (
              <button key={v.id}
                      className={`view ${!custom && view === v.id ? 'active' : ''}`}
                      onClick={() => { setView(v.id); setCustom(null); }}
                      title={v.hint}>
                {v.label}
              </button>
            ))}
            {custom && <span className="view active">Custom · {custom.length}</span>}
          </nav>

          <div className="ghead-actions">
            <div className="tierfilter">
              {[null, 'Large', 'Mid', 'Small', 'Micro'].map((t) => (
                <button key={t ?? 'all'}
                        className={tier === t ? 'active' : ''}
                        onClick={() => setTier(t)}>
                  {t ?? 'All'}
                </button>
              ))}
            </div>
            <button className="btn" onClick={() => setDense((d) => !d)}
                    title="Row height">
              {dense ? 'Compact' : 'Roomy'}
            </button>
            <button className="btn" onClick={() => setPicker((p) => !p)}>
              {picker ? 'Done' : 'Columns'}
            </button>
          </div>
        </div>
        <div className="ghead-sub">
          <span className="muted">
            {custom ? 'Custom column set'
                    : activeView?.hint}
          </span>
          <span className="subtle num">
            {rows ? `${rows.length} of ${total}` : `${total || 750}`} rows
            {' · '}{columns.length} columns
          </span>
        </div>
      </header>

      {picker && (
        <ColumnPicker catalog={catalog} selected={columns}
                      onChange={setCustom}
                      onReset={() => { setCustom(null); setPicker(false); }} />
      )}

      {error && <ErrorState error={error}
                            onRetry={() => setReloadKey((k) => k + 1)} />}
      {!error && !rows && <Loading label="Loading companies" />}

      {rows && (
        <div className={`table-wrap ${dense ? 'dense' : ''}`} ref={scrollRef}>
          <table className="grid-table" style={{ minWidth: tableWidth }}>
            <thead>
              <tr className="bandrow">
                {bands.map((b, i) => (
                  <th key={i} className="band"
                      style={{ width: b.width, minWidth: b.width,
                               flex: `0 0 ${b.width}px` }}>
                    {b.segment}
                  </th>
                ))}
              </tr>
              <tr>
                {specs.map((s) => {
                  const w = colWidth(s);
                  return (
                    <th key={s.name}
                        style={{ width: w, minWidth: w, flex: `0 0 ${w}px` }}
                        className={[
                          s.unit === 'text' || ID.includes(s.name) ? '' : 'num',
                          sort.field === s.name ? 'sorted' : '',
                        ].join(' ')}
                        onClick={() => toggleSort(s.name)}
                        title={`${s.label} · ${s.coverage_pct}% coverage`}>
                      <span className="th-label">{s.label}</span>
                      {sort.field === s.name && (
                        <span className="sort-arrow">
                          {sort.dir === 'desc' ? '▼' : '▲'}
                        </span>
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody style={{ height: virtualizer.getTotalSize(),
                            position: 'relative' }}>
              {virtualizer.getVirtualItems().map((v) => {
                const row = rows[v.index];
                if (!row) return null;
                return (
                  <tr key={row.symbol ?? v.index} className="grid-row"
                      style={{
                        position: 'absolute', top: 0, left: 0, width: '100%',
                        height: v.size, transform: `translateY(${v.start}px)`,
                      }}
                      onClick={() => onOpenCompany?.(row.symbol)}>
                    {specs.map((s) => (
                      <Cell key={s.name} row={row} spec={s} width={colWidth(s)} />
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Cell({ row, spec, width }) {
  const value = row[spec.name];
  const st = { width, minWidth: width, flex: `0 0 ${width}px` };

  if (spec.name === 'symbol') {
    return <td style={st} className="mono strong">{value ?? '--'}</td>;
  }
  if (spec.name === 'cap_tier') {
    return <td style={st}><TierChip tier={value} /></td>;
  }
  if (spec.unit === 'text') {
    return (
      <td style={st} className="ellipsis" title={value ?? ''}>
        {value ?? '--'}
      </td>
    );
  }
  if (spec.unit === 'bool') {
    return (
      <td style={st} className="num">
        {value === null || value === undefined
          ? <span className="subtle">--</span>
          : <span className={value ? 'up' : 'subtle'}>{value ? '●' : '○'}</span>}
      </td>
    );
  }
  if (row._masked_fields?.includes(spec.name)) {
    return <td style={st} className="num subtle"
               title="Not meaningful for financial companies">n/a</td>;
  }

  const rank = row[`pct_rank_${spec.name}`];
  const isChange = /^(chg|perf|momentum|dist)_/.test(spec.name);

  return (
    <td style={st} className="num">
      <span className="ranked">
        <span className={isChange ? signClass(value, spec.polarity) : ''}>
          {formatValue(value, spec)}
        </span>
        {rank !== undefined && rank !== null && <RankBar value={rank} width={34} />}
      </span>
    </td>
  );
}

function ColumnPicker({ catalog, selected, onChange, onReset }) {
  const [q, setQ] = useState('');
  const sel = new Set(selected);

  function toggle(name) {
    onChange(sel.has(name)
      ? selected.filter((c) => c !== name)
      : [...selected, name]);
  }

  const segments = (catalog.segments ?? [])
    .map((s) => ({
      ...s,
      columns: s.columns.filter((c) =>
        !q || c.label.toLowerCase().includes(q.toLowerCase()) ||
        c.name.toLowerCase().includes(q.toLowerCase())),
    }))
    .filter((s) => s.columns.length);

  return (
    <div className="picker card">
      <div className="picker-head">
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="Filter 462 columns" aria-label="Filter columns" />
        <span className="muted num">{selected.length} selected</span>
        <button className="btn subtle-btn" onClick={onReset}>
          Back to views
        </button>
      </div>
      <div className="picker-body">
        {segments.map((s) => (
          <div className="picker-seg" key={s.segment}>
            <div className="eyebrow">{s.segment} · {s.columns.length}</div>
            <div className="picker-cols">
              {s.columns.map((c) => (
                <label key={c.name} className="picker-col">
                  <input type="checkbox" checked={sel.has(c.name)}
                         onChange={() => toggle(c.name)} />
                  <span className="ellipsis"
                        title={`${c.name} · ${c.coverage_pct}% coverage`}>
                    {c.label}
                  </span>
                </label>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
