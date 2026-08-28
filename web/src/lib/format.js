/* Formatting is driven entirely by the catalog's `unit` and `fmt` fields.
   No component decides how a number looks -- it asks here, passing the spec.
   That keeps 462 columns consistent and means a formatting fix lands once. */

/** Indian digit grouping: last three digits, then pairs.
 *  451712 -> "4,51,712"   (not the international "451,712") */
export function groupIndian(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '--';
  const neg = n < 0;
  const [intPart, decPart] = Math.abs(n).toString().split('.');
  let out;
  if (intPart.length <= 3) {
    out = intPart;
  } else {
    const last3 = intPart.slice(-3);
    const rest = intPart.slice(0, -3);
    out = rest.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + last3;
  }
  if (decPart) out += '.' + decPart;
  return (neg ? '-' : '') + out;
}

const CRORE = 1e7; // 1 crore rupees

/** Rupees -> crore, Indian-grouped. 1.9e13 -> "19,00,000" */
export function toCrore(rupees, decimals = 0) {
  if (rupees === null || rupees === undefined || Number.isNaN(rupees)) return '--';
  const cr = rupees / CRORE;
  const rounded = decimals > 0 ? cr.toFixed(decimals) : Math.round(cr);
  return groupIndian(Number(rounded));
}

function fixed(n, d) {
  if (n === null || n === undefined || Number.isNaN(n)) return '--';
  return groupIndian(Number(n.toFixed(d)));
}

/**
 * Format a value using its catalog spec.
 * @param {*} value
 * @param {{unit?:string, fmt?:string}} spec
 * @param {{compact?:boolean, withUnit?:boolean}} opts
 */
export function formatValue(value, spec = {}, opts = {}) {
  const { fmt, unit } = spec;
  const { withUnit = true } = opts;

  if (value === null || value === undefined || value === '') return '--';
  if (unit === 'bool' || typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (unit === 'text' || fmt === 'text') return String(value);
  if (unit === 'date') return String(value).slice(0, 10);

  const n = Number(value);
  if (Number.isNaN(n)) return String(value);

  switch (fmt) {
    case 'cr':
      return withUnit ? `₹${toCrore(n)} Cr` : toCrore(n);
    case '0.1f%':
      return `${fixed(n, 1)}%`;
    case '0.2f':
      return unit === 'inr' && withUnit ? `₹${fixed(n, 2)}` : fixed(n, 2);
    case '0,0':
      return groupIndian(Math.round(n));
    default:
      return fixed(n, 2);
  }
}

/** Compact form for tight spaces (chart axes, dense cells). */
export function formatCompact(value, spec = {}) {
  if (value === null || value === undefined) return '--';
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);

  if (spec.fmt === 'cr') {
    const cr = n / CRORE;
    if (Math.abs(cr) >= 1e5) return `₹${(cr / 1e5).toFixed(2)}L Cr`;
    if (Math.abs(cr) >= 1e3) return `₹${(cr / 1e3).toFixed(1)}k Cr`;
    return `₹${Math.round(cr)} Cr`;
  }
  if (spec.fmt === '0.1f%') return `${n.toFixed(1)}%`;
  if (Math.abs(n) >= 1e5) return groupIndian(Math.round(n));
  return n.toFixed(2);
}

/** Sign class for colouring. Respects catalog polarity: for a
 *  lower-is-better metric a negative change is not automatically bad,
 *  so callers pass polarity when the colour should reflect goodness
 *  rather than raw sign. */
export function signClass(n, polarity = 'neutral') {
  if (n === null || n === undefined || Number.isNaN(n)) return 'flat';
  if (n === 0) return 'flat';
  if (polarity === 'lower_better') return n > 0 ? 'down' : 'up';
  return n > 0 ? 'up' : 'down';
}

export function pct(n, d = 1) {
  if (n === null || n === undefined || Number.isNaN(n)) return '--';
  return `${n.toFixed(d)}%`;
}

/** Signed percentage, for changes. "+2.4%" / "-1.1%" */
export function pctSigned(n, d = 1) {
  if (n === null || n === undefined || Number.isNaN(n)) return '--';
  return `${n > 0 ? '+' : ''}${n.toFixed(d)}%`;
}
