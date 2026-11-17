'use strict';
// Unicode 15.1 normalisation and case folding, built on unicode-tables.js.
// Strings are handled as arrays of code points (numbers). Nothing here uses
// the platform's own normalize(), case conversion or Unicode property classes.

const tables = require('./unicode-tables');

// Hangul syllables are decomposed and composed by arithmetic, not by tables.
const S_BASE = 0xac00;
const L_BASE = 0x1100;
const V_BASE = 0x1161;
const T_BASE = 0x11a7;
const L_COUNT = 19;
const V_COUNT = 21;
const T_COUNT = 28;
const N_COUNT = V_COUNT * T_COUNT;
const S_COUNT = L_COUNT * N_COUNT;

const combiningClass = new Map();
for (const [first, last, value] of tables.combiningClasses) {
  for (let code = first; code <= last; code += 1) combiningClass.set(code, value);
}
const decompositionOf = new Map(tables.decompositions);
const foldingOf = new Map(tables.foldings);
const compositionOf = new Map();
for (const [first, second, composite] of tables.compositions) compositionOf.set(first * 0x200000 + second, composite);

function toCodePoints(text) {
  return Array.from(text, (character) => character.codePointAt(0));
}

function fromCodePoints(codes) {
  return codes.map((code) => String.fromCodePoint(code)).join('');
}

function classOf(code) {
  return combiningClass.get(code) || 0;
}

// True if the code point is assigned in the pinned Unicode version.
function isAssigned(code) {
  let low = 0;
  let high = tables.assigned.length - 1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    const [first, last] = tables.assigned[middle];
    if (code < first) high = middle - 1;
    else if (code > last) low = middle + 1;
    else return true;
  }
  return false;
}

// Appends the full canonical decomposition of one code point to `out`.
function decomposeInto(code, out) {
  if (code >= S_BASE && code < S_BASE + S_COUNT) {
    const index = code - S_BASE;
    out.push(L_BASE + Math.floor(index / N_COUNT));
    out.push(V_BASE + Math.floor((index % N_COUNT) / T_COUNT));
    if (index % T_COUNT !== 0) out.push(T_BASE + (index % T_COUNT));
    return;
  }
  const mapping = decompositionOf.get(code);
  if (mapping === undefined) {
    out.push(code);
    return;
  }
  for (const part of mapping) decomposeInto(part, out);
}

// Puts each run of combining marks (class not 0) into order of class,
// keeping the order of marks with the same class.
function reorder(codes) {
  const out = [];
  let run = [];
  const flush = () => {
    const sorted = run
      .map((code, position) => ({ code, position, value: classOf(code) }))
      .sort((a, b) => a.value - b.value || a.position - b.position);
    for (const item of sorted) out.push(item.code);
    run = [];
  };
  for (const code of codes) {
    if (classOf(code) === 0) {
      flush();
      out.push(code);
    } else {
      run.push(code);
    }
  }
  flush();
  return out;
}

function nfd(codes) {
  const out = [];
  for (const code of codes) decomposeInto(code, out);
  return reorder(out);
}

// The composite of two code points, or undefined.
function compose(first, second) {
  if (first >= L_BASE && first < L_BASE + L_COUNT && second >= V_BASE && second < V_BASE + V_COUNT) {
    return S_BASE + ((first - L_BASE) * V_COUNT + (second - V_BASE)) * T_COUNT;
  }
  const isLV = first >= S_BASE && first < S_BASE + S_COUNT && (first - S_BASE) % T_COUNT === 0;
  if (isLV && second > T_BASE && second < T_BASE + T_COUNT) return first + (second - T_BASE);
  return compositionOf.get(first * 0x200000 + second);
}

function nfc(codes) {
  const out = [];
  let starter = -1; // position in `out` of the last starter
  let lastClass = 0; // class of the last code point added after that starter
  for (const code of nfd(codes)) {
    const value = classOf(code);
    if (starter >= 0) {
      const adjacent = out.length - 1 === starter;
      const blocked = !adjacent && lastClass >= value;
      if (!blocked) {
        const composite = compose(out[starter], code);
        if (composite !== undefined) {
          out[starter] = composite;
          continue;
        }
      }
    }
    if (value === 0) starter = out.length;
    out.push(code);
    lastClass = value;
  }
  return out;
}

// Unicode full case folding.
function fold(codes) {
  const out = [];
  for (const code of codes) {
    const mapping = foldingOf.get(code);
    if (mapping === undefined) out.push(code);
    else out.push(...mapping);
  }
  return out;
}

// Unicode's canonical caseless form: NFD, full case folding, NFD again.
function caselessKey(text) {
  return fromCodePoints(nfd(fold(nfd(toCodePoints(text)))));
}

function isNfc(text) {
  const codes = toCodePoints(text);
  const composed = nfc(codes);
  return composed.length === codes.length && composed.every((code, position) => code === codes[position]);
}

module.exports = { toCodePoints, fromCodePoints, isAssigned, nfd, nfc, fold, caselessKey, isNfc, classOf };
