/* The Screener.

   The backend takes a filter DSL, so the job here is to let someone build one
   without knowing it exists. Filters are added from the catalog, so every one
   of the 444 screenable columns is reachable, and the operator set offered is
   the one that makes sense for that column's type.

   State is encoded in the URL, so a screen is a link you can send someone. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { api } from '../api/client';
import { useCatalog } from '../lib/catalog';
import { formatValue, signClass } from '../lib/format';
import { Empty, ErrorState, Loading, RankBar, TierChip } from '../components/ui';
import Info from '../components/Info';

/* Operator vocabulary per column type. Offering "contains" on a number or
   "between" on a boolean is how a builder starts producing 422s. */
const NUMERIC_OPS = [
  { op: 'gte', label: '≥' }, { op: 'lte', label: '≤' },
  { op: 'gt', label: '>' }, { op: 'lt', label: '<' },
  { op: 'between', label: 'between' }, { op: 'eq', label: '=' },
  { op: 'not_null', label: 'has value' }, { op: 'is_null', label: 'is blank' },
];
const TEXT_OPS = [
  { op: 'in', label: 'is one of' }, { op: 'not_in', label: 'is not' },
  { op: 'contains', label: 'contains' },
  { op: 'not_null', label: 'has value' }, { op: 'is_null', label: 'is blank' },
];
const BOOL_OPS = [{ op: 'eq', label: 'is' }];

const NO_VALUE = new Set(['is_null', 'not_null']);

/* Starting points, so the first screen is one click rather than five. */
const PRESETS = [
  {
    id: 'quality-momentum', label: 'Quality momentum',
    hint: 'Trending, profitable, not over-levered',
    filters: [
      { field: 'ema_stack_bullish', op: 'eq', value: true },
      { field: 'roe', op: 'gte', value: 15 },
      { field: 'debt_to_equity', op: 'lte', value: 1 },
      { field: 'perf_1y_pct', op: 'gt', value: 0 },
    ],
  },
  {
    id: 'record-earnings', label: 'Record earnings',
    hint: 'TTM and latest quarter both at an all-time high',
    filters: [{ field: 'pat_both_at_ath', op: 'eq', value: true }],
  },
  {
    id: 'divergent', label: 'Earnings up, price down',
    hint: 'Record profit, negative 12-month return',
    filters: [
      { field: 'pat_both_at_ath', op: 'eq', value: true },
      { field: 'perf_1y_pct', op: 'lt', value: 0 },
    ],
  },
  {
    id: 'value-smallcap', label: 'Small-cap value',
    hint: 'Cheap on earnings and growth, outside the large caps',
    filters: [
      { field: 'cap_tier', op: 'in', value: ['Small', 'Micro'] },
      { field: 'pe_ratio', op: 'between', value: [5, 20] },
      { field: 'peg_ratio', op: 'lte', value: 1 },
      { field: 'roe', op: 'gte', value: 12 },
    ],
  },
  {
    id: 'near-high', label: 'Near 52-week high',
    hint: 'Within 5% of the high, above the 200-day',
    filters: [
      { field: 'dist_52w_high_pct', op: 'gte', value: -5 },
      { field: 'above_ema_200', op: 'eq', value: true },
    ],
  },
];

const RESULT_COLUMNS = [
  'symbol', 'name', 'cap_tier', 'sector', 'market_cap', 'price',
  'perf_1y_pct', 'momentum_12_1_pct', 'pe_ratio', 'roe', 'dist_52w_high_pct',
];

/* ---------------------------------------------------------- URL state */
function encode(filters, sort) {
  const p = new URLSearchParams();
  if (filters.length) p.set('f', btoa(JSON.stringify(filters)));
  if (sort) p.set('s', `${sort.field}:${sort.dir}`);
  return p.toString();
}

function decode() {
  try {
    const p = new URLSearchParams(window.location.search);
    const f = p.get('f') ? JSON.parse(atob(p.get('f'))) : [];
    const s = p.get('s');
    const [field, dir] = s ? s.split(':') : [];
    return { filters: Array.isArray(f) ? f : [],
             sort: field ? { field, dir: dir === 'asc' ? 'asc' : 'desc' } : null };
  } catch {
    return { filters: [], sort: null };
  }
}

