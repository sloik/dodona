'use strict';
// Turns what the strict reader returns (Map, BigInt) into plain JavaScript values.
// Keys are defined as own data properties, so a key such as `__proto__` is kept as data.

function plain(value) {
  if (value instanceof Map) {
    const object = {};
    for (const [key, member] of value) Object.defineProperty(object, key, { value: plain(member), enumerable: true, writable: true, configurable: true });
    return object;
  }
  if (Array.isArray(value)) return value.map(plain);
  if (typeof value === 'bigint') return Number(value);
  return value;
}

module.exports = { plain };
