/* Choose which day the whole app is showing.

   Only rendered once more than one snapshot exists -- until then it would be
   a control with a single option, which is noise. Changing it reloads so
   every module refetches; a partial switch where some panels show one date
   and some another would be worse than no picker at all. */
import { useEffect, useRef, useState } from 'react';
import { getAsOf, setAsOf } from '../api/client';

export default function SnapshotPicker({ snapshots }) {
  const [open, setOpen] = useState(false);
  const boxRef = useRef(null);
  const current = getAsOf() ?? snapshots[snapshots.length - 1];
  const isPast = Boolean(getAsOf()) && getAsOf() !== snapshots[snapshots.length - 1];

  useEffect(() => {
    const onDoc = (e) =>
      boxRef.current && !boxRef.current.contains(e.target) && setOpen(false);
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  function choose(date) {
    const latest = snapshots[snapshots.length - 1];
    setAsOf(date === latest ? null : date);
    if (date === latest) sessionStorage.removeItem('tm750-asof');
    else sessionStorage.setItem('tm750-asof', date);
    window.location.reload();
  }

  if (!snapshots || snapshots.length < 2) return null;

  return (
    <div className="snappick" ref={boxRef}>
      <button className={`btn snappick-btn ${isPast ? 'past' : ''}`}
              onClick={() => setOpen((o) => !o)}
              title="Show the data as of a past snapshot">
        <span className="mono">{current}</span>
        {isPast && <span className="snappick-tag">past</span>}
      </button>
      {open && (
        <ul className="snappick-list">
          {[...snapshots].reverse().map((d, i) => (
            <li key={d}>
              <button className={d === current ? 'active' : ''}
                      onClick={() => choose(d)}>
                <span className="mono">{d}</span>
                {i === 0 && <span className="subtle">latest</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
