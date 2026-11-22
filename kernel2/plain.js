'use strict';
// Turns what the strict reader returns (Map, BigInt) into plain JavaScript values.
// Keys are defined as own data properties, so a key such as `__proto__` is kept as data.
//
// Containers are converted with a stack of their own, not by recursion, so a value
// the strict reader read at any depth is converted whole and the command that asked
// for it decides what to do with the depth.

function scalar(value) {
  return typeof value === 'bigint' ? Number(value) : value;
}

// An empty plain container for a Map or an array, with the members still to convert;
// null for anything else.
function open(value) {
  if (value instanceof Map) return { out: {}, members: [...value], next: 0 };
  if (Array.isArray(value)) return { out: [], members: value.map((member, index) => [index, member]), next: 0 };
  return null;
}

function put(out, key, value) {
  if (Array.isArray(out)) out.push(value);
  else Object.defineProperty(out, key, { value, enumerable: true, writable: true, configurable: true });
}

function plain(value) {
  const root = open(value);
  if (root === null) return scalar(value);
  const stack = [root];
  while (stack.length > 0) {
    const frame = stack[stack.length - 1];
    if (frame.next === frame.members.length) {
      stack.pop();
      continue;
    }
    const [key, member] = frame.members[frame.next];
    frame.next += 1;
    const inner = open(member);
    if (inner === null) {
      put(frame.out, key, scalar(member));
    } else {
      put(frame.out, key, inner.out);
      stack.push(inner);
    }
  }
  return root.out;
}

module.exports = { plain };
