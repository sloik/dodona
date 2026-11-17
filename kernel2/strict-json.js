'use strict';
// A strict JSON reader. JSON.parse cannot tell 1 from 1.0, cannot see repeated
// keys and silently accepts some things we must refuse, so we read the text
// ourselves.
//
// read(text) returns { value } or { refused: reason }. Objects become Map,
// integers become BigInt, so nothing is rounded on the way in.
//
// Syntax is judged first: a text that is not JSON is `not-json` whatever else
// is wrong with it. Otherwise the first problem found in reading order is the
// reason.

class Syntax extends Error {}

const MAX_SAFE = 9007199254740991n;

function read(text) {
  let at = 0;
  let problem = null; // the first semantic problem, in reading order

  const note = (reason) => {
    if (problem === null) problem = reason;
  };
  const fail = () => {
    throw new Syntax();
  };

  function skipSpace() {
    while (at < text.length && (text[at] === ' ' || text[at] === '\t' || text[at] === '\n' || text[at] === '\r')) at += 1;
  }

  function expect(literal) {
    if (text.startsWith(literal, at)) at += literal.length;
    else fail();
  }

  function readValue() {
    skipSpace();
    const ch = text[at];
    if (ch === '{') return readObject();
    if (ch === '[') return readArray();
    if (ch === '"') return readString();
    if (ch === 't') return expect('true'), true;
    if (ch === 'f') return expect('false'), false;
    if (ch === 'n') return expect('null'), null;
    if (ch === '-' || (ch >= '0' && ch <= '9')) return readNumber();
    return fail();
  }

  function readObject() {
    at += 1; // {
    const members = new Map();
    skipSpace();
    if (text[at] === '}') {
      at += 1;
      return members;
    }
    for (;;) {
      skipSpace();
      if (text[at] !== '"') fail();
      const key = readString();
      skipSpace();
      if (text[at] !== ':') fail();
      at += 1;
      const value = readValue();
      if (members.has(key)) note('duplicate-key');
      members.set(key, value);
      skipSpace();
      if (text[at] === ',') {
        at += 1;
      } else if (text[at] === '}') {
        at += 1;
        return members;
      } else {
        fail();
      }
    }
  }

  function readArray() {
    at += 1; // [
    const items = [];
    skipSpace();
    if (text[at] === ']') {
      at += 1;
      return items;
    }
    for (;;) {
      items.push(readValue());
      skipSpace();
      if (text[at] === ',') {
        at += 1;
      } else if (text[at] === ']') {
        at += 1;
        return items;
      } else {
        fail();
      }
    }
  }

  function readDigits() {
    const start = at;
    while (text[at] >= '0' && text[at] <= '9') at += 1;
    return text.slice(start, at);
  }

  function readNumber() {
    const start = at;
    if (text[at] === '-') at += 1;
    if (text[at] === '0') {
      at += 1;
    } else if (text[at] >= '1' && text[at] <= '9') {
      readDigits();
    } else {
      fail();
    }
    let fractionOrExponent = false;
    if (text[at] === '.') {
      at += 1;
      if (readDigits() === '') fail();
      fractionOrExponent = true;
    }
    if (text[at] === 'e' || text[at] === 'E') {
      at += 1;
      if (text[at] === '+' || text[at] === '-') at += 1;
      if (readDigits() === '') fail();
      fractionOrExponent = true;
    }
    if (fractionOrExponent) {
      note('not-an-integer');
      return 0n;
    }
    const number = BigInt(text.slice(start, at));
    if (number > MAX_SAFE || number < -MAX_SAFE) note('integer-out-of-range');
    return number;
  }

  function hex4() {
    const digits = text.slice(at, at + 4);
    if (!/^[0-9a-fA-F]{4}$/.test(digits)) fail();
    at += 4;
    return parseInt(digits, 16);
  }

  function readString() {
    at += 1; // opening quote
    let out = '';
    let invalid = false;
    for (;;) {
      if (at >= text.length) fail();
      const unit = text.charCodeAt(at);
      if (unit === 0x22) {
        at += 1;
        break;
      }
      if (unit < 0x20) fail();
      if (unit !== 0x5c) {
        out += text[at];
        at += 1;
        continue;
      }
      at += 1; // backslash
      const escape = text[at];
      at += 1;
      const simple = { '"': '"', '\\': '\\', '/': '/', b: '\b', f: '\f', n: '\n', r: '\r', t: '\t' };
      if (escape in simple) {
        out += simple[escape];
      } else if (escape === 'u') {
        const first = hex4();
        if (first >= 0xd800 && first <= 0xdbff && text.startsWith('\\u', at)) {
          const save = at;
          at += 2;
          const second = hex4();
          if (second >= 0xdc00 && second <= 0xdfff) {
            out += String.fromCharCode(first, second);
            continue;
          }
          at = save; // not a pair: the high surrogate is alone
        }
        if (first >= 0xd800 && first <= 0xdfff) invalid = true;
        else out += String.fromCharCode(first);
      } else {
        fail();
      }
    }
    if (invalid) note('invalid-string');
    return out;
  }

  try {
    const value = readValue();
    skipSpace();
    if (at !== text.length) fail();
    return problem === null ? { value } : { refused: problem };
  } catch (error) {
    if (error instanceof Syntax) return { refused: 'not-json' };
    throw error;
  }
}

module.exports = { read, MAX_SAFE };
