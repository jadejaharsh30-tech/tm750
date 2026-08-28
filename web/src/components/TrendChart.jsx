/* One company's metrics across every snapshot held.

   Only rendered with two or more snapshots -- a single point is not a trend,
   and drawing one implies history that does not exist. */
import { useEffect, useMemo, useState } from 'react';
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../api/client';
import { useCatalog } from '../lib/catalog';
import { formatValue } from '../lib/format';
import { Empty, Loading } from './ui';

const METRICS = [
  { name: 'price', label: 'Price' },
  { name: 'market_cap', label: 'Market cap' },
  { name: 'pe_ratio', label: 'P/E' },
  { name: 'perf_1y_pct', label: '1Y return' },
  { name: 'momentum_12_1_pct', label: '12-1 momentum' },
  { name: 'rsi_14', label: 'RSI 14' },
  { name: 'dist_52w_high_pct', label: 'From 52W high' },
  { name: 'roe', label: 'ROE' },
  { name: 'fii_holding', label: 'FII holding' },
];

export default function TrendChart({ symbol, snapshotCount }) {
  const catalog = useCatalog();
  const [metric, setMetric] = useState('price');
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!symbol || snapshotCount < 2) return undefined;
    let cancelled = false;
    setData(null);
    api.companySeries(symbol, METRICS.map((m) => m.name))
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setData({ series: [] }));
    return () => { cancelled = true; };
  }, [symbol, snapshotCount]);

  const spec = catalog.spec(metric);

  const series = useMemo(
    () => (data?.series ?? []).map((r) => ({
      date: r.snapshot_date, value: r[metric],
    })), [data, metric]);

  if (snapshotCount < 2) return null;

  const first = series[0]?.value;
  const last = series[series.length - 1]?.value;
  const change = (first != null && last != null && first !== 0)
    ? ((last / Math.abs(first)) - 1) * 100 : null;

  return (
    <section className="card pad">
      <div className="card-head">
        <div className="eyebrow">Across {snapshotCount} snapshots</div>
        <select className="filter-op" value={metric}
                onChange={(e) => setMetric(e.target.value)}>
          {METRICS.map((m) => (
            <option key={m.name} value={m.name}>{m.label}</option>
          ))}
        </select>
      </div>

      {!data ? <Loading label="Loading series" />
        : series.length < 2 ? (
          <Empty title="Not enough history"
                 hint="This company appears in only one snapshot." />
        ) : (
          <>
            <div className="trendhead">
              <span className="num trendhead-v">
                {formatValue(last, spec)}
              </span>
              {change != null && (
                <span className={`num ${change >= 0 ? 'up' : 'down'}`}>
                  {change > 0 ? '+' : ''}{change.toFixed(2)}% since{' '}
                  {series[0].date}
                </span>
              )}
            </div>
            <ResponsiveContainer width="100%" height={170}>
              <LineChart data={series}
                         margin={{ top: 6, right: 10, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="2 3"
                               vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--fg-subtle)' }}
                       axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10, fill: 'var(--fg-subtle)' }}
                       axisLine={false} tickLine={false} width={58}
                       domain={['auto', 'auto']} />
                <Tooltip content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null;
                  return (
                    <div className="tooltip">
                      <div className="tooltip-label">{label}</div>
                      <div className="num">
                        {formatValue(payload[0].value, spec)}
                      </div>
                    </div>
                  );
                }} />
                <Line type="monotone" dataKey="value" strokeWidth={2}
                      stroke="var(--accent)" dot={{ r: 2.5 }}
                      activeDot={{ r: 4 }} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </>
        )}
    </section>
  );
}
