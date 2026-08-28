/* Loads the column catalog once and shares it. Every component that needs a
   column's label, unit, format or polarity reads it from here, so the frontend
   has no hardcoded knowledge of the 462 columns. */
import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';

const CatalogContext = createContext(null);

export function CatalogProvider({ children }) {
  const [state, setState] = useState({ status: 'loading', error: null });

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.catalog(), api.segments(), api.snapshots()])
      .then(([cat, seg, snaps]) => {
        if (cancelled) return;
        const byName = {};
        for (const c of cat.columns) byName[c.name] = c;
        setState({
          status: 'ready', columns: cat.columns, byName,
          segments: seg.segments, snapshot: snaps.latest,
          snapshots: snaps.snapshots ?? [],
          snapshotCount: (snaps.snapshots ?? []).length, error: null,
        });
      })
      .catch((err) => !cancelled && setState({ status: 'error', error: err }));
    return () => { cancelled = true; };
  }, []);

  const value = useMemo(() => ({
    ...state,
    spec: (name) => state.byName?.[name] ?? { name, label: name, fmt: '0.2f' },
    label: (name) => state.byName?.[name]?.label ?? name,
    describe: (name) => state.byName?.[name]?.description ?? '',
  }), [state]);

  return (
    <CatalogContext.Provider value={value}>{children}</CatalogContext.Provider>
  );
}

export function useCatalog() {
  const ctx = useContext(CatalogContext);
  if (!ctx) throw new Error('useCatalog must be used inside CatalogProvider');
  return ctx;
}
