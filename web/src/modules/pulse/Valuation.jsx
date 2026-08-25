/* Valuation spread. A median P/E says the market is expensive; quartiles say
   whether that is the whole universe or a long right tail. */
import { RangeBar } from './shared';
import { Loading, TierChip } from '../../components/ui';

export default function Valuation({ valuation }) {
  if (!valuation) return <Loading label="Loading valuation" />;
  const tiers = valuation.by_tier ?? [];
  const sectors = valuation.by_sector ?? [];
  const scaleMax = Math.max(...tiers.map((t) => t.p90 ?? 0), 100);
  const secMax = Math.max(...sectors.map((s) => s.pe ?? 0), 10);

  return (
    <div className="grid-2">
      <section className="card pad">
        <div className="eyebrow">P/E spread by cap tier</div>
        <p className="muted tight">
          Bar spans the middle 50%. The line marks the median, the tick marks
          the 90th percentile.
        </p>
        <div className="ranges">
          {tiers.map((t) => (
            <div className="range-row" key={t.tier}>
              <span className="range-label"><TierChip tier={t.tier} /></span>
              <RangeBar p25={t.p25} p50={t.p50} p75={t.p75} p90={t.p90}
                        scaleMax={scaleMax} />
              <span className="num range-med">{t.p50}</span>
            </div>
          ))}
        </div>
        <table className="mini" style={{ marginTop: 'var(--sp-3)' }}>
          <thead>
            <tr>
              <th>Tier</th><th className="num">P25</th><th className="num">Med</th>
              <th className="num">P75</th><th className="num">PEG</th>
              <th className="num">Earn yield</th>
            </tr>
          </thead>
          <tbody>
            {tiers.map((t) => (
              <tr key={t.tier}>
                <td><TierChip tier={t.tier} /></td>
                <td className="num">{t.p25}</td>
                <td className="num strong">{t.p50}</td>
                <td className="num">{t.p75}</td>
                <td className="num">{t.peg}</td>
                <td className="num">{t.earnings_yield}%</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="note">
          PEG falls as size falls while P/E stays flat — the smaller tiers are
          not cheaper, they are growing faster for the same price.
        </p>
      </section>

      <section className="card pad">
        <div className="eyebrow">Sector valuation ladder</div>
        <p className="muted tight">
          Median P/E, cheapest first. The right column is each sector against
          its own five-year history — a different question from cross-sector
          comparison.
        </p>
        <div className="grouplist tall">
          <div className="grouprow val-row grouprow-head eyebrow">
            <span>Sector</span><span className="num">n</span>
            <span>Median P/E</span><span className="num">P/B</span>
            <span className="num">vs own 5Y</span>
          </div>
          {sectors.map((s) => (
            <div className="grouprow val-row" key={s.sector}>
              <span className="ellipsis" title={s.sector}>{s.sector}</span>
              <span className="num subtle">{s.n}</span>
              <span className="groupbar">
                <span className="minibar">
                  <span className="minibar-fill"
                        style={{ width: `${(100 * s.pe) / secMax}%` }} />
                </span>
                <span className="num">{s.pe}</span>
              </span>
              <span className="num subtle">{s.pb}</span>
              <span className={`num ${s.vs_own_5y >= 0 ? 'down' : 'up'}`}>
                {s.vs_own_5y > 0 ? '+' : ''}{s.vs_own_5y}%
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
