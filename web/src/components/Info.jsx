/* A hoverable explanation.

   Descriptions come from the catalog, so a label's tooltip is identical
   wherever that label appears -- grid header, company tile, compare row,
   screener field. One source, no drift.

   Rendered through a portal into document.body rather than inline: the
   trigger sits inside tiles and table cells that clip overflow (for text
   ellipsis), so an inline absolutely-positioned popover was being clipped
   invisibly by its own ancestor -- the icon would highlight on hover but
   the tooltip itself never appeared. Portaling escapes that ancestor chain
   entirely, and position is computed from the trigger's own bounding box. */
import { useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

export default function Info({ text, source, coverage, name }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  const markRef = useRef(null);

  useLayoutEffect(() => {
    if (!open || !markRef.current) return;
    const r = markRef.current.getBoundingClientRect();
    setPos({
      // Centered above the trigger, in viewport coordinates -- position:
      // fixed in the portal, so no ancestor's scroll or transform applies.
      left: r.left + r.width / 2,
      top: r.top,
    });
  }, [open]);

  if (!text) return null;

  return (
    <span className="info"
          ref={markRef}
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => setOpen(false)}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          tabIndex={0} role="button" aria-label="What this means">
      <span className="info-mark">i</span>
      {open && pos && createPortal(
        <span className="info-pop" role="tooltip"
              style={{ left: pos.left, top: pos.top }}>
          <span className="info-text">{text}</span>
          <span className="info-meta subtle">
            {name && <code className="mono">{name}</code>}
            {coverage != null && <span>{coverage}% populated</span>}
            {source === 'curated' && <span>definition checked</span>}
          </span>
        </span>,
        document.body
      )}
    </span>
  );
}
