/* Market Pulse.

   Six tabs rather than one long scroll. Each panel fetches only when its tab
   is first opened, so landing on the page costs two requests, not seven, and
   a panel you never look at costs nothing. */
import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { ErrorState, Loading, Stat } from '../components/ui';
import { useCatalog } from '../lib/catalog';
import { groupIndian, pctSigned } from '../lib/format';
import Breadth from './pulse/Breadth';
import Changes from './pulse/Changes';
import Divergence from './pulse/Divergence';
import Earnings from './pulse/Earnings';
import Factors from './pulse/Factors';
import Flows from './pulse/Flows';
import Valuation from './pulse/Valuation';

const TABS = [
  { id: 'breadth',    label: 'Breadth' },
  { id: 'changes',    label: 'What changed' },
  { id: 'earnings',   label: 'Earnings' },
  { id: 'divergence', label: 'Divergence' },
  { id: 'valuation',  label: 'Valuation' },
  { id: 'flows',      label: 'Ownership' },
  { id: 'factors',    label: 'Factors' },
];

export default function Pulse({ onOpenCompany }) {
  const catalog = useCatalog();
  const [pulse, setPulse] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('breadth');
  const [by, setBy] = useState('sector');
  const [reloadKey, setReloadKey] = useState(0);

  // Panels are fetched on first open and then kept.
  const [panels, setPanels] = useState({});
  const set = useCallback(
    (k, v) => setPanels((p) => ({ ...p, [k]: v })), []);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api.pulse().then((d) => !cancelled && setPulse(d))
      .catch((e) => !cancelled && setError(e));
    return () => { cancelled = true; };
  }, [reloadKey]);

  useEffect(() => {
    let cancelled = false;
    api.breadth(by).then((b) => !cancelled && set('breadth', b))
      .catch(() => !cancelled && set('breadth', { groups: [] }));
    return () => { cancelled = true; };
  }, [by, reloadKey, set]);

  /* Lazy per-tab loading. The dependency list is the tab, so opening
     Valuation is what triggers the valuation request -- never before. */
  useEffect(() => {
    let cancelled = false;
    const need = {
      earnings:   ['ath', api.profitAth],
      divergence: ['drawdown', api.drawdown],
      valuation:  ['valuation', api.valuation],
      flows:      ['flows', api.flows],
      factors:    ['factors', api.factors],
    }[tab];

    // Divergence draws on the earnings payload too.
    if (tab === 'divergence' && !panels.ath) {
      api.profitAth().then((d) => !cancelled && set('ath', d)).catch(() => {});
    }
    if (!need) return;
    const [key, fetcher] = need;
    if (panels[key]) return;
    fetcher().then((d) => !cancelled && set(key, d)).catch(() => {});
    return () => { cancelled = true; };
  }, [tab, panels, set]);

  const retry = () => { setPanels({}); setReloadKey((k) => k + 1); };

  if (error) {
    return <div className="module"><ErrorState error={error} onRetry={retry} /></div>;
  }
  if (!pulse) {
    return <div className="module"><Loading label="Loading market pulse" /></div>;
  }

  const h = pulse.headline ?? {};
  const adv = h.advancing ?? 0;
  const dec = h.declining ?? 0;

  return (
    <div className="module">
      <header className="module-head">
        <div>
          <div className="eyebrow">Nifty Total Market · {pulse.snapshot}</div>
          <h1>Market pulse</h1>
        </div>
      </header>

      {/* Headline strip stays across every tab -- it is the constant. */}
      <section className="stat-row">
        <Stat label="Companies" value={groupIndian(h.companies)} />
        <Stat label="Total market cap" value={`₹${h.total_mcap_lakh_cr} L Cr`} />
        <Stat label="Median P/E" value={h.median_pe} />
        <Stat label="Median 1Y return" value={pctSigned(h.median_1y_return)}
              tone={h.median_1y_return >= 0 ? 'up' : 'down'} />
        <Stat label="Median from ATH" value={`${h.median_from_ath}%`} tone="down" />
        <Stat label="Advance / decline" value={`${adv} / ${dec}`}
              tone={adv > dec ? 'up' : 'down'} />
      </section>

      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={`tab ${tab === t.id ? 'active' : ''}`}
                  onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      {tab === 'breadth' && (
        <Breadth pulse={pulse} breadth={panels.breadth} by={by} setBy={setBy} />
      )}
      {tab === 'changes' && (
        <Changes snapshotCount={catalog.snapshotCount ?? 1} />
      )}
      {tab === 'earnings' && (
        <Earnings ath={panels.ath} total={h.companies} />
      )}
      {tab === 'divergence' && (
        <Divergence drawdown={panels.drawdown} ath={panels.ath}
                    onOpenCompany={onOpenCompany} />
      )}
      {tab === 'valuation' && <Valuation valuation={panels.valuation} />}
      {tab === 'flows' && (
        <Flows flows={panels.flows} onOpenCompany={onOpenCompany} />
      )}
      {tab === 'factors' && <Factors factors={panels.factors} />}
    </div>
  );
}
