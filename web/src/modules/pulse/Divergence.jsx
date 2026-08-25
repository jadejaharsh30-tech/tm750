/* Earnings drawdown against price drawdown. Both axes are a distance from an
   all-time high -- one in profit, one in price. The interesting companies are
   the ones far from the diagonal. */
import {
  CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart,
  Tooltip, XAxis, YAxis, ZAxis,
} from 'recharts';
import { CompanyRow, signed } from './shared';
import { Loading } from '../../components/ui';

const TIER_COLOR = {
  Large: 'var(--tier-large)', Mid: 'var(--tier-mid)',
  Small: 'var(--tier-small)', Micro: 'var(--tier-micro)',
};

export default function Divergence({ drawdown, ath, onOpenCompany }) {
  if (!drawdown || !ath) return <Loading label="Loading divergence" />;
  const q = drawdown.quadrants ?? {};

  const byTier = ['Large', 'Mid', 'Small', 'Micro'].map((t) => ({
    tier: t,
    data: (drawdown.points ?? []).filter((p) => p.cap_tier === t),
  }));

  return (
    <>
      <div className="quadstats">
        <QuadCell n={q.earnings_high_price_low} tone="up"
                  title="Earnings high, price low"
                  hint="Within 10% of peak profit, over 20% off the price high" />
        <QuadCell n={q.both_near_high} tone=""
                  title="Both near highs"
                  hint="Earnings and price agree, at the top" />
        <QuadCell n={q.both_low} tone=""
                  title="Both well off"
                  hint="Earnings and price agree, at the bottom" />
        <QuadCell n={q.price_high_earnings_low} tone="down"
                  title="Price high, earnings low"
                  hint="Price holding up while profit is 10%+ off its peak" />
      </div>

      <section className="card pad">
        <div className="eyebrow">Earnings drawdown vs price drawdown</div>
        <p className="muted tight">
          Each point is a company: TTM profit below its peak on the horizontal,
          price below its all-time high on the vertical. Points below the
          diagonal have held earnings better than price.
        </p>
        <ResponsiveContainer width="100%" height={330}>
          <ScatterChart margin={{ top: 10, right: 16, bottom: 24, left: 4 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="2 3" />
            <XAxis type="number" dataKey="earnings" name="Earnings from peak"
                   domain={[-100, 5]} unit="%"
                   tick={{ fontSize: 10, fill: 'var(--fg-subtle)' }}
                   axisLine={false} tickLine={false}
                   label={{ value: 'TTM profit vs peak %', position: 'bottom',
                            offset: 4, fontSize: 10,
                            fill: 'var(--fg-subtle)' }} />
            <YAxis type="number" dataKey="price" name="Price from ATH"
                   domain={[-100, 5]} unit="%"
                   tick={{ fontSize: 10, fill: 'var(--fg-subtle)' }}
                   axisLine={false} tickLine={false} width={44}
                   label={{ value: 'Price vs ATH %', angle: -90,
                            position: 'insideLeft', fontSize: 10,
                            fill: 'var(--fg-subtle)' }} />
            <ZAxis range={[9, 9]} />
            <ReferenceLine segment={[{ x: -100, y: -100 }, { x: 5, y: 5 }]}
                           stroke="var(--fg-subtle)" strokeDasharray="3 3" />
            <Tooltip content={<PointTip />} cursor={{ strokeDasharray: '2 2' }} />
            {byTier.map((t) => (
              <Scatter key={t.tier} name={t.tier} data={t.data}
                       fill={TIER_COLOR[t.tier]} fillOpacity={0.62} />
            ))}
          </ScatterChart>
        </ResponsiveContainer>
        <div className="legend">
          {byTier.map((t) => (
            <span className="legend-item" key={t.tier}>
              <span className="legend-dot"
                    style={{ background: TIER_COLOR[t.tier] }} />
              {t.tier} · {t.data.length}
            </span>
          ))}
        </div>
      </section>

      <div className="grid-2">
        <section className="card pad">
          <div className="eyebrow">
            Record earnings, falling price · {ath.divergent_n}
          </div>
          <p className="muted tight">
            TTM and latest quarter both at a record, yet down over 12 months.
          </p>
          <div className="divlist">
            {(ath.divergent ?? []).map((d) => (
              <CompanyRow key={d.symbol} c={d} tone="down"
                          value={signed(d.perf_1y_pct)}
                          onOpen={onOpenCompany} />
            ))}
          </div>
        </section>

        <section className="card pad">
          <div className="eyebrow">Record year, quarter rolling over</div>
          <p className="muted tight">
            TTM still at a high, but the latest quarter is off its own peak —
            the earliest visible sign a run of record earnings is fading.
          </p>
          <div className="divlist">
            {(ath.rolling_over ?? []).map((d) => (
              <CompanyRow key={d.symbol} c={d} tone="flat"
                          value={`${d.pat_q_vs_peak_pct?.toFixed(0)}%`}
                          onOpen={onOpenCompany} />
            ))}
          </div>
        </section>
      </div>
    </>
  );
}

function QuadCell({ n, title, hint, tone }) {
  return (
    <div className="quadcell">
      <span className={`num quadcell-n ${tone}`}>{n ?? '--'}</span>
      <span className="quadcell-title">{title}</span>
      <span className="subtle quadcell-hint">{hint}</span>
    </div>
  );
}

function PointTip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="tooltip">
      <div className="tooltip-label mono">{p.symbol} · {p.cap_tier}</div>
      <div className="num">Profit {p.earnings?.toFixed(1)}% from peak</div>
      <div className="num">Price {p.price?.toFixed(1)}% from ATH</div>
    </div>
  );
}
