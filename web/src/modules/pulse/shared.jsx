/* Presentational primitives shared across the pulse panels.
   Kept here so every panel renders bars, histograms and stat blocks the same
   way -- twelve panels drifting apart visually is what makes a dashboard
   feel assembled rather than designed. */
import { pctSigned } from '../../lib/format';

/* A horizontal distribution. Shows shape, which a median cannot. */
export function Histogram({ buckets, total }) {
  const max = Math.max(...buckets.map((b) => b.n ?? 0), 1);
  return (
    <div className="hist">
      {buckets.map((b) => (
        <div className="hist-row" key={b.label}>
          <span className="hist-label">{b.label}</span>
          <span className="hist-track">
            <span className={`hist-fill ${b.tone}`}
                  style={{ width: `${(100 * (b.n ?? 0)) / max}%` }} />
          </span>
          <span className="num hist-n">{b.n ?? '--'}</span>
          <span className="num hist-pct subtle">
            {b.n != null && total ? `${((100 * b.n) / total).toFixed(0)}%` : ''}
          </span>
        </div>
      ))}
    </div>
  );
}

/* Label, bar, value. The workhorse row of the whole page. */
export function BarRow({ label, value, max = 100, suffix = '%', tone }) {
  const w = value == null ? 0 : Math.min(100, (100 * Math.abs(value)) / max);
  return (
    <div className="breadth-row">
      <span className="breadth-label ellipsis" title={label}>{label}</span>
      <span className="breadth-track">
        <span className={`breadth-fill ${tone ?? ''}`} style={{ width: `${w}%` }} />
      </span>
      <span className="num breadth-val">
        {value == null ? '--' : `${value}${suffix}`}
      </span>
    </div>
  );
}

/* A count with its share of the universe underneath. */
export function CountStat({ label, n, total, tone, emphasis, muted }) {
  const pct = n != null && total ? (100 * n) / total : null;
  return (
    <div className={`athstat ${emphasis ? 'emphasis' : ''} ${muted ? 'ref' : ''}`}>
      <span className="eyebrow small">{label}</span>
      <span className={`athstat-n num ${tone ?? ''}`}>{n ?? '--'}</span>
      <span className="athstat-bar">
        <span className="athstat-fill" style={{ width: `${pct ?? 0}%` }} />
      </span>
      <span className="subtle num">
        {pct != null ? `${pct.toFixed(0)}%` : '--'}
      </span>
    </div>
  );
}

/* A quartile range drawn as a span, with the median marked. Communicates
   spread, where a single median communicates only level. */
export function RangeBar({ p25, p50, p75, p90, scaleMax }) {
  const pos = (v) => `${Math.min(100, (100 * v) / scaleMax)}%`;
  return (
    <span className="rangebar">
      <span className="rangebar-track" />
      <span className="rangebar-iqr"
            style={{ left: pos(p25), width: `calc(${pos(p75)} - ${pos(p25)})` }} />
      <span className="rangebar-med" style={{ left: pos(p50) }} />
      {p90 != null && <span className="rangebar-p90" style={{ left: pos(p90) }} />}
    </span>
  );
}

export function CompanyRow({ c, value, onOpen, tone }) {
  return (
    <button className="mover" onClick={() => onOpen?.(c.symbol)}>
      <span className="mono mover-sym">{c.symbol}</span>
      <span className="muted ellipsis">{c.name}</span>
      <span className={`num ${tone ?? ''}`}>{value}</span>
    </button>
  );
}

export function signed(n, d = 1) {
  return n == null ? '--' : pctSigned(n, d);
}
