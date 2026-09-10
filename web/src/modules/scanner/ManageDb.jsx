/* Trigger prices, editable, with their history.

   Every change to an ATH is logged -- seed, sync, split repair, manual edit --
   so the question "why is this symbol's trigger this number" always has an
   answer. The reference app overwrote the value in place with no record,
   which made a bad write permanent and invisible. */
import { Fragment, useCallback, useEffect, useState } from 'react';
import { scannerApi } from '../../api/scanner';
import { Empty, ErrorState, Loading } from '../../components/ui';

const SOURCE_LABEL = {
  seed: 'Seeded from history',
  sync: 'EOD sync',
  split: 'Split repair',
  manual: 'Manual edit',
  audit: 'Audit correction',
};

function num(v) {
  if (v === null || v === undefined) return '\u2014';
  return v.toLocaleString('en-IN', { minimumFractionDigits: 2,
                                     maximumFractionDigits: 2 });
}

function EventList({ symbol }) {
  const [rows, setRows] = useState(null);

  useEffect(() => {
    let cancelled = false;
    scannerApi.athEvents(symbol)
      .then((d) => !cancelled && setRows(d.rows))
      .catch(() => !cancelled && setRows([]));
    return () => { cancelled = true; };
  }, [symbol]);

  if (rows === null) return <Loading label="Loading history" />;
  if (!rows.length) return <p className="subtle tight">No recorded changes.</p>;

  return (
    <table className="mini dptable">
      <tbody>
        {rows.map((e, i) => (
          <tr key={i}>
            <td className="subtle">{e.date ?? '\u2014'}</td>
            <td>{SOURCE_LABEL[e.source] ?? e.source}</td>
            <td className="r num subtle">{num(e.old_price)}</td>
            <td className="r num">&rarr; {num(e.new_price)}</td>
            <td className="subtle">{e.note ?? ''}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function ManageDb() {
  const [q, setQ] = useState('');
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ price: '', date: '' });
  const [expanded, setExpanded] = useState(null);
  const [suspects, setSuspects] = useState(null);
  const [resetPhrase, setResetPhrase] = useState('');
  const [wipeEvents, setWipeEvents] = useState(false);
  const [resetting, setResetting] = useState(false);

  const load = useCallback((query) => {
    setError(null);
    scannerApi.athList(query)
      .then((d) => setRows(d.rows))
      .catch(setError);
  }, []);

  /* A lower bound on symbols affected by the repeated-halving bug -- two or
     more logged split repairs on the same symbol is the unambiguous signal.
     Checked once on load, not on every keystroke of the search box. */
  useEffect(() => {
    scannerApi.suspectedRepeatHalvings()
      .then((d) => setSuspects(d.rows))
      .catch(() => setSuspects([]));
  }, []);

  const [resetNote, setResetNote] = useState(null);

  const resetAth = async () => {
    setResetting(true); setError(null); setResetNote(null);
    try {
      const out = await scannerApi.resetAth(wipeEvents);
      setResetPhrase('');
      setSuspects([]);
      load(q);
      setResetNote(
        `Cleared ${out.ath_rows} ATH rows`
        + (wipeEvents ? ` and ${out.events_cleared} logged events` : '')
        + '. Go to the Scanner tab and press Run ATH scan to reseed the universe.');
    } catch (e) { setError(e); } finally { setResetting(false); }
  };

  /* Debounced so typing a prefix does not fire a request per keystroke. */
  useEffect(() => {
    const t = setTimeout(() => load(q), 250);
    return () => clearTimeout(t);
  }, [q, load]);

  const beginEdit = (row) => {
    setEditing(row.symbol);
    setForm({ price: row.ath_price ?? '', date: row.ath_date ?? '' });
  };

  const save = async (symbol) => {
    const price = Number(form.price);
    if (!Number.isFinite(price) || price <= 0) {
      setError(new Error('Enter a price above zero.'));
      return;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(form.date)) {
      setError(new Error('Enter the date as YYYY-MM-DD.'));
      return;
    }
    try {
      await scannerApi.editAth(symbol, price, form.date);
      setEditing(null);
      load(q);
    } catch (e) { setError(e); }
  };

  return (
    <div className="mdb">
      <div className="mdb-bar">
        <input className="mdb-search" value={q} placeholder="Search symbol"
               aria-label="Search symbol"
               onChange={(e) => setQ(e.target.value.toUpperCase())} />
        <span className="subtle num">
          {rows ? `${rows.length} shown` : ''}
        </span>
      </div>

      {error && <ErrorState error={error} onRetry={() => load(q)} />}

      {suspects?.length > 0 && (
        <div className="card pad warn-card">
          <span className="eyebrow">
            {suspects.length} symbol{suspects.length === 1 ? '' : 's'} show
            signs of being halved more than once
          </span>
          <p className="subtle tight">
            Repeated split-repair events on the same symbol -- a fixed bug
            (2026-08-27) could have applied a split adjustment more than
            once. This is a lower bound, not a complete list: a symbol
            caught only once before the fix looks identical to a normal
            repair here. A full reset below re-derives every trigger from
            scratch and is the only fully certain fix.
          </p>
          <p className="mono tight">
            {suspects.map((s) => `${s.symbol} (${s.split_events})`).join(', ')}
          </p>
        </div>
      )}

      {rows === null && <Loading label="Loading trigger prices" />}

      {rows?.length === 0 && (
        <Empty title="Nothing here yet"
               hint="Upload a universe and run a scan to seed trigger prices." />
      )}

      {rows?.length > 0 && (
        <table className="stable">
          <thead>
            <tr>
              <th>Symbol</th>
              <th className="r">ATH price</th>
              <th className="r">ATH date</th>
              <th className="r">Last updated</th>
              <th className="r">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <Fragment key={r.symbol}>
                <tr>
                  <td className="mono strong">{r.symbol}</td>
                  {editing === r.symbol ? (
                    <>
                      <td className="r">
                        <input className="mdb-input num" value={form.price}
                               aria-label="ATH price"
                               onChange={(e) => setForm(
                                 { ...form, price: e.target.value })} />
                      </td>
                      <td className="r">
                        <input className="mdb-input mono" value={form.date}
                               placeholder="YYYY-MM-DD" aria-label="ATH date"
                               onChange={(e) => setForm(
                                 { ...form, date: e.target.value })} />
                      </td>
                      <td />
                      <td className="r">
                        <button className="btn primary sm"
                                onClick={() => save(r.symbol)}>Save</button>
                        <button className="btn subtle-btn sm"
                                onClick={() => setEditing(null)}>Cancel</button>
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="r num strong">{num(r.ath_price)}</td>
                      <td className="r subtle">{r.ath_date ?? '\u2014'}</td>
                      <td className="r subtle">
                        {r.last_updated
                          ? r.last_updated.replace('T', ' ').slice(0, 16)
                          : '\u2014'}
                      </td>
                      <td className="r">
                        <button className="btn subtle-btn sm"
                                onClick={() => beginEdit(r)}>Edit</button>
                        <button className="btn subtle-btn sm"
                                onClick={() => setExpanded(
                                  expanded === r.symbol ? null : r.symbol)}>
                          {expanded === r.symbol ? 'Hide' : 'History'}
                        </button>
                      </td>
                    </>
                  )}
                </tr>
                {expanded === r.symbol && (
                  <tr className="mdb-events">
                    <td colSpan={5}><EventList symbol={r.symbol} /></td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}

      <div className="card pad danger-card">
        <div className="card-head">
          <span className="eyebrow">Danger zone</span>
        </div>
        <p className="subtle tight">
          Clears every stored ATH price and trigger, for a clean re-seed
          under corrected logic. Universe and profit data are untouched.
          After clearing, go to the Scanner tab and press Run ATH scan to
          reseed the whole universe from scratch &mdash; that takes several
          minutes, since each symbol needs its full price history refetched.
        </p>
        {resetNote && <div className="banner compact">{resetNote}</div>}
        <label className="mdb-checkbox subtle tight">
          <input type="checkbox" checked={wipeEvents}
                 onChange={(e) => setWipeEvents(e.target.checked)} />
          {' '}also clear the change history (seed/sync/split/manual log)
        </label>
        <div className="uni-row">
          <input className="mdb-input" placeholder="Type RESET to enable"
                 value={resetPhrase}
                 aria-label="Type RESET to confirm"
                 onChange={(e) => setResetPhrase(e.target.value)} />
          <button className="btn danger"
                  disabled={resetPhrase.trim().toUpperCase() !== 'RESET'
                           || resetting}
                  onClick={resetAth}>
            {resetting ? 'Clearing\u2026' : 'Clear all ATH data'}
          </button>
        </div>
      </div>
    </div>
  );
}
