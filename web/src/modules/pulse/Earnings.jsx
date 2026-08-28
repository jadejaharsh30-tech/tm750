/* Earnings breadth. TTM is the rolling-year truth: it updates every quarter,
   where reported annual PAT moves once a year and can describe a period
   closed up to four quarters ago. */
import { CountStat, Histogram } from './shared';
import { Loading, TierChip } from '../../components/ui';

export default function Earnings({ ath, total }) {
  if (!ath) return <Loading label="Loading earnings breadth" />;
  const c = ath.counts ?? {};

  return (
    <>
      <div className="athstats">
        <CountStat label="TTM PAT at ATH" n={c.ttm_at_ath} total={total} />
        <CountStat label="Latest quarter at ATH" n={c.q_at_ath} total={total} />
        <CountStat label="Both TTM + quarter" n={c.both_at_ath} total={total}
                   emphasis />
        <CountStat label="Annual PAT at ATH (ref)" n={c.fy_at_ath} total={total}
                   muted />
      </div>

      <div className="splitrow">
        <div className="splitcell">
          <span className="num splitcell-n up">{c.both_at_ath}</span>
          <span className="splitcell-label">
            <strong>Still setting records</strong>
            <span className="subtle">TTM and latest quarter both at a high</span>
          </span>
        </div>
        <div className="splitcell">
          <span className="num splitcell-n flat">{c.ttm_only}</span>
          <span className="splitcell-label">
            <strong>Record year, quarter fading</strong>
            <span className="subtle">TTM at a high, latest quarter is not</span>
          </span>
        </div>
        <div className="splitcell">
          <span className="num splitcell-n flat">{c.q_only}</span>
          <span className="splitcell-label">
            <strong>Strong quarter, year behind</strong>
            <span className="subtle">Quarter at a high, TTM not yet</span>
          </span>
        </div>
      </div>

      <div className="grid-2">
        <section className="card pad">
          <div className="eyebrow">TTM PAT, distance from its own peak</div>
          <p className="muted tight">
            An earnings drawdown, directly analogous to a price drawdown.
          </p>
          <Histogram total={total} buckets={[
            { label: 'At peak', n: c.ttm_at_ath, tone: 'up' },
            { label: 'Within 10%', n: c.ttm_within_10, tone: 'up' },
            { label: '10–25% below', n: c.ttm_10_25, tone: 'flat' },
            { label: '25–50% below', n: c.ttm_25_50, tone: 'down' },
            { label: 'Over 50% below', n: c.ttm_below_50, tone: 'down' },
          ]} />
        </section>

        <section className="card pad">
          <div className="eyebrow">By cap tier</div>
          <p className="muted tight">
            Where record earnings actually sit in the size spectrum.
          </p>
          <table className="mini">
            <thead>
              <tr>
                <th>Tier</th><th className="num">TTM ATH</th>
                <th className="num">Qtr ATH</th><th className="num">Both</th>
                <th className="num">Both %</th>
              </tr>
            </thead>
            <tbody>
              {(ath.by_tier ?? []).map((t) => (
                <tr key={t.tier}>
                  <td><TierChip tier={t.tier} /></td>
                  <td className="num">{t.ttm_at_ath}</td>
                  <td className="num">{t.q_at_ath}</td>
                  <td className="num strong">{t.both_at_ath}</td>
                  <td className="num">{t.both_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </>
  );
}
