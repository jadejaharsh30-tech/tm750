/* Search every datapoint on a company page.

   Matches label, raw column name, and group -- so "roce", "return on
   capital" and "profitability" all reach the same tile. The dropdown shows
   the current value alongside each hit, which often answers the question
   without navigating at all.

   Selecting one switches tab, expands the group if it is collapsed, scrolls
   the tile into view and flashes it. Ctrl/Cmd+K focuses. Not "/" -- that is
   already the global company search, and overloading it would break the
   habit. */
import { useEffect, useMemo, useRef, useState } from 'react';
import { formatValue } from '../lib/format';

export default function DatapointSearch({ items, onJump }) {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    function onKey(e) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
        setOpen(true);
      } else if (e.key === 'Escape' && document.activeElement === inputRef.current) {
        setQ(''); setOpen(false); inputRef.current.blur();
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    const onDoc = (e) =>
      boxRef.current && !boxRef.current.contains(e.target) && setOpen(false);
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const results = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return [];
    const scored = [];
    for (const it of items) {
      const label = it.label.toLowerCase();
      const name = it.name.toLowerCase();
      const group = (it.group ?? '').toLowerCase();
      let score = null;
      // Ranked so an exact label match never sits below a group match.
      if (label === term || name === term) score = 0;
      else if (label.startsWith(term) || name.startsWith(term)) score = 1;
      else if (label.includes(term) || name.includes(term)) score = 2;
      else if (group.includes(term)) score = 3;
      if (score !== null) scored.push({ ...it, score });
    }
    return scored
      .sort((a, b) => a.score - b.score || a.label.localeCompare(b.label))
      .slice(0, 12);
  }, [q, items]);

  useEffect(() => { setActive(0); }, [q]);

  function pick(r) {
    onJump(r);
    setQ('');
    setOpen(false);
    inputRef.current?.blur();
  }

  function onKeyDown(e) {
    if (!results.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault(); setActive((a) => (a + 1) % results.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((a) => (a - 1 + results.length) % results.length);
    } else if (e.key === 'Enter') {
      e.preventDefault(); pick(results[active]);
    }
  }

  return (
    <div className="dpsearch" ref={boxRef}>
      <input
        ref={inputRef}
        value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        placeholder={`Find any of ${items.length} datapoints`}
        aria-label="Search datapoints on this company"
      />
      {!q && <kbd className="search-kbd">⌘K</kbd>}

      {open && q && (
        <ul className="dpresults" role="listbox">
          {results.length === 0 && (
            <li className="dpempty subtle">No datapoint matches “{q}”</li>
          )}
          {results.map((r, i) => (
            <li key={r.name} role="option" aria-selected={i === active}
                className={i === active ? 'active' : ''}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => { e.preventDefault(); pick(r); }}>
              <span className="dp-label ellipsis">{r.label}</span>
              <span className="dp-where subtle ellipsis">
                {r.tab} · {r.group}
              </span>
              <span className="dp-value num">
                {r.masked ? 'n/a' : formatValue(r.value, r)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
