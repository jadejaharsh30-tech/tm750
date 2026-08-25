/* Data quality.

   Every dataset has holes and compromises. Hiding them does not remove them,
   it just moves the surprise to whoever trusts a number they should not have.
   This page states what was dropped, what was reconstructed rather than
   reported, where two sources disagree, and which metrics are withheld for
   which companies. */
import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { ErrorState, Loading } from '../components/ui';

export default function Quality() {
  const [q, setQ] = useState(null);
  const [error, setError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api.quality().then((d) => !cancelled && setQ(d))
      .catch((e) => !cancelled && setError(e));
    return () => { cancelled = true; };
  }, [reloadKey]);

  if (error) {
    return (
      <div className="module">
        <ErrorState error={error} onRetry={() => setReloadKey((k) => k + 1)} />
      </div>
    );
  }
  if (!q) return <div className="module"><Loading label="Loading data quality" /></div>;

  const drops = q.drop_reasons ?? {};
  const mask = q.sector_masking ?? {};

  return (
    <div className="module">
      <header className="module-head">
        <div>
          <div className="eyebrow">What this dataset can and cannot tell you</div>
          <h1>Data quality</h1>
        </div>
      </header>

      <section className="stat-row">
        <QStat label="Companies" value={q.universe} />
        <QStat label="Columns retained" value={q.columns_retained} />
        <QStat label="Columns dropped" value={q.columns_dropped} />
        <QStat label="Fully populated" value={q.fully_populated_columns} />
        <QStat label="Below 50% coverage" value={q.columns_below_50pct} />
        <QStat label="Not screenable" value={q.non_screenable_columns} />
      </section>

      <div className="grid-2">
        {/* ------------------------------------------------ dropped */}
        <section className="card pad">
          <div className="eyebrow">Why {q.columns_dropped} columns were dropped</div>
          <p className="muted tight">
            Removed at build time. None of these carried information worth the
            column.
          </p>
          <div className="qlist">
            <QRow label="Currency columns" n={drops.currency}
                  why="Every value was INR. A column with one value everywhere carries no information." />
            <QRow label="Exact duplicates" n={drops.duplicate}
                  why="Byte-identical to another column already present." />
            <QRow label="Below coverage floor" n={drops.low_coverage}
                  why="Under 15% populated. Too sparse to rank, screen or aggregate honestly." />
          </div>
        </section>

        {/* ------------------------------------------- reconstruction */}
        <section className="card pad">
          <div className="eyebrow">Reconstructed, not reported</div>
          <p className="muted tight">
            These fields were computed from other columns because the source
            was too sparse to use. Error is measured against the rows where the
            reported value did exist.
          </p>
          <div className="qlist">
            {(q.reconstruction_checks ?? []).map((r) => (
              <div className="qrow" key={r.field}>
                <div className="qrow-head">
                  <span className="qrow-label ellipsis" title={r.field}>
                    {r.field}
                  </span>
                  <span className={`chip ${r.within_tolerance ? 'ok' : 'warn'}`}>
                    {r.within_tolerance ? 'validated' : 'check'}
                  </span>
                </div>
                <span className="qrow-why">
                  Median error <strong className="num">{r.median_abs_err_pct}%</strong>{' '}
                  against <span className="num">{r.n_overlap}</span> companies
                  that reported both.
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* -------------------------------------------- source conflicts */}
      <section className="card pad">
        <div className="eyebrow">Where the two sources disagree</div>
        <p className="muted tight">
          TradingView and Screener.in both publish these concepts. Where they
          diverge, both are kept rather than one being silently chosen — a
          divergence is usually a definitional difference, not an error.
        </p>
        <div className="qtable">
          <div className="qtrow qthead eyebrow">
            <span>Concept</span><span>TradingView</span><span>Screener</span>
            <span className="num">Overlap</span><span className="num">Corr</span>
            <span className="num">Median diff</span>
          </div>
          {(q.source_conflicts ?? []).map((c) => (
            <div className="qtrow" key={c.concept}>
              <span className="strong">{c.concept}</span>
              <span className="mono subtle ellipsis" title={c.tradingview_col}>
                {c.tradingview_col}
              </span>
              <span className="mono subtle ellipsis" title={c.screener_col}>
                {c.screener_col}
              </span>
              <span className="num subtle">{c.n_overlap}</span>
              <span className="num">{c.correlation}</span>
              <span className={`num ${c.median_abs_diff_pct > 5 ? 'down' : ''}`}>
                {c.median_abs_diff_pct}%
              </span>
            </div>
          ))}
        </div>
      </section>

      <div className="grid-2">
        {/* -------------------------------------------- history depth */}
        <section className="card pad">
          <div className="eyebrow">History depth</div>
          <p className="muted tight">
            Not every company has a full history. Long-window metrics are null
            rather than computed from a short series.
          </p>
          <div className="qlist">
            {(q.history_depth ?? []).map((h) => (
              <div className="qrow" key={h.series}>
                <div className="qrow-head">
                  <span className="qrow-label">{h.series}</span>
                  <span className="num subtle">
                    up to {h.max_periods} periods
                  </span>
                </div>
                <div className="depthbar">
                  <span className="depthbar-full"
                        style={{ width: `${(100 * h.full_history_n) / q.universe}%` }} />
                  <span className="depthbar-part"
                        style={{ width: `${(100 * (q.universe - h.full_history_n - h.under_half_n)) / q.universe}%` }} />
                  <span className="depthbar-thin"
                        style={{ width: `${(100 * h.under_half_n) / q.universe}%` }} />
                </div>
                <span className="qrow-why">
                  <strong className="num">{h.full_history_n}</strong> have the
                  full series · <span className="num">{h.under_half_n}</span>{' '}
                  have under half · median{' '}
                  <span className="num">{h.median_available}</span> periods
                </span>
              </div>
            ))}
          </div>
        </section>

        {/* ------------------------------------------ sector masking */}
        <section className="card pad">
          <div className="eyebrow">Sector masking</div>
          <p className="muted tight">{mask.rationale}</p>
          <div className="masksummary">
            <div>
              <span className="num masksummary-n">{mask.finance_companies}</span>
              <span className="subtle">
                financial companies · {mask.finance_pct_of_universe}% of the universe
              </span>
            </div>
            <div>
              <span className="num masksummary-n">{mask.masked_metrics}</span>
              <span className="subtle">metrics withheld for each of them</span>
            </div>
          </div>
          <div className="tags">
            {(mask.masked_list ?? []).map((m) => (
              <span className="tag mono" key={m}>{m}</span>
            ))}
          </div>
          <p className="note">
            Masking is applied at the API, not in this interface — so a
            notebook, a script or a future export cannot accidentally rank
            banks on inventory turnover either.
          </p>
        </section>
      </div>

      {/* ------------------------------------------- segment coverage */}
      <section className="card pad">
        <div className="eyebrow">Coverage by segment</div>
        <p className="muted tight">
          Median and worst-case population per segment. A low minimum means at
          least one column in that group is sparse — check the column tooltip
          in the grid before relying on it.
        </p>
        <div className="explist">
          {[...(q.segment_coverage ?? [])]
            .sort((a, b) => a.median_coverage - b.median_coverage)
            .map((s) => (
              <div className="exprow" key={s.segment}>
                <span className="exprow-label ellipsis">{s.segment}</span>
                <span className="num subtle exprow-n">{s.columns}</span>
                <span className="exprow-track">
                  <span className="exprow-fill"
                        style={{ width: `${s.median_coverage}%` }} />
                  <span className="cov-min"
                        style={{ left: `${s.min_coverage}%` }}
                        title={`worst column: ${s.min_coverage}%`} />
                </span>
                <span className="num exprow-val">{s.median_coverage}%</span>
              </div>
            ))}
        </div>
        <p className="note">
          Bar is the median column in that segment. The tick marks the worst.
        </p>
      </section>
    </div>
  );
}

function QStat({ label, value }) {
  return (
    <div className="stat">
      <div className="eyebrow">{label}</div>
      <div className="stat-value num">{value ?? '--'}</div>
    </div>
  );
}

function QRow({ label, n, why }) {
  if (n == null) return null;
  return (
    <div className="qrow">
      <div className="qrow-head">
        <span className="qrow-label">{label}</span>
        <span className="num strong">{n}</span>
      </div>
      <span className="qrow-why">{why}</span>
    </div>
  );
}
