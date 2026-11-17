'use strict';
// The path check (protocol/path-check.md). Pure functions of the path.

const unicode = require('./unicode');

const MAX_PATH_BYTES = 200;
const MAX_SEGMENT_BYTES = 100;
const FORBIDDEN = new Set(['\\', ':', '*', '?', '"', '<', '>', '|']);
const DEVICE_NAMES = new Set(['con', 'prn', 'aux', 'nul']);
const NUMBERED_DEVICES = new Set(['com', 'lpt']);
const DEVICE_DIGITS = new Set(['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '¹', '²', '³']);

function byteLength(text) {
  return Buffer.byteLength(text, 'utf8');
}

// Lower-cases ASCII letters only. Device names are ASCII, so nothing else matters.
function asciiLower(text) {
  return text.replace(/[A-Z]/g, (letter) => String.fromCharCode(letter.charCodeAt(0) + 32));
}

function hasForbiddenCharacter(path) {
  for (const character of path) {
    const code = character.codePointAt(0);
    if (code <= 0x1f || code === 0x7f || FORBIDDEN.has(character)) return true;
  }
  return false;
}

function isReservedName(segment) {
  const stem = asciiLower(segment.split('.')[0]);
  if (DEVICE_NAMES.has(stem)) return true;
  const characters = Array.from(stem);
  return characters.length === 4 && NUMBERED_DEVICES.has(characters.slice(0, 3).join('')) && DEVICE_DIGITS.has(characters[3]);
}

// Checks one path given as bytes. Returns { accepted: true } or { refused: reason }.
function checkPath(bytes) {
  let path;
  try {
    path = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch (error) {
    return { refused: 'not-utf8' };
  }
  if (path === '') return { refused: 'empty' };
  if (bytes.length > MAX_PATH_BYTES) return { refused: 'too-long' };
  const segments = path.split('/');
  if (segments.some((segment) => segment === '')) return { refused: 'empty-segment' };
  if (segments.some((segment) => segment === '.' || segment === '..')) return { refused: 'dot-segment' };
  if (segments.some((segment) => byteLength(segment) > MAX_SEGMENT_BYTES)) return { refused: 'segment-too-long' };
  if (hasForbiddenCharacter(path)) return { refused: 'forbidden-character' };
  if (segments.some((segment) => segment.endsWith('.') || segment.endsWith(' '))) return { refused: 'trailing-dot-or-space' };
  if (segments.some((segment) => segment.startsWith(' '))) return { refused: 'leading-space' };
  if (segments.some(isReservedName)) return { refused: 'reserved-name' };
  if (!unicode.isNfc(path)) return { refused: 'not-nfc' };
  const codes = unicode.toCodePoints(path);
  if (codes.some((code) => !unicode.isAssigned(code))) return { refused: 'unassigned-character' };
  return { accepted: true };
}

// Finds the pairs of paths that are equal once case is ignored.
// Returns [[a, b], ...], each pair in order and the list sorted.
function findCollisions(paths) {
  const groups = new Map();
  for (const path of new Set(paths)) {
    const key = unicode.caselessKey(path);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(path);
  }
  const pairs = [];
  for (const group of groups.values()) {
    group.sort();
    for (let i = 0; i < group.length; i += 1) {
      for (let j = i + 1; j < group.length; j += 1) pairs.push([group[i], group[j]]);
    }
  }
  return pairs.sort((x, y) => (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : x[1] < y[1] ? -1 : x[1] > y[1] ? 1 : 0));
}

module.exports = { checkPath, findCollisions };
