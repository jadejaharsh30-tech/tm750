/* Price breadth: how much of the universe is actually participating. */
import { Histogram, BarRow } from './shared';
import { Loading, RankBar } from '../../components/ui';
import { pctSigned } from '../../lib/format';

export default function Breadth({ pulse, breadth, by, setBy }) {
  const b = pulse.breadth ?? {};
  const h = pulse.headline ?? {};
  const adv = h.advancing ?? 0;
  const dec = h.declining ?? 0;
  const advPct = (adv + dec) > 0 ? (100 * adv) / (adv + dec) : 50;
  const hl = breadth?.high_low ?? {};
  const dist = breadth?.distance_from_52w_high;

  return (
    <>
      <div className="grid-2">
        <section className="card pad">
          <div className="eyebrow">Participation</div>
          <p className="muted tight">
            An index level says nothing about how many companies carry it.
          </p>
          <div className="breadth">
            <BarRow label="Above EMA200" value={b.pct_above_ema200} />
            <BarRow label="Above SMA200" value={b.pct_above_sma200} />
            <BarRow label="Full EMA stack" value={b.pct_ema_stacked} />
            <BarRow label="Positive 1Y" value={b.pct_positive_1y} />
            <BarRow label="Within 10% of 52W high" value={b.pct_near_52w_high} />
          </div>
          <div className="advdec">
            <div className="advdec-bar">
              <span className="advdec-up" style={{ width: `${advPct}%` }} />
              <span className="advdec-down" style={{ width: `${100 - advPct}%` }} />
            </div>
            <div className="advdec-legend">
              <span className="up num">{adv} advancing</span>
              <span className="down num">{dec} declining</span>
            </div>
          </div>
        </section>

        <section className="card pad">
          <div className="eyebrow">Distance from 52-week high</div>
          <p className="muted tight">
            The shape behind the median. Where the 750 actually sit.
          </p>
          {dist ? (
            <Histogram total={h.companies} buckets={[
              { label: 'At high', n: dist.at_high, tone: 'up' },
              { label: 'Within 10%', n: dist.within_10, tone: 'up' },
              { label: '10–25% off', n: dist.down_10_25, tone: 'flat' },
              { label: '25–50% off', n: dist.down_25_50, tone: 'down' },
              { label: 'Over 50% off', n: dist.down_50, tone: 'down' },
            ]} />
          ) : <Loading label="Loading" />}

          <div className="hilo">
            <div className="hilo-cell">
              <span className="num hilo-n up">{hl.new_highs ?? '--'}</span>
              <span className="subtle">new highs</span>
            </div>
            <div className="hilo-vs subtle">vs</div>
            <div className="hilo-cell">
              <span className="num hilo-n down">{hl.new_lows ?? '--'}</span>
              <span className="subtle">new lows</span>
            </div>
            <p className="note hilo-note">
              More new lows than new highs is a narrowing market, whatever the
              index is doing. Median company sits at{' '}
              <strong className="num">{hl.median_range_position ?? '--'}%</strong>{' '}
              of its own 52-week range.
            </p>
          </div>
        </section>
      </div>

      <section className="card pad">
        <div className="card-head">
          <div>
            <div className="eyebrow">Breadth by {by}</div>
            <p className="muted tight">
              Strength concentrated in two sectors is a different market from
              strength spread across twenty.
            </p>
          </div>
          <div className="seg-toggle">
            {['sector', 'tier'].map((x) => (
              <button key={x} className={by === x ? 'active' : ''}
                      onClick={() => setBy(x)}>
                {x === 'sector' ? 'Sector' : 'Cap tier'}
              </button>
            ))}
          </div>
        </div>
        {breadth?.groups ? (
          <div className="grouplist tall">
            <div className="grouprow grouprow-head eyebrow">
              <span>Group</span><span className="num">n</span>
              <span>&gt;EMA200</span><span className="num">Profit ATH</span>
              <span className="num">1Y</span>
            </div>
            {breadth.groups.map((g) => (
              <div className="grouprow" key={g.group}>
                <span className="ellipsis" title={g.group}>{g.group}</span>
                <span className="num subtle">{g.n}</span>
                <span className="groupbar">
                  <RankBar value={g.pct_above_ema200} width={58} />
                  <span className="num">{g.pct_above_ema200}%</span>
                </span>
                <span className="num subtle">{g.pct_profit_ath}%</span>
                <span className={`num ${g.median_1y >= 0 ? 'up' : 'down'}`}>
                  {pctSigned(g.median_1y)}
                </span>
              </div>
            ))}
          </div>
        ) : <Loading label="Loading" />}
      </section>
    </>
  );
}
