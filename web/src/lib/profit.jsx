/* Profit feed state, held once for the whole app.

   Profit used to arrive by two unrelated routes -- uploaded workbooks for the
   platform, an API fetch for the scanner -- which meant "when was profit last
   refreshed" had two answers that could disagree. There is now one fetch, so
   there is one piece of state describing it, and every screen that shows
   freshness reads from here rather than asking separately.

   The fetch is slow by nature (two Apps Script calls, 5,500+ companies each,
   roughly a minute). It is held in context so navigating away from whichever
   page you started it on does not abandon it. */
import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from 'react';
import { api } from '../api/client';

const ProfitContext = createContext(null);

export function ProfitProvider({ children }) {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [lastResult, setLastResult] = useState(null);

  const refresh = useCallback(() => {
    api.profitStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const fetchNow = useCallback(async () => {
    if (busy) return null;
    setBusy(true);
    setError(null);
    try {
      const out = await api.profitFetch();
      setLastResult(out);
      refresh();
      return out;
    } catch (err) {
      setError(err);
      // Nothing was written on the server side either -- the fetch is
      // all-or-nothing -- so the previous status is still accurate.
      throw err;
    } finally {
      setBusy(false);
    }
  }, [busy, refresh]);

  const value = useMemo(() => ({
    status, busy, error, lastResult, fetchNow, refresh,
    // Stale means "not fetched today". The sheets are maintained daily at
    // source, so yesterday's fetch is older data, not merely an older click.
    stale: status ? status.stale !== false : true,
    everFetched: Boolean(status?.fetched_at),
  }), [status, busy, error, lastResult, fetchNow, refresh]);

  return (
    <ProfitContext.Provider value={value}>{children}</ProfitContext.Provider>
  );
}

export function useProfitFeed() {
  const ctx = useContext(ProfitContext);
  if (!ctx) {
    throw new Error('useProfitFeed must be used inside <ProfitProvider>');
  }
  return ctx;
}

/** "2026-08-31 15:52" from an ISO stamp, or null. */
export function stampText(iso) {
  if (!iso) return null;
  return String(iso).replace('T', ' ').slice(0, 16);
}
