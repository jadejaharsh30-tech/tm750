/* App shell: navigation, theme, and the one piece of routing state.
   Modules not yet built render a placeholder rather than a broken tab, so the
   nav always tells the truth about what exists. */
import { useEffect, useMemo, useState } from 'react';
import { CatalogProvider, useCatalog } from './lib/catalog';
import { CompanySearch, ErrorState, Loading } from './components/ui';
import ErrorBoundary from './components/ErrorBoundary';
import SnapshotPicker from './components/SnapshotPicker';
import Pulse from './modules/Pulse';
import Grid from './modules/Grid';
import Company from './modules/Company';
import Screener from './modules/Screener';
import Compare from './modules/Compare';
import Explorer from './modules/Explorer';
import Quality from './modules/Quality';
import Segment from './modules/Segment';
import Upload from './modules/Upload';
import Scanner from './modules/Scanner';

const MODULES = [
  { id: 'pulse',    label: 'Pulse',     ready: true },
  { id: 'grid',     label: 'Grid',      ready: true },
  { id: 'company',  label: 'Company',   ready: true },
  { id: 'screener', label: 'Screener',  ready: true },
  { id: 'compare',  label: 'Compare',   ready: true },
  { id: 'explorer', label: 'Explorer',  ready: true },
  { id: 'segment',  label: 'Sectors',   ready: true },
  { id: 'quality',  label: 'Data quality', ready: true },
  { id: 'upload',   label: 'Upload',    ready: true },
  { id: 'scanner',  label: 'Scanner',   ready: true },
];

function useTheme() {
  const [theme, setTheme] = useState(
    () => localStorage.getItem('tm750-theme') ?? 'dark');
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('tm750-theme', theme);
  }, [theme]);
  return [theme, () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))];
}

function Shell() {
  const catalog = useCatalog();
  const [view, setView] = useState('pulse');
  const [symbol, setSymbol] = useState(null);
  const [theme, toggleTheme] = useTheme();

  // Opening Compare straight after viewing a company carries it across, so
  // you are not retyping a symbol you were just looking at.
  const compareSeed = useMemo(() => (symbol ? [symbol] : []), [symbol]);

  // Which sector / industry / tier the Segment page is showing. Held here so
  // a link from Explorer can set it before the page mounts.
  const [segment, setSegment] = useState({ dim: 'sector', value: null });

  function openSegment(dim, value) {
    setSegment({ dim, value });
    setView('segment');
  }

  function openCompany(sym) {
    setSymbol(sym);
    setView('company');
  }

  if (catalog.status === 'loading') {
    return <div className="boot"><Loading label="Connecting to API" /></div>;
  }
  if (catalog.status === 'error') {
    return (
      <div className="boot">
        <ErrorState error={catalog.error}
                    onRetry={() => window.location.reload()} />
      </div>
    );
  }

  return (
    <div className="app">
      <nav className="nav">
        <div className="brand">
          <span className="brand-mark mono">tm</span>
          <span className="brand-text">
            <strong>750</strong>
            <span className="subtle">{catalog.snapshot}</span>
          </span>
          {catalog.snapshotCount > 1 && (
            <span className="snapcount"
                  title={`${catalog.snapshotCount} snapshots held`}>
              {catalog.snapshotCount}d
            </span>
          )}
        </div>

        <div className="nav-links">
          {MODULES.map((m) => (
            <button
              key={m.id}
              className={`nav-link ${view === m.id ? 'active' : ''} ${m.ready ? '' : 'pending'}`}
              onClick={() => setView(m.id)}
              title={m.ready ? m.label : `${m.label} — not built yet`}
            >
              {m.label}
              {!m.ready && <span className="dot" aria-hidden="true" />}
            </button>
          ))}
        </div>

        <div className="nav-right">
          <SnapshotPicker snapshots={catalog.snapshots ?? []} />
          <CompanySearch onPick={openCompany} />
          <button className="btn icon" onClick={toggleTheme}
                  title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
                  aria-label="Toggle theme">
            {theme === 'dark' ? '☀' : '☾'}
          </button>
        </div>
      </nav>

      <main className="main">
        {/* Keyed so a crash in one module clears when you move to another,
            instead of following you around the app. */}
        <ErrorBoundary key={`${view}:${symbol ?? ''}`}
                       where={MODULES.find((m) => m.id === view)?.label}>
          {view === 'pulse'   && <Pulse onOpenCompany={openCompany} />}
          {view === 'grid'    && <Grid onOpenCompany={openCompany} />}
          {view === 'company' && <Company symbol={symbol} />}
          {view === 'screener' && <Screener onOpenCompany={openCompany} />}
          {view === 'compare' && (
            <Compare initialSymbols={compareSeed} onOpenCompany={openCompany} />
          )}
          {view === 'explorer' && <Explorer onOpenSegment={openSegment} />}
          {view === 'segment' && (
            <Segment dim={segment.dim} value={segment.value}
                     onOpenCompany={openCompany}
                     onChangeSelection={(d, v) => setSegment({ dim: d, value: v })} />
          )}
          {view === 'upload' && (
            <Upload onCommitted={() => window.location.reload()} />
          )}
          {view === 'quality' && <Quality />}
          {view === 'scanner' && <Scanner />}
        </ErrorBoundary>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <CatalogProvider>
      <Shell />
    </CatalogProvider>
  );
}
