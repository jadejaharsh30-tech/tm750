/* Where the price sits inside its own range.

   Two bars: the 52-week range and the all-time range. Each shows the band,
   the endpoints, and the current price as a marker. The shorter-window highs
   (1m / 3m / 6m) are drawn as ticks on the 52-week bar, because a price 2%
   off its 52-week high but 8% off its one-month high is a different setup
   from one sitting at both. */
import { formatValue } from '../lib/format';

const PRICE = { unit: 'inr', fmt: '0.2f' };

export default function RangeBars({ flat }) {
  const price = flat.price?.value;
  if (price == null) return null;

  const bars = [
    {
      label: '52-week range',
      low: flat.low_52w?.value,
      high: flat.high_52w?.value,
      pos: flat.pct_of_52w_range?.value,
      fromHigh: flat.dist_52w_high_pct?.value,
      fromLow: flat.above_52w_low_pct?.value,
      ticks: [
        { label: '1M high', v: flat.high_1m?.value },
        { label: '3M high', v: flat.high_3m?.value },
        { label: '6M high', v: flat.high_6m?.value },
      ].filter((t) => t.v != null),
    },
    {
      label: 'All-time range',
      low: flat.low_all_time?.value,
      high: flat.high_all_time?.value,
      pos: null,
      fromHigh: flat.dist_ath_pct?.value,
      fromLow: flat.above_atl_pct?.value,
      ticks: [],
    },
  ].filter((b) => b.low != null && b.high != null && b.high > b.low);

  if (!bars.length) return null;

  return (
    <section className="card pad">
      <div className="eyebrow">Price range</div>
      <p className="muted tight">
        Where {formatValue(price, PRICE)} sits between the low and the high.
      </p>

      <div className="rangebars">
        {bars.map((b) => {
          const span = b.high - b.low;
          const at = (v) =>
            `${Math.max(0, Math.min(100, (100 * (v - b.low)) / span))}%`;
          // Prefer the precomputed range position; fall back to the geometry.
          const pct = b.pos ?? (100 * (price - b.low)) / span;

          return (
            <div className="rb" key={b.label}>
              <div className="rb-head">
                <span className="eyebrow small">{b.label}</span>
                <span className="subtle num">
                  {pct != null ? `${pct.toFixed(0)}% of range` : ''}
                </span>
              </div>

              <div className="rb-ends">
                <span className="rb-end">
                  <span className="subtle">Low</span>
                  <span className="num rb-val">{formatValue(b.low, PRICE)}</span>
                  {b.fromLow != null && (
                    <span className="num up rb-delta">
                      +{b.fromLow.toFixed(1)}%
                    </span>
                  )}
                </span>
                <span className="rb-end right">
                  <span className="subtle">High</span>
                  <span className="num rb-val">{formatValue(b.high, PRICE)}</span>
                  {b.fromHigh != null && (
                    <span className="num down rb-delta">
                      {b.fromHigh.toFixed(1)}%
                    </span>
                  )}
                </span>
              </div>

              <div className="rb-track">
                {/* Gradient track (red->green, CSS) shows position by
                    color; the marker below pins exactly where price sits. */}
                {b.ticks.map((t) => (
                  <span key={t.label} className="rb-tick"
                        style={{ left: at(t.v) }}
                        title={`${t.label} ${formatValue(t.v, PRICE)}`} />
                ))}
                <span className="rb-marker" style={{ left: `${pct}%` }}
                      title={`Current ${formatValue(price, PRICE)}`} />
              </div>

              {b.ticks.length > 0 && (
                <div className="rb-legend subtle">
                  {b.ticks.map((t) => (
                    <span key={t.label}>
                      {t.label} {formatValue(t.v, PRICE)}
                    </span>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
