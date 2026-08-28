/* Institutional ownership by tier, and how it has moved over three years. */
import { CompanyRow } from './shared';
import { Loading, TierChip } from '../../components/ui';

export default function Flows({ flows, onOpenCompany }) {
  if (!flows) return <Loading label="Loading ownership" />;
  const tiers = flows.by_tier ?? [];
  const max = Math.max(...tiers.flatMap((t) => [t.fii ?? 0, t.dii ?? 0]), 1);

  return (
    <>
      <section className="card pad">
        <div className="eyebrow">Institutional ownership by tier</div>
        <p className="muted tight">
          Foreign holding falls monotonically with size — the cleanest gradient
          in the dataset. Domestic institutions do not follow the same slope.
        </p>
        <div className="flowgrid">
          <div className="flowhead eyebrow">
            <span>Tier</span><span>FII</span><span>DII</span>
            <span className="num">Promoter</span>
          </div>
          {tiers.map((t) => (
            <div className="flowrow" key={t.tier}>
              <span><TierChip tier={t.tier} /></span>
              <span className="flowbar">
                <span className="minibar">
                  <span className="minibar-fill fii"
                        style={{ width: `${(100 * t.fii) / max}%` }} />
                </span>
                <span className="num">{t.fii}%</span>
                <span className={`num chg ${t.fii_chg_3y >= 0 ? 'up' : 'down'}`}>
                  {t.fii_chg_3y > 0 ? '+' : ''}{t.fii_chg_3y}
                </span>
              </span>
              <span className="flowbar">
                <span className="minibar">
                  <span className="minibar-fill dii"
                        style={{ width: `${(100 * t.dii) / max}%` }} />
                </span>
                <span className="num">{t.dii}%</span>
                <span className={`num chg ${t.dii_chg_3y >= 0 ? 'up' : 'down'}`}>
                  {t.dii_chg_3y > 0 ? '+' : ''}{t.dii_chg_3y}
                </span>
              </span>
              <span className="num subtle">{t.promoter}%</span>
            </div>
          ))}
        </div>
        <p className="note">
          Small numbers on the right are the three-year change in percentage
          points. Foreign money has been trimming large caps while domestic
          institutions added across every tier.
        </p>
      </section>

      <div className="grid-2">
        <section className="card pad">
          <div className="eyebrow">FII added most · 3 years</div>
          <div className="divlist">
            {(flows.fii_added ?? []).map((c) => (
              <CompanyRow key={c.symbol} c={c} tone="up"
                          value={`+${c.chg_fii_holding_3y?.toFixed(1)}`}
                          onOpen={onOpenCompany} />
            ))}
          </div>
        </section>
        <section className="card pad">
          <div className="eyebrow">FII cut most · 3 years</div>
          <div className="divlist">
            {(flows.fii_cut ?? []).map((c) => (
              <CompanyRow key={c.symbol} c={c} tone="down"
                          value={c.chg_fii_holding_3y?.toFixed(1)}
                          onOpen={onOpenCompany} />
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
