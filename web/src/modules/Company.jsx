/* Company card.

   Three levels of structure rather than two: tab, then concept group, then
   datapoint. The grouping comes from the catalog, so the Grid's column
   picker and the Screener's field picker share exactly this taxonomy instead
   of each inventing their own.

   The largest tab held ninety tiles in one flat wall; the largest group now
   holds seventeen. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../api/client';
import { useCatalog } from '../lib/catalog';
import { formatCompact, formatValue, signClass } from '../lib/format';
import { Empty, ErrorState, Loading, RankBar, TierChip } from '../components/ui';
import RangeBars from '../components/RangeBars';
import DatapointSearch from '../components/DatapointSearch';
import TrendChart from '../components/TrendChart';
import Info from '../components/Info';

const TABS = [
  { id: 'snapshot',  label: 'Snapshot',
    segments: ['Overview', 'Performance', 'Per Share'] },
  { id: 'valuation', label: 'Valuation', segments: ['Valuation'] },
  { id: 'quality',   label: 'Quality',
    segments: ['Profitability', 'Balance Sheet', 'Cash Flow'] },
  { id: 'growth',    label: 'Growth',
    segments: ['Growth', 'Income Statement', 'History'] },
  { id: 'trend',     label: 'Trend',
    segments: ['Trend & Momentum', 'Technicals'] },
  { id: 'ownership', label: 'Ownership',
    segments: ['Ownership', 'Dividend', 'Forecasts'] },
];

const HEADLINE = [
  'market_cap', 'price', 'chg_1d_pct', 'perf_1y_pct', 'pe_ratio', 'roe',
];

/* Every tab opens fully collapsed -- just the group headings and counts,
   so scanning a tab means reading a table of contents rather than a wall of
   tiles. Nothing pre-opens by default; the search jump (Ctrl/Cmd+K) is the
   fast path when you know exactly which datapoint you want. */
const OPEN_BY_DEFAULT = {};

