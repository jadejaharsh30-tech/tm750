/* Factor index membership, overlap, and whether members still qualify.

   Index constituents are fixed until the next rebalance, so a momentum-index
   member can sit below its moving averages for months. That gap between
   membership and current condition is the rebalance lag, and it is
   measurable rather than theoretical. */
import { Loading, RankBar, TierChip } from '../../components/ui';
import { pctSigned } from '../../lib/format';

export default function Factors({ factors }) {
  if (!factors) return <Loading label="Loading factors" />;
  const rows = factors.factors ?? [];
  const maxOverlap = Math.max(...(factors.overlaps ?? []).map((o) => o.overlap), 1);

  return (
    <>
      <section className="card pad">
        <div className="eyebrow">Do factor-index members still qualify?</div>
        <p className="muted tight">
          Constituents are fixed until the next rebalance. The gap between
          membership and current trend condition is rebalance lag.
        </p>
        <div className="grouplist">
          <div className="grouprow fac-row grouprow-head eyebrow">
            <span>Index</span><span className="num">n</span>
            <span>Full EMA stack</span><span className="num">&gt;EMA200</span>
            <span className="num">Median 1Y</span><span className="num">P/E</span>
          </div>
          {rows.map((r) => (
            <div className="grouprow fac-row" key={r.factor}>
              <span className="cap">{r.factor.replace(/_/g, ' ')}</span>
              <span className="num subtle">{r.n}</span>
              <span className="groupbar">
                <RankBar value={r.pct_stacked} width={58} />
                <span className="num">{r.pct_stacked}%</span>
              </span>
              <span className="num subtle">{r.pct_above_ema200}%</span>
              <span className={`num ${r.median_1y >= 0 ? 'up' : 'down'}`}>
                {pctSigned(r.median_1y)}
              </span>
              <span className="num subtle">{r.median_pe}</span>
            </div>
          ))}
        </div>
      </section>

      <div className="grid-2">
        <section className="card pad">
          <div className="eyebrow">Index overlap</div>
          <p className="muted tight">
            Two factor sleeves that share half their names are not the
            independent bets they appear to be.
          </p>
          <div className="ranges">
            {(factors.overlaps ?? []).map((o) => (
              <div className="overlap-row" key={`${o.a}-${o.b}`}>
                <span className="overlap-pair ellipsis">
                  <span className="cap">{o.a.replace(/_/g, ' ')}</span>
                  <span className="subtle"> ∩ </span>
                  <span className="cap">{o.b.replace(/_/g, ' ')}</span>
                </span>
                <span className="minibar">
                  <span className="minibar-fill"
                        style={{ width: `${(100 * o.overlap) / maxOverlap}%` }} />
                </span>
                <span className="num">{o.overlap}</span>
                <span className="num subtle">{o.pct_of_a}%</span>
              </div>
            ))}
          </div>
        </section>

        <section className="card pad">
          <div className="eyebrow">Factor membership by tier</div>
          <p className="muted tight">
            Micro caps carry no momentum-index membership at all — the indices
            are not built from that end of the universe.
          </p>
          <table className="mini">
            <thead>
              <tr>
                <th>Tier</th><th className="num">Momentum</th>
                <th className="num">Quality</th><th className="num">Value</th>
                <th className="num">Low vol</th>
              </tr>
            </thead>
            <tbody>
              {(factors.by_tier ?? []).map((t) => (
                <tr key={t.tier}>
                  <td><TierChip tier={t.tier} /></td>
                  <td className="num">{t.momentum}</td>
                  <td className="num">{t.quality}</td>
                  <td className="num">{t.value}</td>
                  <td className="num">{t.low_vol}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </>
  );
}
