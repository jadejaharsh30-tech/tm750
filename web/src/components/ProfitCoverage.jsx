/* Which universe members the profit feed does not cover.

   The feed carries 5,500+ companies; the platform universe and the scanner's
   scan list are each much smaller subsets of it. Companies in the feed but
   outside a universe are not a problem and are not reported -- there are
   thousands of them. The only thing worth surfacing is the reverse: a
   universe member the feed has no row for, which is exactly the unmapped-ISIN
   case that otherwise shows up as a silent "no data" verdict.

   Universe sizes are read from the server, never assumed. The platform
   universe is whatever the current snapshot holds and the scan list is
   whatever Excel was last uploaded; both change. */
import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useProfitFeed } from '../lib/profit';

export default function ProfitCoverage() {
  const { status, lastResult, everFetched } = useProfitFeed();
  const [cov, setCov] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api.profitCoverage()
      .then((d) => !cancelled && setCov(d))
      .catch((e) => !cancelled && setError(e));
    return () => { cancelled = true; };
    // Refetch after a new fetch completes, so the panel is never one behind.
  }, [status?.fetched_at, lastResult]);

  if (!everFetched) {
    return (
      <section className="card pad">
        <div className="eyebrow">Profit feed coverage</div>
        <p className="muted tight">
          Profit data has never been fetched. Use the Profit button in the
          header — coverage is reported against each universe once a fetch has
          run.
        </p>
      </section>
    );
  }

  if (error) {
    return (
      <section className="card pad">
        <div className="eyebrow">Profit feed coverage</div>
        <p className="muted tight">{error.message}</p>
      </section>
    );
  }

  if (!cov) {
    return (
      <section className="card pad">
        <div className="eyebrow">Profit feed coverage</div>
        <p className="muted tight">Loading…</p>
      </section>
    );
  }

  const universes = Object.entries(cov.universes ?? {});

  return (
    <section className="card pad">
      <div className="eyebrow">
        Profit feed coverage ·{' '}
        <span className="num">
          {Number(cov.feed_companies ?? 0).toLocaleString('en-IN')}
        </span>{' '}
        companies in the feed
      </div>
      <p className="muted tight">
        Measured against each universe separately. Companies in the feed but
        outside a universe are expected and are not counted as a gap — only
        universe members the feed has no row for.
      </p>

      {universes.map(([key, u]) => (
        <div className="covblock" key={key}>
          <div className="covhead">
            <strong>{u.label ?? key}</strong>
            {u.error ? (
              <span className="subtle">unavailable — {u.error}</span>
            ) : (
              <span className="num subtle">
                {u.matched} of {u.size} matched
                {u.unmatched?.length > 0
                  && ` · ${u.unmatched.length} without profit data`}
              </span>
            )}
          </div>

          {!u.error && u.unmatched?.length === 0 && (
            <p className="muted tight">Every member is covered.</p>
          )}

          {!u.error && u.unmatched?.length > 0 && (
            <div className="covlist">
              {u.unmatched.map((c) => (
                <span className="covchip" key={c.symbol ?? c.isin}
                      title={c.isin ? `ISIN ${c.isin}` : 'No ISIN recorded'}>
                  <span className="mono">{c.symbol ?? '—'}</span>
                  {!c.isin && <span className="subtle"> no ISIN</span>}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </section>
  );
}