export default function Company({ symbol }) {
  const catalog = useCatalog();
  const [data, setData] = useState(null);
  const [history, setHistory] = useState(null);
  const [freq, setFreq] = useState('FY');
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('snapshot');
  const [open, setOpen] = useState(new Set());
  const [hideEmpty, setHideEmpty] = useState(true);
  const [dense, setDense] = useState(false);
  const [flash, setFlash] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const tileRefs = useRef({});

  useEffect(() => {
    if (!symbol) return undefined;
    let cancelled = false;
    setError(null); setData(null); setTab('snapshot');
    api.company(symbol)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e));
    return () => { cancelled = true; };
  }, [symbol, reloadKey]);

  useEffect(() => {
    if (!symbol) return undefined;
    let cancelled = false;
    setHistory(null);
    api.history(symbol, freq)
      .then((h) => !cancelled && setHistory(h))
      .catch(() => !cancelled && setHistory({ series: [] }));
    return () => { cancelled = true; };
  }, [symbol, freq, reloadKey]);

  // Default-open groups follow the tab.
  useEffect(() => {
    setOpen(new Set(OPEN_BY_DEFAULT[tab] ?? []));
  }, [tab]);

  const masked = useMemo(
    () => new Set(data?.masked_fields ?? []), [data]);

  const flat = useMemo(() => {
    const out = {};
    for (const items of Object.values(data?.segments ?? {})) {
      for (const it of items ?? []) out[it.name] = it;
    }
    return out;
  }, [data]);

  /* Every datapoint, flattened with the tab it lives on -- this is what the
     search index needs, and it costs one pass. */
  const searchIndex = useMemo(() => {
    const out = [];
    for (const t of TABS) {
      for (const seg of t.segments) {
        for (const it of data?.segments?.[seg] ?? []) {
          out.push({ ...it, tab: t.id, tabLabel: t.label,
                     masked: masked.has(it.name) });
        }
      }
    }
    return out;
  }, [data, masked]);

  const jump = useCallback((hit) => {
    setTab(hit.tab);
    setOpen((s) => new Set(s).add(hit.group));
    setFlash(hit.name);
    // Wait for the tab switch and group expansion to render.
    setTimeout(() => {
      const el = tileRefs.current[hit.name];
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 60);
    setTimeout(() => setFlash(null), 2200);
  }, []);

  if (!symbol) {
    return (
      <div className="module">
        <Empty title="No company selected"
               hint="Search above, or click any row in the grid." />
      </div>
    );
  }
  if (error) {
    return (
      <div className="module">
        <ErrorState error={error} onRetry={() => setReloadKey((k) => k + 1)} />
      </div>
    );
  }
  if (!data) {
    return <div className="module"><Loading label={`Loading ${symbol}`} /></div>;
  }

  const active = TABS.find((t) => t.id === tab) ?? TABS[0];
  const claimed = new Set(TABS.flatMap((t) => t.segments));
  const segments = tab === 'ownership'
    ? [...active.segments,
       ...Object.keys(data.segments ?? {}).filter((s) => !claimed.has(s))]
    : active.segments;

  // Segment -> group -> items, preserving catalog order within a group.
  const grouped = [];
  let hiddenEmpty = 0;
  for (const seg of segments) {
    const byGroup = new Map();
    for (const it of data.segments?.[seg] ?? []) {
      const empty = it.value === null || it.value === undefined
        || masked.has(it.name);
      if (empty) hiddenEmpty += 1;
      if (hideEmpty && empty) continue;
      const g = it.group || 'Other';
      if (!byGroup.has(g)) byGroup.set(g, []);
      byGroup.get(g).push(it);
    }
    if (byGroup.size) grouped.push({ segment: seg, groups: [...byGroup] });
  }

  return (
    <div className="module">
      <header className="chero">
        <div className="chero-id">
          <h1 className="mono">{data.symbol}</h1>
          <div className="chero-meta">
            <span className="chero-name ellipsis">{data.name}</span>
            <span className="chero-tags">
              <TierChip tier={data.cap_tier} />
              <span className="subtle">{data.sector}</span>
            </span>
          </div>
        </div>
        <div className="chero-stats">
          {HEADLINE.map((name) => {
            const it = flat[name];
            if (!it) return null;
            const rank = data.percentile_ranks?.[name];
            const change = /^(perf|chg|momentum)_/.test(name);
            return (
              <div className="cstat" key={name}>
                <span className="cstat-label ellipsis">{it.label}</span>
                <span className={`cstat-value num ${change ? signClass(it.value, it.polarity) : ''}`}>
                  {masked.has(name) ? 'n/a' : formatValue(it.value, it)}
                </span>
                <RankBar value={rank?.universe} width={50} />
              </div>
            );
          })}
        </div>
      </header>

      <AthBadges flat={flat} />

      {masked.size > 0 && (
        <div className="banner compact">
          <strong>{masked.size} metrics withheld.</strong> ROCE, ROIC and
          leverage ratios are not meaningful for financial companies, so they
          are hidden rather than shown as misleading numbers.
        </div>
      )}

      {/* Tab bar, with the datapoint search filling the space on the right */}
      <nav className="tabs tabs-with-search">
        <div className="tabs-list">
          {TABS.map((t) => {
            const n = t.segments.reduce(
              (a, s) => a + (data.segments?.[s]?.length ?? 0), 0);
            return (
              <button key={t.id}
                      className={`tab ${tab === t.id ? 'active' : ''}`}
                      onClick={() => setTab(t.id)}>
                {t.label}<span className="tab-n num">{n}</span>
              </button>
            );
          })}
        </div>
        <DatapointSearch items={searchIndex} onJump={jump} />
      </nav>

      {tab === 'snapshot' && (
        <>
          <div className="grid-2">
            <section className="card pad">
              <div className="card-head">
                <div className="eyebrow">Profit after tax</div>
                <div className="seg-toggle">
                  {['FY', 'Q'].map((f) => (
                    <button key={f} className={freq === f ? 'active' : ''}
                            onClick={() => setFreq(f)}>
                      {f === 'FY' ? 'Annual' : 'Quarterly'}
                    </button>
                  ))}
                </div>
              </div>
              <ProfitChart history={history} />
            </section>

            <section className="card pad">
              <div className="eyebrow">Percentile position</div>
              <p className="muted tight">
                100 = highest in the group. Polarity is not applied: a high
                P/E percentile means expensive, not good.
              </p>
              <div className="rank-head eyebrow">
                <span>Metric</span><span>All 750</span><span>{data.sector}</span>
              </div>
              <div className="ranks">
                {Object.entries(data.percentile_ranks ?? {}).map(([name, r]) => (
                  <div className="rank-row" key={name}>
                    <span className="rank-label ellipsis">
                      {catalog.label(name)}
                    </span>
                    <span className="rank-scope">
                      <RankBar value={r?.universe} width={62} title="vs all 750" />
                      <span className="num subtle">
                        {r?.universe?.toFixed(0) ?? '--'}
                      </span>
                    </span>
                    <span className="rank-scope">
                      <RankBar value={r?.sector} width={62}
                               title={`vs ${data.sector}`} />
                      <span className="num subtle">
                        {r?.sector?.toFixed(0) ?? '--'}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            </section>
          </div>

          <RangeBars flat={flat} />
          <TrendChart symbol={symbol}
                      snapshotCount={catalog.snapshotCount ?? 1} />
        </>
      )}

      {/* View controls */}
      <div className="viewbar">
        <label className="toggle">
          <input type="checkbox" checked={hideEmpty}
                 onChange={(e) => setHideEmpty(e.target.checked)} />
          <span>Hide empty</span>
          {hiddenEmpty > 0 && (
            <span className="subtle num">{hiddenEmpty}</span>
          )}
        </label>
        <div className="seg-toggle">
          {[['tiles', false], ['table', true]].map(([label, v]) => (
            <button key={label} className={dense === v ? 'active' : ''}
                    onClick={() => setDense(v)}>
              {label}
            </button>
          ))}
        </div>
        <button className="btn subtle-btn" onClick={() => {
          const all = grouped.flatMap((s) => s.groups.map(([g]) => g));
          setOpen((s) => (s.size >= all.length ? new Set() : new Set(all)));
        }}>
          {open.size >= grouped.flatMap((s) => s.groups).length
            ? 'Collapse all' : 'Expand all'}
        </button>
      </div>

      {/* Grouped datapoints */}
      {grouped.map(({ segment, groups }) => (
        <section className="segblock" key={segment}>
          <div className="segblock-head">
            <span className="eyebrow">{segment}</span>
            <span className="subtle num">
              {groups.reduce((a, [, items]) => a + items.length, 0)}
            </span>
          </div>

          {groups.map(([group, items]) => {
            const isOpen = open.has(group);
            return (
              <div className={`groupblock ${isOpen ? 'open' : ''}`} key={group}>
                <button className="groupblock-head"
                        aria-expanded={isOpen}
                        onClick={() => setOpen((s) => {
                          const n = new Set(s);
                          n.has(group) ? n.delete(group) : n.add(group);
                          return n;
                        })}>
                  <span className="groupblock-caret">{isOpen ? '−' : '+'}</span>
                  <span className="groupblock-title">{group}</span>
                  <span className="subtle num">{items.length}</span>
                </button>

                {isOpen && (dense ? (
                  <table className="mini dptable">
                    <tbody>
                      {items.map((it) => (
                        <tr key={it.name}
                            ref={(el) => { tileRefs.current[it.name] = el; }}
                            className={flash === it.name ? 'flash' : ''}>
                          <td className="ellipsis">
                            {it.label}
                            <Info text={it.description}
                                  source={it.description_source}
                                  name={it.name} />
                          </td>
                          <td className="num strong">
                            {masked.has(it.name) ? <span className="subtle">n/a</span>
                              : formatValue(it.value, it)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="tiles">
                    {items.map((it) => (
                      <MetricTile key={it.name} item={it}
                                  masked={masked.has(it.name)}
                                  rank={data.percentile_ranks?.[it.name]}
                                  flash={flash === it.name}
                                  innerRef={(el) => {
                                    tileRefs.current[it.name] = el;
                                  }} />
                    ))}
                  </div>
                ))}
              </div>
            );
          })}
        </section>
      ))}

      {tab === 'ownership' && data.index_memberships?.length > 0 && (
        <section className="segblock">
          <div className="segblock-head">
            <span className="eyebrow">Index membership</span>
            <span className="subtle num">{data.index_memberships.length}</span>
          </div>
          <div className="tags">
            {data.index_memberships.map((m) => (
              <span className="tag" key={m}>{m}</span>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function MetricTile({ item, masked, rank, flash, innerRef }) {
  const change = /^(perf|chg|momentum|dist)_/.test(item.name);
  return (
    <div className={`tile ${flash ? 'flash' : ''}`} ref={innerRef}>
      <span className="tile-label ellipsis">
        {item.label}
        <Info text={item.description} source={item.description_source}
              name={item.name} />
      </span>
      <span className={`tile-value num ${change ? signClass(item.value, item.polarity) : ''}`}>
        {masked
          ? <span className="subtle" title="Not meaningful for financials">n/a</span>
          : formatValue(item.value, item)}
      </span>
      {rank?.universe !== undefined && (
        <span className="tile-rank">
          <RankBar value={rank.universe} width={38} />
          <span className="subtle num">{rank.universe?.toFixed(0)}</span>
        </span>
      )}
    </div>
  );
}

function AthBadges({ flat }) {
  const ttm = flat.pat_ttm_at_ath?.value;
  const q = flat.pat_q_at_ath?.value;
  const fy = flat.pat_fy_at_ath?.value;
  if (ttm === undefined && q === undefined) return null;

  const items = [
    { on: ttm, label: 'TTM PAT', gap: flat.pat_ttm_vs_fy_peak_pct?.value,
      note: 'vs financial years' },
    { on: q, label: 'Latest quarter', gap: flat.pat_q_vs_peak_pct?.value,
      note: 'most recent' },
    { on: fy, label: 'Annual PAT', gap: flat.pat_vs_peak_pct?.value,
      note: 'reference', ref: true },
  ];

  return (
    <div className="athrow">
      {ttm && q && (
        <div className="athbadge hit lead">
          <span className="athbadge-mark">{'\u2713'}</span>
          <span className="athbadge-text">
            <span className="athbadge-label">Earnings at a record</span>
            <span className="subtle">
              Rolling year and latest quarter both at a high
            </span>
          </span>
        </div>
      )}
      {items.map((it) => (
        <div className={`athbadge ${it.on ? 'hit' : ''} ${it.ref ? 'ref' : ''}`}
             key={it.label}>
          <span className="athbadge-mark">{it.on ? '\u2713' : ''}</span>
          <span className="athbadge-text">
            <span className="athbadge-label">
              {it.label} <span className="subtle">· {it.note}</span>
            </span>
            <span className="subtle num">
              {it.on ? 'at all-time high'
                     : it.gap != null ? `${it.gap.toFixed(1)}% from peak`
                     : 'no history'}
            </span>
          </span>
        </div>
      ))}
    </div>
  );
}

function ProfitChart({ history }) {
  if (!history) return <Loading label="Loading history" />;
  if (!history.series?.length) {
    return <Empty title="No profit history"
                  hint="No reported periods for this company in the source files." />;
  }
  const data = [...history.series].reverse();
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <XAxis dataKey="period" tick={{ fontSize: 10, fill: 'var(--fg-subtle)' }}
               axisLine={false} tickLine={false} interval="preserveStartEnd" />
        <YAxis tick={{ fontSize: 10, fill: 'var(--fg-subtle)' }}
               axisLine={false} tickLine={false} width={56}
               tickFormatter={(v) => formatCompact(v * 1e7, { fmt: 'cr' })} />
        <Tooltip content={<PatTooltip />} cursor={{ fill: 'var(--bg-hover)' }} />
        <Bar dataKey="pat" radius={[2, 2, 0, 0]}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.pat >= 0 ? 'var(--up)' : 'var(--down)'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function PatTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const v = payload[0].value;
  return (
    <div className="tooltip">
      <div className="tooltip-label">{label}</div>
      <div className={`num ${v >= 0 ? 'up' : 'down'}`}>
        ₹{v?.toLocaleString('en-IN')} Cr
      </div>
    </div>
  );
}
