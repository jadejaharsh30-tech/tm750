/* What moved between the two most recent snapshots.

   The question a single snapshot cannot answer at all, and the reason for
   holding history in the first place. */
import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { Empty, Loading, TierChip } from '../../components/ui';
import { useCatalog } from '../../lib/catalog';
import { formatValue } from '../../lib/format';
import { CompanyRow } from './shared';

const METRICS = [
  { name: 'price', label: 'Price' },
  { name: 'market_cap', label: 'Market cap' },
  { name: 'pe_ratio', label: 'P/E' },
  { name: 'perf_1y_pct', label: '1Y return' },
  { name: 'momentum_12_1_pct', label: '12-1 momentum' },
  { name: 'rsi_14', label: 'RSI 14' },
  { name: 'fii_holding', label: 'FII holding' },
];

export default function Changes({ snapshotCount }) {
  const catalog = useCatalog();
  const [metric, setMetric] = useState('price');
  const [data, setData] = useState(null);
  const [universe, setUniverse] = useState(null);

  useEffect(() => {
    if (snapshotCount < 2) return undefined;
    let cancelled = false;
    setData(null);
    api.changes(metric, 12)
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setData({ movers: [], summary: {} }));
    return () => { cancelled = true; };
  }, [metric, snapshotCount]);

  useEffect(() => {
    if (snapshotCount < 2) return undefined;
    let cancelled = false;
    api.universeChanges()
      .then((d) => !cancelled && setUniverse(d))
      .catch(() => {});
    return () => { cancelled = true; };
  }, [snapshotCount]);

  if (snapshotCount < 2) {
    return (
      <Empty title="Only one snapshot held"
             hint="Upload another day's export and this fills in — movers, entries and exits between any two dates." />
    );
  }
  if (!data) return <Loading label="Comparing snapshots" />;

  const s = data.summary ?? {};
  const spec = catalog.spec(metric);
  const up = data.movers.filter((m) => m.delta > 0).slice(0, 6);
  const down = data.movers.filter((m) => m.delta < 0).slice(0, 6);

  return (
    <>
      <div className="card-head">
        <div>
          <div className="eyebrow">
            {data.from} → {data.to}
          </div>
          <p className="muted tight">
            Joined on ISIN, not symbol — a ticker rename would otherwise look
            like one company leaving and another arriving.
          </p>
        </div>
        <select className="filter-op" value={metric}
                onChange={(e) => setMetric(e.target.value)}>
          {METRICS.map((m) => (
            <option key={m.name} value={m.name}>{m.label}</option>
          ))}
        </select>
      </div>

      <div className="splitrow">
        <div className="splitcell">
          <span className="num splitcell-n up">{s.up ?? '--'}</span>
          <span className="splitcell-label"><strong>Rose</strong></span>
        </div>
        <div className="splitcell">
          <span className="num splitcell-n down">{s.down ?? '--'}</span>
          <span className="splitcell-label"><strong>Fell</strong></span>
        </div>
        <div className="splitcell">
          <span className="num splitcell-n flat">{s.flat ?? '--'}</span>
          <span className="splitcell-label"><strong>Unchanged</strong></span>
        </div>
        <div className="splitcell">
          <span className="num splitcell-n">
            {s.median_delta ?? '--'}
          </span>
          <span className="splitcell-label">
            <strong>Median change</strong>
            <span className="subtle">{spec.label}</span>
          </span>
        </div>
      </div>

      {universe && !universe.stable && (
        <div className="banner compact">
          <strong>The universe changed.</strong>{' '}
          {universe.entered.length} entered, {universe.left.length} left,{' '}
          {universe.tier_moves.length} moved cap tier between these dates.
        </div>
      )}

      <div className="grid-2">
        <section className="card pad">
          <div className="eyebrow">Biggest increases</div>
          <div className="divlist">
            {up.map((m) => (
              <CompanyRow key={m.symbol} c={m} tone="up"
                          value={m.pct_change != null
                            ? `+${m.pct_change.toFixed(2)}%`
                            : formatValue(m.delta, spec)} />
            ))}
            {up.length === 0 && <span className="subtle">None</span>}
          </div>
        </section>
        <section className="card pad">
          <div className="eyebrow">Biggest decreases</div>
          <div className="divlist">
            {down.map((m) => (
              <CompanyRow key={m.symbol} c={m} tone="down"
                          value={m.pct_change != null
                            ? `${m.pct_change.toFixed(2)}%`
                            : formatValue(m.delta, spec)} />
            ))}
            {down.length === 0 && <span className="subtle">None</span>}
          </div>
        </section>
      </div>

      {universe && !universe.stable && (
        <div className="grid-2">
          {universe.entered.length > 0 && (
            <section className="card pad">
              <div className="eyebrow">Entered the universe</div>
              <div className="divlist">
                {universe.entered.slice(0, 8).map((e) => (
                  <div className="mover" key={e.symbol}>
                    <span className="mono mover-sym">{e.symbol}</span>
                    <span className="muted ellipsis">{e.name}</span>
                    <TierChip tier={e.cap_tier} />
                  </div>
                ))}
              </div>
            </section>
          )}
          {universe.left.length > 0 && (
            <section className="card pad">
              <div className="eyebrow">Left the universe</div>
              <div className="divlist">
                {universe.left.slice(0, 8).map((e) => (
                  <div className="mover" key={e.symbol}>
                    <span className="mono mover-sym">{e.symbol}</span>
                    <span className="muted ellipsis">{e.name}</span>
                    <TierChip tier={e.cap_tier} />
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </>
  );
}
