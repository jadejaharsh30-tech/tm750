/* Segment pages: sector, industry, cap tier.

   Explorer answers "how do the groups compare". This answers "what is
   actually inside one group" -- the constituents, ranked, with the group's
   own aggregate above them for context. The two are linked in both
   directions, so a row in Explorer opens here and a header here goes back.

   Percentile ranks shown are within-sector where the data layer computed
   them, because a stock's position inside its own sector is a different and
   usually more useful question than its position across all 750. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { api } from '../api/client';
import { useCatalog } from '../lib/catalog';
import { formatValue, pctSigned, signClass } from '../lib/format';
import {
  Empty, ErrorState, Loading, RankBar, Stat, TierChip,
} from '../components/ui';

const DIMS = [
  { id: 'sector', label: 'Sector', field: 'sector' },
  { id: 'industry', label: 'Industry', field: 'industry' },
  { id: 'tier', label: 'Cap tier', field: 'cap_tier' },
];

const COLUMNS = [
  'symbol', 'name', 'cap_tier', 'market_cap', 'price', 'chg_1d_pct',
  'perf_1y_pct', 'momentum_12_1_pct', 'pe_ratio', 'roe',
  'dist_52w_high_pct', 'fii_holding',
];

const WIDTHS = {
  symbol: 104, name: 200, cap_tier: 76, market_cap: 128, price: 100,
};

export default function Segment({ dim: initialDim = 'sector',
                                  value: initialValue = null,
                                  onOpenCompany, onChangeSelection }) {
  const catalog = useCatalog();
  const [dim, setDim] = useState(initialDim);
  const [value, setValue] = useState(initialValue);
  const [enums, setEnums] = useState(null);
  const [rows, setRows] = useState(null);
  const [agg, setAgg] = useState(null);
  const [error, setError] = useState(null);
  const [sort, setSort] = useState({ field: 'market_cap', dir: 'desc' });
  const scrollRef = useRef(null);

  useEffect(() => { api.enums().then(setEnums).catch(() => {}); }, []);

  // Group aggregate, for the context strip above the constituents.
  useEffect(() => {
    let cancelled = false;
    api.explore(dim)
      .then((d) => !cancelled && setAgg(d))
      .catch(() => !cancelled && setAgg(null));
    return () => { cancelled = true; };
  }, [dim]);

  const field = DIMS.find((d) => d.id === dim)?.field ?? 'sector';

  const rankColumns = useMemo(() => {
    if (!catalog.byName) return [];
    // Prefer within-sector ranks: position inside the peer group is the
    // question this page exists to answer.
    const scope = dim === 'sector' ? '_in_sector' : '';
    return COLUMNS.flatMap((c) => [`pct_rank_${c}${scope}`, `pct_rank_${c}`])
      .filter((r) => catalog.byName[r]);
  }, [catalog.byName, dim]);

  const load = useCallback(() => {
    if (!value) { setRows(null); return undefined; }
    let cancelled = false;
    setError(null); setRows(null);
    api.screen({
      filters: [{ field, op: 'eq', value }],
      columns: [...COLUMNS, ...rankColumns],
      sort: [sort], limit: 750, include_total: true,
    })
      .then((r) => !cancelled && setRows(r.rows))
      .catch((e) => !cancelled && setError(e));
    return () => { cancelled = true; };
  }, [field, value, sort, rankColumns]);

  useEffect(() => load(), [load]);

  const options = useMemo(() => {
    const key = dim === 'tier' ? 'cap_tier' : field;
    return enums?.[key] ?? [];
  }, [enums, dim, field]);

  const groupAgg = useMemo(
    () => agg?.groups?.find((g) => g.group === value), [agg, value]);

  const virtualizer = useVirtualizer({
    count: rows?.length ?? 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 32,
    overscan: 12,
  });

  const specs = useMemo(() => COLUMNS.map((c) => catalog.spec(c)), [catalog]);
  const width = (s) => WIDTHS[s.name] ?? (s.fmt === 'cr' ? 128 : 108);

  function select(dimId, val) {
    setDim(dimId);
    setValue(val);
    onChangeSelection?.(dimId, val);
  }

  return (
    <div className="module module-full">
      <header className="ghead">
        <div className="ghead-top">
          <div className="views">
            {DIMS.map((d) => (
              <button key={d.id} className={`view ${dim === d.id ? 'active' : ''}`}
                      onClick={() => select(d.id, null)}>
                {d.label}
              </button>
            ))}
          </div>
          <div className="ghead-actions">
            <select className="filter-op seg-select" value={value ?? ''}
                    onChange={(e) => select(dim, e.target.value || null)}>
              <option value="">Choose a {dim === 'tier' ? 'tier' : dim}…</option>
              {options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.value} ({o.count})
                </option>
              ))}
            </select>
          </div>
        </div>
      </header>

      {/* Quick links -- the whole list, one click each */}
      {!value && (
        <section className="card pad">
          <div className="eyebrow">
            Pick a {dim === 'tier' ? 'cap tier' : dim} · {options.length} available
          </div>
          <div className="seglinks">
            {options.map((o) => (
              <button className="seglink" key={o.value}
                      onClick={() => select(dim, o.value)}>
                <span className="ellipsis">{o.value}</span>
                <span className="subtle num">{o.count}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {value && (
        <>
          <header className="module-head">
            <div>
              <div className="eyebrow">
                {DIMS.find((d) => d.id === dim)?.label}
              </div>
              <h1>{value}</h1>
            </div>
          </header>

          {groupAgg && (
            <section className="stat-row">
              <Stat label="Companies" value={groupAgg.n} />
              <Stat label="Total market cap"
                    value={`₹${groupAgg.mcap_lakh_cr} L Cr`} />
              <Stat label="Median P/E" value={groupAgg.pe_ratio_median ?? '--'} />
              <Stat label="Median ROE" value={groupAgg.roe_median ?? '--'} />
              <Stat label="Median 1Y"
                    value={pctSigned(groupAgg.perf_1y_pct_median)}
                    tone={groupAgg.perf_1y_pct_median >= 0 ? 'up' : 'down'} />
              <Stat label="Above EMA200"
                    value={`${groupAgg.pct_above_ema200 ?? '--'}%`} />
            </section>
          )}

          {error && <ErrorState error={error} onRetry={load} />}
          {!rows && !error && <Loading label={`Loading ${value}`} />}
          {rows && rows.length === 0 && (
            <Empty title={`No companies in ${value}`} />
          )}

          {rows && rows.length > 0 && (
            <div className="table-wrap dense" ref={scrollRef}>
              <table className="grid-table"
                     style={{ minWidth: specs.reduce((a, s) => a + width(s), 0) }}>
                <thead>
                  <tr>
                    {specs.map((s) => {
                      const w = width(s);
                      return (
                        <th key={s.name}
                            style={{ width: w, flex: `0 0 ${w}px` }}
                            className={[
                              s.unit === 'text' || s.name === 'symbol' ? '' : 'num',
                              sort.field === s.name ? 'sorted' : '',
                            ].join(' ')}
                            onClick={() => setSort((x) => x.field === s.name
                              ? { field: s.name,
                                  dir: x.dir === 'desc' ? 'asc' : 'desc' }
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
                          <SegCell key={s.name} row={row} spec={s}
                                   width={width(s)} inSector={dim === 'sector'} />
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {rows && dim === 'sector' && (
            <p className="note">
              Rank hairlines are within {value}, not across all 750 — a
              stock's position among its own peers is usually the more useful
              comparison.
            </p>
          )}
        </>
      )}
    </div>
  );
}

function SegCell({ row, spec, width, inSector }) {
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

  const rank = (inSector ? row[`pct_rank_${spec.name}_in_sector`] : undefined)
    ?? row[`pct_rank_${spec.name}`];
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