export default function Screener({ onOpenCompany }) {
  const catalog = useCatalog();
  const initial = useRef(decode()).current;

  const [filters, setFilters] = useState(initial.filters);
  const [sort, setSort] = useState(
    initial.sort ?? { field: 'market_cap', dir: 'desc' });
  const [rows, setRows] = useState(null);
  const [total, setTotal] = useState(null);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);
  const [enums, setEnums] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => { api.enums().then(setEnums).catch(() => {}); }, []);

  /* Keep the URL in step so a screen is shareable and survives a refresh. */
  useEffect(() => {
    const qs = encode(filters, sort);
    window.history.replaceState(
      null, '', qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  }, [filters, sort]);

  const rankColumns = useMemo(() => {
    if (!catalog.byName) return [];
    return RESULT_COLUMNS.map((c) => `pct_rank_${c}`)
      .filter((r) => catalog.byName[r]);
  }, [catalog.byName]);

  const run = useCallback(() => {
    let cancelled = false;
    setError(null);
    setRows(null);
    api.screen({
      filters: filters.filter(isComplete),
      columns: [...RESULT_COLUMNS, ...rankColumns],
      sort: [sort], limit: 750, include_total: true,
    })
      .then((r) => { if (!cancelled) { setRows(r.rows); setTotal(r.total); } })
      .catch((e) => !cancelled && setError(e));
    return () => { cancelled = true; };
  }, [filters, sort, rankColumns]);

  useEffect(() => run(), [run]);

  const virtualizer = useVirtualizer({
    count: rows?.length ?? 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 32,
    overscan: 12,
  });

  const specs = useMemo(
    () => RESULT_COLUMNS.map((c) => catalog.spec(c)), [catalog]);

  function update(i, patch) {
    setFilters((f) => f.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  }
  function remove(i) { setFilters((f) => f.filter((_, j) => j !== i)); }

  function addField(name) {
    const spec = catalog.spec(name);
    const ops = opsFor(spec);
    setFilters((f) => [...f, {
      field: name, op: ops[0].op,
      value: spec.unit === 'bool' ? true : spec.unit === 'text' ? [] : '',
    }]);
    setAdding(false);
  }

  const active = filters.filter(isComplete).length;

  return (
    <div className="module module-full">
      <header className="ghead">
        <div className="ghead-top">
          <nav className="views">
            {PRESETS.map((p) => (
              <button key={p.id} className="view" title={p.hint}
                      onClick={() => setFilters(p.filters)}>
                {p.label}
              </button>
            ))}
          </nav>
          <div className="ghead-actions">
            <button className="btn" onClick={() => setAdding((a) => !a)}>
              {adding ? 'Close' : '+ Filter'}
            </button>
            {filters.length > 0 && (
              <button className="btn subtle-btn" onClick={() => setFilters([])}>
                Clear
              </button>
            )}
          </div>
        </div>
      </header>

      {adding && (
        <FieldPicker catalog={catalog} onPick={addField}
                     onClose={() => setAdding(false)} />
      )}

      {/* Filter stack */}
      {filters.length > 0 ? (
        <div className="filters">
          {filters.map((f, i) => (
            <FilterRow key={i} filter={f} index={i} catalog={catalog}
                       enums={enums} onChange={update} onRemove={remove} />
          ))}
        </div>
      ) : (
        <div className="filters-empty">
          <span className="muted">
            No filters — showing all 750. Start from a preset above, or add one.
          </span>
        </div>
      )}

      {catalog.snapshotCount > 1 && filters.filter(isComplete).length > 0 && (
        <ScreenChanges filters={filters.filter(isComplete)} />
      )}

      {/* Result count */}
      <div className="ghead-sub">
        <span className="muted">
          {total == null ? 'Running…'
            : <><strong className="num">{total}</strong> of 750 match
                {active > 0 && ` · ${active} filter${active > 1 ? 's' : ''}`}</>}
        </span>
        <span className="subtle">
          Sorted by {catalog.label(sort.field)} {sort.dir === 'desc' ? '↓' : '↑'}
        </span>
      </div>

      {error && <ErrorState error={error} onRetry={run} />}
      {!error && !rows && <Loading label="Screening" />}
      {rows && rows.length === 0 && (
        <Empty title="Nothing matches"
               hint="Loosen a filter, or remove one from the stack above." />
      )}

      {rows && rows.length > 0 && (
        <div className="table-wrap dense" ref={scrollRef}>
          <table className="grid-table" style={{ minWidth: 1180 }}>
            <thead>
              <tr>
                {specs.map((s) => {
                  const w = widthFor(s);
                  return (
                    <th key={s.name} style={{ width: w, flex: `0 0 ${w}px` }}
                        className={[
                          s.unit === 'text' || s.name === 'symbol' ? '' : 'num',
                          sort.field === s.name ? 'sorted' : '',
                        ].join(' ')}
                        onClick={() => setSort((x) => x.field === s.name
                          ? { field: s.name, dir: x.dir === 'desc' ? 'asc' : 'desc' }
                          : { field: s.name, dir: 'desc' })}>
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
                      style={{ position: 'absolute', top: 0, left: 0,
                               width: '100%', height: v.size,
                               transform: `translateY(${v.start}px)` }}
                      onClick={() => onOpenCompany?.(row.symbol)}>
                    {specs.map((s) => (
                      <ResultCell key={s.name} row={row} spec={s}
                                  width={widthFor(s)} />
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

/* What started and stopped matching this screen since the previous
   snapshot -- the single most useful thing history buys a screener. */
function ScreenChanges({ filters }) {
  const [d, setD] = useState(null);
  useEffect(() => {
    let cancelled = false;
    setD(null);
    api.screenChanges(filters)
      .then((r) => !cancelled && setD(r))
      .catch(() => !cancelled && setD(null));
    return () => { cancelled = true; };
  }, [JSON.stringify(filters)]);

  if (!d || (!d.entered.length && !d.exited.length)) return null;
  return (
    <div className="scrchanges">
      <span className="eyebrow">Since {d.from}</span>
      {d.entered.length > 0 && (
        <span className="scrtag up">
          <strong className="num">{d.entered.length}</strong> newly matching:{' '}
          {d.entered.slice(0, 5).map((e) => e.symbol).join(', ')}
          {d.entered.length > 5 && ` +${d.entered.length - 5}`}
        </span>
      )}
      {d.exited.length > 0 && (
        <span className="scrtag down">
          <strong className="num">{d.exited.length}</strong> dropped out:{' '}
          {d.exited.slice(0, 5).map((e) => e.symbol).join(', ')}
          {d.exited.length > 5 && ` +${d.exited.length - 5}`}
        </span>
      )}
    </div>
  );
}

/* ------------------------------------------------------------- helpers */
function opsFor(spec) {
  if (spec.unit === 'bool') return BOOL_OPS;
  if (spec.unit === 'text' || spec.unit === 'date') return TEXT_OPS;
  return NUMERIC_OPS;
}

function isComplete(f) {
  if (NO_VALUE.has(f.op)) return true;
  if (f.op === 'between') {
    return Array.isArray(f.value) && f.value.length === 2
      && f.value.every((v) => v !== '' && v != null && !Number.isNaN(Number(v)));
  }
  if (f.op === 'in' || f.op === 'not_in') {
    return Array.isArray(f.value) && f.value.length > 0;
  }
  return f.value !== '' && f.value != null;
}

function widthFor(s) {
  if (s.name === 'symbol') return 104;
  if (s.name === 'name') return 220;
  if (s.name === 'cap_tier') return 78;
  if (s.name === 'sector') return 150;
  if (s.fmt === 'cr') return 132;
  return 112;
}

/* --------------------------------------------------------- filter row */
function FilterRow({ filter, index, catalog, enums, onChange, onRemove }) {
  const spec = catalog.spec(filter.field);
  const ops = opsFor(spec);
  const options = enums?.[filter.field];

  return (
    <div className="filter">
      <span className="filter-field ellipsis">
        {spec.label}
        <Info text={spec.description} source={spec.description_source}
              name={spec.name} coverage={spec.coverage_pct} />
      </span>

      <select className="filter-op" value={filter.op}
              onChange={(e) => {
                const op = e.target.value;
                onChange(index, {
                  op,
                  value: op === 'between' ? ['', '']
                       : (op === 'in' || op === 'not_in') ? []
                       : spec.unit === 'bool' ? true : '',
                });
              }}>
        {ops.map((o) => (
          <option key={o.op} value={o.op}>{o.label}</option>
        ))}
      </select>

      <FilterValue filter={filter} spec={spec} options={options}
                   onChange={(v) => onChange(index, { value: v })} />

      <button className="filter-x" onClick={() => onRemove(index)}
              aria-label="Remove filter">×</button>
    </div>
  );
}

function FilterValue({ filter, spec, options, onChange }) {
  if (NO_VALUE.has(filter.op)) {
    return <span className="filter-novalue subtle">—</span>;
  }

  if (spec.unit === 'bool') {
    return (
      <select className="filter-val" value={String(filter.value)}
              onChange={(e) => onChange(e.target.value === 'true')}>
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  }

  if (filter.op === 'in' || filter.op === 'not_in') {
    if (options) {
      const sel = new Set(filter.value ?? []);
      return (
        <div className="filter-chips">
          {options.map((o) => (
            <button key={o.value}
                    className={`chipbtn ${sel.has(o.value) ? 'on' : ''}`}
                    onClick={() => {
                      const next = new Set(sel);
                      next.has(o.value) ? next.delete(o.value)
                                        : next.add(o.value);
                      onChange([...next]);
                    }}>
              {o.value} <span className="subtle">{o.count}</span>
            </button>
          ))}
        </div>
      );
    }
    return (
      <input className="filter-val" placeholder="comma separated"
             value={(filter.value ?? []).join(', ')}
             onChange={(e) => onChange(
               e.target.value.split(',').map((x) => x.trim()).filter(Boolean))} />
    );
  }

  if (filter.op === 'between') {
    const v = Array.isArray(filter.value) ? filter.value : ['', ''];
    return (
      <span className="filter-range">
        <input className="filter-val num" inputMode="decimal" value={v[0] ?? ''}
               placeholder="min"
               onChange={(e) => onChange([num(e.target.value), v[1]])} />
        <span className="subtle">and</span>
        <input className="filter-val num" inputMode="decimal" value={v[1] ?? ''}
               placeholder="max"
               onChange={(e) => onChange([v[0], num(e.target.value)])} />
      </span>
    );
  }

  if (spec.unit === 'text') {
    return (
      <input className="filter-val" value={filter.value ?? ''}
             placeholder="text"
             onChange={(e) => onChange(e.target.value)} />
    );
  }

  return (
    <input className="filter-val num" inputMode="decimal"
           value={filter.value ?? ''} placeholder="value"
           onChange={(e) => onChange(num(e.target.value))} />
  );
}

/* Keep the raw string while it is mid-typing ("-", "1.") so the field does
   not fight the user, but hand a real number to the API once it is one. */
function num(s) {
  if (s === '' || s === '-' || s.endsWith('.')) return s;
  const n = Number(s);
  return Number.isNaN(n) ? s : n;
}

/* -------------------------------------------------------- field picker */
function FieldPicker({ catalog, onPick, onClose }) {
  const [q, setQ] = useState('');
  const inputRef = useRef(null);
  useEffect(() => { inputRef.current?.focus(); }, []);

  const segments = (catalog.segments ?? [])
    .map((s) => ({
      ...s,
      columns: s.columns.filter((c) =>
        c.screenable && (!q
          || c.label.toLowerCase().includes(q.toLowerCase())
          || c.name.toLowerCase().includes(q.toLowerCase()))),
    }))
    .filter((s) => s.columns.length);

  const n = segments.reduce((a, s) => a + s.columns.length, 0);

  return (
    <div className="picker card">
      <div className="picker-head">
        <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="Search fields to filter on"
               onKeyDown={(e) => e.key === 'Escape' && onClose()} />
        <span className="muted num">{n} available</span>
      </div>
      <div className="picker-body">
        {segments.map((s) => (
          <div className="picker-seg" key={s.segment}>
            <div className="eyebrow">{s.segment} · {s.columns.length}</div>
            <div className="picker-cols">
              {s.columns.map((c) => (
                <button key={c.name} className="picker-pick ellipsis"
                        title={`${c.name} · ${c.coverage_pct}% coverage`}
                        onClick={() => onPick(c.name)}>
                  {c.label}
                </button>
              ))}
            </div>
          </div>
        ))}
        {n === 0 && (
          <Empty title="No matching field"
                 hint="Try a shorter search term." />
        )}
      </div>
    </div>
  );
}

/* --------------------------------------------------------- result cell */
function ResultCell({ row, spec, width }) {
  const st = { width, minWidth: width, flex: `0 0 ${width}px` };
  const value = row[spec.name];

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
  if (row._masked_fields?.includes(spec.name)) {
    return <td style={st} className="num subtle">n/a</td>;
  }

  const rank = row[`pct_rank_${spec.name}`];
  const isChange = /^(chg|perf|momentum|dist)_/.test(spec.name);

  return (
    <td style={st} className="num">
      <span className="ranked">
        <span className={isChange ? signClass(value, spec.polarity) : ''}>
          {formatValue(value, spec)}
        </span>
        {rank != null && <RankBar value={rank} width={34} />}
      </span>
    </td>
  );
}
