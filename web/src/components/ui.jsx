/* Shared UI primitives.
   RankBar is the signature element: wherever a percentile rank exists, the
   number carries a hairline showing where it sits in its universe. You never
   read a P/E of 34 without seeing it is the 71st percentile of its sector. */
import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import { formatValue } from '../lib/format';

/* ------------------------------------------------------------- RankBar */
export function RankBar({ value, width = 46, title }) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  const pct = Math.max(0, Math.min(100, value));
  return (
    <span
      className="rankbar"
      style={{ width }}
      title={title ?? `${pct.toFixed(0)}th percentile`}
      aria-label={`${pct.toFixed(0)}th percentile`}
    >
      <span className="rankbar-fill" style={{ width: `${pct}%` }} />
    </span>
  );
}

/* Number + its rank hairline, stacked. The core cell of the whole app. */
export function RankedValue({ value, spec, rank, align = 'right' }) {
  return (
    <span className="ranked" style={{ alignItems:
      align === 'right' ? 'flex-end' : 'flex-start' }}>
      <span className="num">{formatValue(value, spec)}</span>
      <RankBar value={rank} />
    </span>
  );
}

/* --------------------------------------------------------------- Chips */
export function TierChip({ tier }) {
  if (!tier) return null;
  return <span className={`chip tier-${tier}`}>{tier}</span>;
}

/* ---------------------------------------------------------- Load/error */
export function Loading({ label = 'Loading' }) {
  return (
    <div className="state">
      <div className="spinner" aria-hidden="true" />
      <span className="muted">{label}</span>
    </div>
  );
}

/* Errors say what happened and how to fix it, never apologise, never vague. */
export function ErrorState({ error, onRetry }) {
  const unreachable = error?.status === 0;
  return (
    <div className="state">
      <div className="eyebrow" style={{ color: 'var(--down)' }}>
        {unreachable ? 'API unreachable' : 'Request failed'}
      </div>
      <p style={{ margin: '4px 0 0', maxWidth: 420 }}>{error?.message}</p>
      {unreachable && (
        <code className="hint">uvicorn api.main:app --reload --port 8000</code>
      )}
      {onRetry && (
        <button className="btn" onClick={onRetry} style={{ marginTop: 12 }}>
          Try again
        </button>
      )}
    </div>
  );
}

export function Empty({ title, hint }) {
  return (
    <div className="state">
      <div className="eyebrow">{title}</div>
      {hint && <p className="muted" style={{ margin: '4px 0 0' }}>{hint}</p>}
    </div>
  );
}

/* -------------------------------------------------------------- Search */
export function CompanySearch({ onPick, placeholder = 'Search companies' }) {
  const [q, setQ] = useState('');
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef(null);
  const inputRef = useRef(null);

  /* "/" focuses search from anywhere, unless the user is already typing
     somewhere. Escape returns focus to the page. */
  useEffect(() => {
    function onKey(e) {
      const el = document.activeElement;
      const typing = el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'
                            || el.isContentEditable);
      if (e.key === '/' && !typing && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        inputRef.current?.focus();
      } else if (e.key === 'Escape' && el === inputRef.current) {
        inputRef.current.blur();
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    if (q.trim().length < 1) { setResults([]); return; }
    let cancelled = false;
    const t = setTimeout(() => {
      api.search(q, 8)
        .then((r) => !cancelled && (setResults(r.results), setActive(0)))
        .catch(() => !cancelled && setResults([]));
    }, 140);
    return () => { cancelled = true; clearTimeout(t); };
  }, [q]);

  useEffect(() => {
    const onDoc = (e) =>
      boxRef.current && !boxRef.current.contains(e.target) && setOpen(false);
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  function pick(r) {
    onPick(r.symbol);
    setQ('');
    setOpen(false);
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
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  }

  return (
    <div className="search" ref={boxRef}>
      <input
        ref={inputRef}
        value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        aria-label={placeholder}
      />
      {!q && <kbd className="search-kbd">/</kbd>}
      {open && results.length > 0 && (
        <ul className="search-results" role="listbox">
          {results.map((r, i) => (
            <li
              key={r.symbol}
              role="option"
              aria-selected={i === active}
              className={i === active ? 'active' : ''}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => { e.preventDefault(); pick(r); }}
            >
              <span className="mono" style={{ fontWeight: 600 }}>{r.symbol}</span>
              <span className="muted ellipsis">{r.name}</span>
              <TierChip tier={r.cap_tier} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- Stats */
export function Stat({ label, value, sub, tone }) {
  return (
    <div className="stat">
      <div className="eyebrow">{label}</div>
      <div className={`stat-value num ${tone ?? ''}`}>{value}</div>
      {sub && <div className="stat-sub muted">{sub}</div>}
    </div>
  );
}
