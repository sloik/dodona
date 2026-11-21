'use strict';
// The `status` command: the status of a whole project from its project file, its
// providers and its ledgers (conformance/README.md, "How a project's status is
// judged"; decision 0034). It runs nothing.
//
// In:  one JSON object on standard input (the contract gives its fields).
// Out: {"judged", "report", "coverage", "policy_source", "ledger", "not_served",
//       "not_checkable", "policy_not_applied", "project_doubts", "project_status"},
//      or {"refused": REASON, "detail": TEXT}. Either way the command exits 0.
//
// The steps run in the contract's order; the first rule broken gives the reason and
// nothing after it is done. The report is what this kernel's own status rules, the
// code behind its `scenario` command, give as the last result for the scenario it
// judged. The providers are commands the site names; the kernel names no tool.

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const strictJson = require('./strict-json');
const { plain } = require('./plain');
const { compareUnits } = require('./canonical');
const { identityOf } = require('./identity');
const ledgerFormat = require('./ledger');
const processes = require('./processes');
const { Wire, isObject, MAX_DEPTH } = require('./wire');
const hostRules = require('./host-rules');
const { ECHO } = require('./session');
const { runScenario } = require('./scenario');

const PROTOCOL = '0.2';
const MAX_LINE_BYTES = 1048576;
const MAX_LOG_BYTES = 1048576;
const MOST_DEADLINE_MS = 86400000;
const SERVED = ['obligation.enumerate', 'intent.index'];
const LEVELS = ['self', 'helper', 'apart', 'tested', 'cross-make', 'credentialed'];
const FLOOR_KINDS = ['confirm-baseline', 'match-check', 'grant-amendment', 'close-deferred', 'change-policy'];
const POLICY_FIELDS = ['floors', 'min_hard_gates', 'not_applied', 'required'];
// The step that names nothing, so that a project with an empty ledger has a report too.
const NOTHING = { do: { set_gate: { intent: '', criterion: '', to: 'hard' } } };

const DOUBTS = {
  policy: 'policy no status rule applies',
  children: 'a required intent has children, and no status rule reads descendants yet',
  unchecked: 'obligations the provider could not make into checks',
  unread: "criteria declare what no status rule reads yet: a deferred gate's limit, runs that must agree, or evidence not applicable",
  torn: 'a ledger ends in an entry cut short',
  absent: 'a ledger the site names does not exist',
};

// A rule broken: the reason, and a detail for a person.
class Stop extends Error {
  constructor(reason, detail = '') {
    super(reason);
    this.reason = reason;
    this.detail = detail;
  }
}

function isString(value) {
  return typeof value === 'string';
}

function isStrings(value) {
  return Array.isArray(value) && value.every(isString);
}

function own(object, key) {
  return isObject(object) && Object.hasOwn(object, key) ? object[key] : undefined;
}

// Sets a key as an own data property, so a name such as `__proto__` is kept as data.
function put(object, key, value) {
  Object.defineProperty(object, key, { value, enumerable: true, writable: true, configurable: true });
  return object;
}

// Sorted as the canonical encoding sorts keys, by UTF-16 code units, each member once.
function sortedSet(items) {
  return [...new Set(items)].sort(compareUnits);
}

function isSortedSet(list) {
  return list.every((item, at) => at === 0 || compareUnits(list[at - 1], item) < 0);
}

function sha256Hex(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

// A path that is relative: not empty, not starting with `/`, no `\`, no `:` and no NUL,
// and no segment that is empty, `.` or `..`.
function isRelative(rel) {
  return isString(rel) && rel !== '' && !rel.startsWith('/') && !rel.includes('\\') && !rel.includes(':') && !rel.includes('\u0000')
    && rel.split('/').every((segment) => segment !== '' && segment !== '.' && segment !== '..');
}

function stepsOf(root, rel) {
  const steps = [];
  let at = root;
  for (const part of rel.split('/')) {
    at = path.join(at, part);
    steps.push(at);
  }
  return steps;
}

// How `rel` is reached from the root, looking at each step without following it:
// 'link' if a step is a symbolic link; 'missing' if a step is not there or cannot be
// looked at (a path such a step of which is not shown to be a regular file); otherwise
// 'file' or 'other' by what the last step is.
function reach(root, rel) {
  const steps = stepsOf(root, rel);
  for (let i = 0; i < steps.length; i += 1) {
    let status;
    try {
      status = fs.lstatSync(steps[i]);
    } catch (error) {
      return 'missing';
    }
    if (status.isSymbolicLink()) return 'link';
    if (i === steps.length - 1) return status.isFile() ? 'file' : 'other';
  }
  return 'other';
}

// The input (step 0): one JSON object, from its first byte to its last or followed by
// exactly one line feed, read as a check reads JSON. Null when it cannot be read.
function readInput(bytes) {
  let body = bytes;
  if (body.length > 0 && body[body.length - 1] === 0x0a) body = body.subarray(0, body.length - 1);
  if (body.length === 0 || body[0] !== 0x7b || body[body.length - 1] !== 0x7d) return null;
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(body);
  } catch (error) {
    return null;
  }
  const read = strictJson.read(text, { maxDepth: MAX_DEPTH });
  if (read.refused !== undefined || !(read.value instanceof Map)) return null;
  return plain(read.value);
}

// Step 1, the policy as the site hands it over: why it cannot be read, or null.
function policyProblem(policy) {
  if (!isObject(policy) || Object.keys(policy).sort().join(',') !== POLICY_FIELDS.join(',')) {
    return 'the policy must be an object holding exactly required, min_hard_gates, floors and not_applied';
  }
  if (!isStrings(policy.required)) return 'policy.required is not a list of strings';
  if (!Number.isSafeInteger(policy.min_hard_gates) || policy.min_hard_gates < 0) return 'policy.min_hard_gates is not a whole number of at least 0';
  const floors = policy.floors;
  if (!isObject(floors) || !Object.entries(floors).every(([kind, level]) => FLOOR_KINDS.includes(kind) && LEVELS.includes(level))) {
    return 'policy.floors maps kinds of act to levels on the scale';
  }
  if (!isStrings(policy.not_applied) || !isSortedSet(policy.not_applied)) return 'policy.not_applied is not a sorted list of strings, each once';
  return null;
}

function siteHasShape(site) {
  if (!isObject(site)) return false;
  const platform = own(site, 'platform');
  const tools = own(site, 'tools');
  const providers = own(site, 'providers');
  const deadline = own(site, 'deadline_ms');
  return isString(own(site, 'writer')) && isString(own(site, 'runner'))
    && isObject(platform) && isString(own(platform, 'os')) && isString(own(platform, 'arch'))
    && Array.isArray(tools) && tools.every((tool) => ['name', 'version', 'digest'].every((field) => isString(own(tool, field))))
    && isObject(providers) && Object.values(providers).every((provider) => {
      const command = own(provider, 'command');
      // A command none of whose words holds a NUL, which no program's arguments can carry.
      return isStrings(command) && command.length > 0 && command.every((word) => !word.includes('\u0000')) && isStrings(own(provider, 'code'));
    })
    && Number.isSafeInteger(deadline) && deadline >= 1 && deadline <= MOST_DEADLINE_MS;
}

function isDirectory(root) {
  try {
    return fs.statSync(root).isDirectory();
  } catch (error) {
    return false;
  }
}

// Step 1. Returns the code digest of each provider, by name.
function checkInput(asked) {
  if (!isObject(asked)) throw new Stop('bad-input', 'the input is not one JSON object read strictly');
  const ledgers = own(asked, 'ledgers');
  const shaped = ['root', 'project', 'policy_source', 'owner_ledger'].every((field) => isString(own(asked, field)))
    && isStrings(ledgers) && isRelative(asked.project) && isRelative(asked.owner_ledger) && ledgers.every(isRelative)
    && siteHasShape(own(asked, 'site'));
  if (!shaped) throw new Stop('bad-input', 'the input does not have the shape the contract gives');
  const problem = policyProblem(own(asked, 'policy'));
  if (problem !== null) throw new Stop('bad-input', problem);
  const root = asked.root;
  if (!isDirectory(root)) throw new Stop('bad-input', 'root is not a directory');
  const providers = Object.entries(asked.site.providers).sort(([a], [b]) => compareUnits(a, b));
  for (const [name, provider] of providers) {
    if (new Set(provider.code).size !== provider.code.length) throw new Stop('bad-input', `${name}: a code path listed twice`);
    for (const rel of provider.code) {
      if (!isRelative(rel) || reach(root, rel) !== 'file') throw new Stop('bad-input', `${name}: code path ${JSON.stringify(rel)} is not a regular file under root reached without a link`);
    }
  }
  // Then every provider's code is read, before any provider is started.
  const digests = new Map();
  for (const [name, provider] of providers) {
    const files = {};
    for (const rel of provider.code) {
      try {
        put(files, rel, sha256Hex(fs.readFileSync(path.join(root, rel))));
      } catch (error) {
        throw new Stop('unreadable-file', `${rel}: ${error.code || error.message}`);
      }
    }
    digests.set(name, identityOf(files).slice('sha256:'.length, 'sha256:'.length + 16));
  }
  return digests;
}

// Step 2. The project file, in the subset of TOML the contract allows.

const HEADER = /^(?:\[(project|policy)\]|\[\[(binding|platform|tool)\]\])$/;
const STRING = '"[^"\\\\]*"';
const VALUE = new RegExp(`^(${STRING}|\\[ *(?:${STRING}(?: *, *${STRING})*)? *\\])( +#.*)? *$`, 's');
const KEY = /^([a-z_]+) = (.*)$/s;
const FORBIDDEN = /[\u0000-\u0009\u000b-\u001f\u007f-\u009f]/;
const STRINGS = /"[^"\\]*"/g;
// A pattern segment: any character but `[`, `]`, `\`, `*` and `:`; `*`; or a range of
// two printable ASCII characters other than `/`, `:`, `[`, `\` and `]`.
const RANGE_END = '[!-.0-9;-Z^-~]';
const PATTERN_SEGMENT = new RegExp(`^(?:[^\\[\\]\\\\*:]|\\*|\\[${RANGE_END}-${RANGE_END}\\])+$`, 'u');
const RANGE = /\[(.)-(.)\]/g;

function isPattern(pattern) {
  if (!isString(pattern) || pattern === '' || pattern.startsWith('/')) return false;
  return pattern.split('/').every((segment) => segment !== '.' && segment !== '..' && PATTERN_SEGMENT.test(segment)
    && [...segment.matchAll(RANGE)].every(([, low, high]) => low.codePointAt(0) <= high.codePointAt(0)));
}

function readProject(raw) {
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(raw);
  } catch (error) {
    throw new Stop('bad-project', 'not UTF-8');
  }
  if (text.startsWith('\ufeff')) throw new Stop('bad-project', 'a byte-order mark');
  const singles = new Set();
  const arrays = { binding: [], platform: [], tool: [] };
  let here = null;
  text.split('\n').forEach((line, index) => {
    const number = index + 1;
    if (FORBIDDEN.test(line)) throw new Stop('bad-project', `line ${number}: a carriage return, tab or control character`);
    if (/^ *$/.test(line) || /^ *#/.test(line)) return;
    const header = HEADER.exec(line);
    if (header !== null) {
      if (header[1] !== undefined) {
        if (singles.has(header[1])) throw new Stop('bad-project', `line ${number}: [${header[1]}] is given twice`);
        singles.add(header[1]);
        here = new Map();
      } else {
        here = new Map();
        arrays[header[2]].push(here);
      }
      return;
    }
    const pair = KEY.exec(line);
    const value = pair === null ? null : VALUE.exec(pair[2]);
    if (value === null) throw new Stop('bad-project', `line ${number}: not in the subset of TOML a kernel reads`);
    if (here === null || here.has(pair[1])) throw new Stop('bad-project', `line ${number}: a key before any header, or given twice`);
    const written = value[1];
    here.set(pair[1], written.startsWith('[') ? (written.match(STRINGS) || []).map((item) => item.slice(1, -1)) : written.slice(1, -1));
  });
  const bindings = arrays.binding.map((table) => ({
    name: table.get('name'), provider: table.get('provider'), capabilities: table.get('capabilities'), match: table.has('match') ? table.get('match') : [],
  }));
  for (const binding of bindings) {
    if (!isString(binding.name) || !isString(binding.provider) || !Array.isArray(binding.capabilities) || !Array.isArray(binding.match)) {
      throw new Stop('bad-project', 'a binding needs a name, a provider and a list of capabilities, and match is a list');
    }
    if (!binding.match.every(isPattern)) throw new Stop('bad-project', `binding ${binding.name}: a match pattern outside the pattern language`);
  }
  if (new Set(bindings.map((binding) => binding.name)).size !== bindings.length) throw new Stop('bad-project', 'two bindings have one name');
  return bindings;
}

// Step 4. Files a binding claims.

// Every regular file under the root, by relative path, reached without a link at any
// step and with no segment `.git`. Entries are told apart by what the listing says.
function regularFiles(root) {
  const found = [];
  const todo = [''];
  while (todo.length > 0) {
    const rel = todo.pop();
    let entries;
    try {
      entries = fs.readdirSync(rel === '' ? root : path.join(root, rel), { withFileTypes: true });
    } catch (error) {
      throw new Stop('unreadable-file', `${rel || '.'}: ${error.code || error.message}`);
    }
    for (const entry of entries) {
      if (entry.name === '.git' || entry.isSymbolicLink()) continue;
      const child = rel === '' ? entry.name : `${rel}/${entry.name}`;
      if (entry.isDirectory()) todo.push(child);
      else if (entry.isFile()) found.push(child);
    }
  }
  return found;
}

// One segment of a pattern against one segment of a path: `*` is any run of
// characters, `[a-b]` one character from a to b, anything else itself.
function segmentMatches(pattern, name) {
  const tokens = [];
  const chars = [...pattern];
  for (let i = 0; i < chars.length; i += 1) {
    if (chars[i] === '*') tokens.push({ star: true });
    else if (chars[i] === '[') {
      tokens.push({ low: chars[i + 1].codePointAt(0), high: chars[i + 3].codePointAt(0) });
      i += 4;
    } else tokens.push({ code: chars[i].codePointAt(0) });
  }
  const codes = [...name].map((character) => character.codePointAt(0));
  // can[j]: the tokens so far match the first j characters.
  let can = codes.map(() => false).concat(false);
  can[0] = true;
  for (const token of tokens) {
    const next = can.map(() => false);
    if (token.star) {
      let reached = false;
      for (let j = 0; j < can.length; j += 1) {
        reached = reached || can[j];
        next[j] = reached;
      }
    } else {
      for (let j = 0; j < codes.length; j += 1) {
        if (!can[j]) continue;
        const code = codes[j];
        next[j + 1] = token.code !== undefined ? code === token.code : token.low <= code && code <= token.high;
      }
    }
    can = next;
  }
  return can[codes.length];
}

function pathMatches(pattern, rel) {
  const wanted = pattern.split('/');
  const parts = rel.split('/');
  return wanted.length === parts.length && wanted.every((segment, at) => segmentMatches(segment, parts[at]));
}

function claimedFiles(root, files, patterns) {
  return files.filter((rel) => patterns.some((pattern) => pathMatches(pattern, rel))).sort(compareUnits).map((rel) => {
    try {
      return { path: rel, identity: `sha256:${sha256Hex(fs.readFileSync(path.join(root, rel)))}` };
    } catch (error) {
      throw new Stop('unreadable-file', `${rel}: ${error.code || error.message}`);
    }
  });
}

// Steps 5 and 7: one session with a provider, one request, as in a check.

function answerProblem(message, id, capability) {
  if (message.id !== id) return 'wrong-id';
  if (message.type === 'error') return 'provider-error';
  if (message.type !== 'result' || !isObject(message.body)) return 'unexpected';
  if (message.capability !== capability) return 'wrong-capability';
  return null;
}

async function converse(wire, binding, deadline, capability, body) {
  const until = () => performance.now() + deadline;
  const helloSent = await wire.send({ type: 'hello', protocol: [PROTOCOL], limits: { max_line_bytes: MAX_LINE_BYTES, deadline_ms: deadline }, echo: ECHO }, until());
  if (helloSent !== null) throw new Stop(helloSent, binding.provider);
  const opening = await wire.next(until());
  if (opening.reason !== undefined) throw new Stop(opening.reason, binding.provider);
  if (opening.message.type !== 'manifest' || opening.message.echo !== ECHO) throw new Stop('bad-manifest', 'no manifest, or its echo differs');
  const manifest = own(opening.message, 'manifest');
  if (hostRules.manifestProblem(manifest) !== null) throw new Stop('bad-manifest', 'the manifest does not have its shape');
  if (!isString(own(manifest, 'name')) || !isString(own(manifest, 'version')) || own(manifest, 'protocol') !== PROTOCOL) {
    throw new Stop('bad-manifest', 'name and version must be strings, and protocol the one hello offered, 0.2');
  }
  if (manifest.name !== binding.provider) {
    throw new Stop('provider-mismatch', `binding ${binding.name} names ${binding.provider}, the provider says ${manifest.name}`);
  }
  const requestSent = await wire.send({ type: 'request', id: '1', deadline_ms: deadline, capability, body }, until());
  if (requestSent !== null) throw new Stop(requestSent, capability);
  const answer = await wire.next(until());
  if (answer.reason !== undefined) throw new Stop(answer.reason, capability);
  const problem = answerProblem(answer.message, '1', capability);
  if (problem !== null) throw new Stop(problem, capability);
  return { manifest, body: answer.message.body };
}

// shutdown at the end of every session, a moment to exit, and every process ended.
async function endSession(wire, child) {
  wire.post({ type: 'shutdown' });
  wire.close();
  await Promise.race([child.exited, processes.pause(1000)]);
  await processes.endTree(child);
}

// One session, one request. The session ends here, after its answer or on any rule
// broken, unless `keep` is given and the answer was read: then `keep` is handed the
// open session, whose next request takes id 2, and whoever holds it ends it (the run
// command, for the checks of a binding that lists obligation.check).
async function ask(root, site, binding, capability, body, keep = null) {
  const child = processes.start(site.providers[binding.provider].command, root);
  if (child.pid === undefined) {
    await child.exited;
    throw new Stop('provider-not-started', binding.provider);
  }
  const wire = new Wire(child, { maxLine: MAX_LINE_BYTES, maxLog: MAX_LOG_BYTES, strict: true });
  let answer = null;
  try {
    answer = await converse(wire, binding, site.deadline_ms, capability, body);
    return answer;
  } finally {
    if (keep === null || answer === null) await endSession(wire, child);
    else keep({ binding, wire, child, manifest: answer.manifest, next_id: 2 });
  }
}

function byName(a, b) {
  return compareUnits(a.name, b.name);
}

// Step 5 and 6. Obligations and their keys.

function obligationHasShape(item) {
  return isObject(item) && isString(own(item, 'name')) && item.name !== '' && isString(own(item, 'kind'))
    && isStrings(own(item, 'specified_by')) && isStrings(own(item, 'targets')) && isString(own(item, 'expect'))
    && isObject(own(item, 'config')) && Object.hasOwn(item, 'inputs') && (!Object.hasOwn(item, 'defect_of') || isString(item.defect_of));
}

// `kept`, given only by the run command, is a list each session of a binding that lists
// obligation.check is added to as soon as its answer is read, so that whoever holds the
// list can end it on any later refusal as well as at the end of the run.
async function obligationsOf(root, site, digests, bindings, claims, kept = null) {
  const found = new Map();
  const listed = [];
  let unchecked = [];
  for (const binding of bindings.filter((b) => b.capabilities.includes('obligation.enumerate')).sort(byName)) {
    const files = claims.get(binding.name);
    const identities = new Map(files.map((file) => [file.path, file.identity]));
    const request = { binding: binding.name, definitions: [], files };
    let session = null;
    const keep = kept !== null && binding.capabilities.includes('obligation.check') ? (held) => {
      session = held;
      kept.push(held);
    } : null;
    const { manifest, body } = await ask(root, site, binding, 'obligation.enumerate', request, keep);
    const items = own(body, 'obligations');
    const rejected = Object.hasOwn(body, 'rejected') ? body.rejected : [];
    if (!Array.isArray(items) || !Array.isArray(rejected) || !rejected.every((entry) => isString(own(entry, 'name')))
      || !items.every(obligationHasShape)) {
      throw new Stop('bad-answer', `binding ${binding.name}: the answer does not have the shape the contract gives`);
    }
    for (const item of items) {
      if (!isStrings(item.inputs) || !isSortedSet(item.inputs) || !item.inputs.every((rel) => identities.has(rel))) throw new Stop('bad-inputs', item.name);
    }
    for (const item of items) {
      if (![...item.specified_by, ...item.targets].every((rel) => item.inputs.includes(rel))) throw new Stop('unknown-file', item.name);
    }
    const version = `${manifest.version}+${digests.get(binding.provider)}+${site.runner}`;
    const uses = new Set(manifest.tools.map((tool) => tool.name));
    for (const item of items) {
      if (found.has(item.name)) throw new Stop('duplicate-obligation', item.name);
      const given = item.inputs.map((rel) => ({ path: rel, identity: identities.get(rel) }));
      found.set(item.name, {
        preimage: {
          obligation: identityOf({ binding: binding.name, name: item.name }),
          kind: 'check',
          inputs: {
            specified_by: sortedSet(given.filter((file) => item.specified_by.includes(file.path)).map((file) => file.identity)),
            targets: sortedSet(given.filter((file) => item.targets.includes(file.path)).map((file) => file.identity)),
            closure: sortedSet(given.map((file) => identityOf({ path: file.path, identity: file.identity }))),
            // Only the site's tools the provider's manifest names, in the site's order.
            tools: site.tools.filter((tool) => uses.has(tool.name)).map((tool) => ({ name: tool.name, digest: tool.digest })),
            config: identityOf(item.config),
            expect: item.expect,
          },
          provider: { name: manifest.name, version, protocol: manifest.protocol },
        },
      });
      listed.push({ binding: binding.name, name: item.name });
    }
    if (session !== null) {
      // What the checks on this session start from (step 11): the request as sent, the
      // obligations as enumerated, the provider as measured, the site's platform as given.
      // A check's inputs are F, its own obligation's `inputs` taken from request.files,
      // never every file the binding claims.
      const named = site.tools.filter((tool) => uses.has(tool.name));
      Object.assign(session, {
        request,
        obligations: items,
        provider: { name: manifest.name, version, protocol: manifest.protocol },
        code: digests.get(binding.provider),
        tools: named.map((tool) => ({ name: tool.name, version: tool.version, digest: tool.digest })),
        platform: site.platform,
        deadline_ms: site.deadline_ms,
        offers_check: manifest.capabilities.some((entry) => entry.capability === 'obligation.check'),
      });
    }
    unchecked = unchecked.concat(rejected.map((entry) => entry.name));
  }
  listed.sort((a, b) => compareUnits(a.binding, b.binding) || compareUnits(a.name, b.name));
  return { found, listed, unchecked: sortedSet(unchecked) };
}

// Step 7. Intents.

function isPerson(value) {
  return isString(own(value, 'id'));
}

function intentHasShape(it) {
  return isObject(it) && isString(own(it, 'name')) && it.name !== '' && isString(own(it, 'text'))
    && isPerson(own(it, 'owner')) && (!Object.hasOwn(it, 'worker') || isPerson(it.worker))
    && Array.isArray(own(it, 'children')) && it.children.every((child) => isString(child) && child !== '')
    && Array.isArray(own(it, 'criteria')) && it.criteria.every((criterion) => isObject(criterion)
      && isString(own(criterion, 'id')) && criterion.id !== '' && isString(own(criterion, 'statement'))
      && isString(own(criterion, 'gate')) && Array.isArray(own(criterion, 'links'))
      && criterion.links.every((link) => isString(own(link, 'binding')) && isString(own(link, 'obligation'))));
}

async function intentsOf(root, site, bindings, listed, claims) {
  const answers = [];
  for (const binding of bindings.filter((b) => b.capabilities.includes('intent.index')).sort(byName)) {
    const { body } = await ask(root, site, binding, 'intent.index', { binding: binding.name, files: claims.get(binding.name), obligations: listed });
    const items = own(body, 'intents');
    const rejected = Object.hasOwn(body, 'rejected') ? body.rejected : [];
    if (!Array.isArray(items) || !Array.isArray(rejected) || !rejected.every((entry) => isString(own(entry, 'path')) && entry.path !== '')
      || !items.every(intentHasShape)) {
      throw new Stop('bad-answer', `binding ${binding.name}: the answer does not have the shape the contract gives`);
    }
    if (rejected.length > 0) throw new Stop('intent-unreadable', rejected.map((entry) => entry.path).join(', '));
    answers.push(...items);
  }
  const unread = answers.some((it) => it.criteria.some((criterion) => Object.hasOwn(criterion, 'limit_days') || Object.hasOwn(criterion, 'not_applicable')
    || criterion.links.some((link) => Object.hasOwn(link, 'varying'))));
  for (const it of answers) {
    if (new Set(it.criteria.map((criterion) => criterion.id)).size !== it.criteria.length) throw new Stop('duplicate-criterion', it.name);
  }
  const known = new Set(listed.map((o) => JSON.stringify([o.binding, o.name])));
  for (const it of answers) {
    for (const criterion of it.criteria) {
      for (const link of criterion.links) {
        if (!known.has(JSON.stringify([link.binding, link.obligation]))) {
          throw new Stop('unknown-link', `${it.name} criterion ${criterion.id}: ${link.binding}/${link.obligation}`);
        }
      }
    }
  }
  const intents = new Map();
  for (const it of answers) {
    if (intents.has(it.name)) throw new Stop('duplicate-intent', it.name);
    const criteria = {};
    for (const criterion of it.criteria) {
      put(criteria, criterion.id, { words: criterion.statement, gate: criterion.gate, checked_by: sortedSet(criterion.links.map((link) => link.obligation)) });
    }
    intents.set(it.name, {
      owner: it.owner.id, worker: Object.hasOwn(it, 'worker') ? it.worker.id : '', children: sortedSet(it.children), words: it.text, criteria,
    });
  }
  const parent = new Map();
  for (const [name, it] of intents) {
    for (const child of it.children) {
      if (parent.has(child)) throw new Stop('two-parents', child);
      parent.set(child, name);
    }
  }
  for (const name of intents.keys()) {
    const seen = new Set([name]);
    let here = name;
    while (parent.has(here)) {
      here = parent.get(here);
      if (seen.has(here)) throw new Stop('intent-cycle', name);
      seen.add(here);
    }
  }
  return { intents, parent, unread };
}

// Step 8. Ledgers.

// 'present', 'absent' (nothing there, every step before it entered, no link to
// nothing), or 'unreadable' (a link to nothing at any step, a folder that cannot be
// entered, or any other error). Only a clean absence is read as no entries.
function ledgerState(root, rel) {
  for (const step of stepsOf(root, rel)) {
    try {
      fs.statSync(step);
    } catch (error) {
      if (error.code !== 'ENOENT') return 'unreadable';
      try {
        fs.lstatSync(step);
      } catch (inner) {
        return inner.code === 'ENOENT' ? 'absent' : 'unreadable';
      }
      return 'unreadable'; // a link to nothing
    }
  }
  return 'present';
}

function fileId(where) {
  try {
    const status = fs.statSync(where, { bigint: true });
    return `${status.dev}:${status.ino}`;
  } catch (error) {
    return null;
  }
}

function isRegular(where) {
  try {
    return fs.statSync(where).isFile();
  } catch (error) {
    return null;
  }
}

function readLedger(root, rel) {
  const state = ledgerState(root, rel);
  if (state === 'unreadable') throw new Stop('unreadable-file', `${rel}: a link to nothing or a folder that cannot be entered on the way`);
  if (state === 'absent') return { entries: [], torn: false, absent: true };
  const where = path.join(root, rel);
  const regular = isRegular(where);
  if (regular === null) throw new Stop('unreadable-file', rel);
  if (!regular) throw new Stop('corrupt-ledger', `${rel} is not a file`);
  let bytes;
  try {
    bytes = fs.readFileSync(where);
  } catch (error) {
    throw new Stop('unreadable-file', `${rel}: ${error.code || error.message}`);
  }
  const read = ledgerFormat.readLedger(bytes);
  if (read.refused !== undefined) throw new Stop('corrupt-ledger', `${rel}, line ${read.at}`);
  return { entries: read.entries, torn: read.torn, absent: false };
}

function ownerReachedWithoutLink(root, rel) {
  for (const step of stepsOf(root, rel)) {
    let status;
    try {
      status = fs.lstatSync(step);
    } catch (error) {
      return true; // cannot be looked at; reading it then finds it absent or unreadable
    }
    if (status.isSymbolicLink()) return false;
  }
  return true;
}

function entriesOf(root, ownerRel, ledgers) {
  if (!ownerReachedWithoutLink(root, ownerRel)) throw new Stop('owner-ledger-link', ownerRel);
  const ownerState = ledgerState(root, ownerRel);
  if (ownerState === 'unreadable') throw new Stop('unreadable-file', `${ownerRel}: a folder on its way cannot be entered`);
  if (ownerState === 'present' && isRegular(path.join(root, ownerRel)) !== true) throw new Stop('owner-ledger-link', ownerRel);
  const sources = ownerState === 'present' ? [{ rel: ownerRel, owner: true }] : [];
  const seen = ownerState === 'present' ? [fileId(path.join(root, ownerRel))] : [];
  // A file already read, the owner's ledger included, however its path is spelt, is not read again.
  for (const rel of ledgers) {
    const present = ledgerState(root, rel) === 'present';
    const id = present ? fileId(path.join(root, rel)) : null;
    if (present && id !== null && seen.includes(id)) continue;
    sources.push({ rel, owner: false });
    if (present && id !== null) seen.push(id);
  }
  let entries = [];
  let torn = false;
  const absent = [];
  for (const source of sources) {
    const read = readLedger(root, source.rel);
    if (read.absent && !source.owner) absent.push(source.rel);
    // Acts are read only from the owner's ledger, and nothing else is read from it.
    entries = entries.concat(read.entries.filter((entry) => (entry.kind === 'act') === source.owner));
    torn = torn || read.torn;
  }
  return { entries, note: { entries: entries.length, torn }, absent };
}

// Step 11. Coverage: where each intent tree's hard gates sit.
function coverageOf(intents, parent, floor) {
  const parentOf = (name) => (parent.has(name) ? parent.get(name) : null);
  const rootOf = (name) => {
    let here = name;
    while (parentOf(here) !== null) here = parentOf(here);
    return here;
  };
  const ownHard = new Map();
  for (const [name, it] of intents) {
    ownHard.set(name, Object.values(it.criteria).filter((criterion) => criterion.gate !== 'soft' && criterion.gate !== 'deferred').length);
  }
  const below = (name) => {
    const found = new Set();
    const todo = [name];
    while (todo.length > 0) {
      const here = todo.pop();
      if (found.has(here) || !intents.has(here)) continue;
      found.add(here);
      todo.push(...intents.get(here).children);
    }
    return found;
  };
  const subtreeHard = (name) => [...below(name)].reduce((sum, here) => sum + ownHard.get(here), 0);
  const out = {};
  for (const name of intents.keys()) {
    const root = rootOf(name);
    const subtree = subtreeHard(name);
    put(out, name, {
      own_hard: ownHard.get(name), subtree_hard: subtree, root, tree_hard: subtreeHard(root), floor, floor_met_only_over_tree: name !== root && subtree < floor,
    });
  }
  const thinnest = {};
  for (const name of [...intents.keys()].sort(compareUnits)) {
    const root = out[name].root;
    const best = Object.hasOwn(thinnest, root) ? thinnest[root] : null;
    if (best === null || out[name].own_hard < out[best].own_hard) put(thinnest, root, name);
  }
  return { intents: out, thinnest };
}

// What this kernel's `scenario` command answers for the scenario, as its last result:
// the scenario is written out and read back as that command reads its input.
function ownReport(judged) {
  const read = strictJson.read(JSON.stringify(judged));
  if (read.refused !== undefined) throw new Error(`the judged scenario cannot be read back: ${read.refused}`);
  const { results } = runScenario(plain(read.value));
  return results[results.length - 1];
}

function objectOf(map) {
  const out = {};
  for (const [key, value] of map) put(out, key, value);
  return out;
}

// Steps 2 to 10, after step 1 has given the code digests: what was read, asked and
// judged, from which the status command makes its output and the run command its plan.
// `kept` as in obligationsOf: the status command gives none, and every session ends
// after its answer.
async function snapshotOf(asked, digests, kept = null) {
  const root = asked.root;
  const site = asked.site;
  // Step 2.
  const how = reach(root, asked.project);
  if (how !== 'file') throw new Stop('bad-project', 'the project file is not a regular file reached without a link');
  let raw;
  try {
    raw = fs.readFileSync(path.join(root, asked.project));
  } catch (error) {
    throw new Stop('unreadable-file', `${asked.project}: ${error.code || error.message}`);
  }
  const bindings = readProject(raw);
  // Step 3.
  const notServed = [];
  for (const binding of bindings) {
    for (const capability of sortedSet(binding.capabilities)) {
      if (!SERVED.includes(capability)) notServed.push({ binding: binding.name, capability });
    }
  }
  notServed.sort((a, b) => compareUnits(a.binding, b.binding) || compareUnits(a.capability, b.capability));
  const served = bindings.filter((binding) => binding.capabilities.some((capability) => SERVED.includes(capability)));
  for (const binding of served) {
    if (!Object.hasOwn(site.providers, binding.provider)) throw new Stop('no-provider', binding.provider);
  }
  // Step 4.
  const claims = new Map();
  if (served.length > 0) {
    const files = regularFiles(root);
    for (const binding of served) claims.set(binding.name, claimedFiles(root, files, binding.match));
  }
  for (const capability of SERVED) {
    const owners = new Map();
    for (const binding of served.filter((b) => b.capabilities.includes(capability))) {
      for (const file of claims.get(binding.name)) {
        if (owners.has(file.path)) throw new Stop('overlapping-bindings', `${file.path} is claimed by ${owners.get(file.path)} and ${binding.name} for ${capability}`);
        owners.set(file.path, binding.name);
      }
    }
  }
  // Steps 5 to 7.
  const obligations = await obligationsOf(root, site, digests, bindings, claims, kept);
  const { intents, parent, unread } = await intentsOf(root, site, bindings, obligations.listed, claims);
  // Step 8.
  const read = entriesOf(root, asked.owner_ledger, asked.ledgers);
  // Step 9.
  const policy = {
    min_hard_gates: Math.max(asked.policy.min_hard_gates, 1),
    required: asked.policy.required,
    trusted_writers: [],
    floors: asked.policy.floors,
    attestors: {},
    makes: [],
  };
  // Step 10.
  const judged = {
    kind: 'status',
    name: 'this-project',
    self: { writer: site.writer, platform: `${site.platform.os}/${site.platform.arch}` },
    policy,
    obligations: objectOf(obligations.found),
    intents: objectOf(intents),
    steps: [...read.entries.map((entry) => ({ do: { append: { kind: entry.kind, body: entry.body } } })), NOTHING],
  };
  const report = ownReport(judged);
  return { judged, report, policy, obligations, intents, parent, unread, read, notServed };
}

// The output, from a snapshot: doubts, coverage (step 11) and the status as stated.
function reportOf(asked, { judged, report, policy, obligations, intents, parent, unread, read, notServed }) {
  const doubts = [];
  if (asked.policy.not_applied.length > 0) doubts.push(DOUBTS.policy);
  if (policy.required.some((name) => intents.has(name) && intents.get(name).children.length > 0)) doubts.push(DOUBTS.children);
  if (obligations.unchecked.length > 0) doubts.push(DOUBTS.unchecked);
  if (unread) doubts.push(DOUBTS.unread);
  if (read.note.torn) doubts.push(DOUBTS.torn);
  if (read.absent.length > 0) doubts.push(DOUBTS.absent);
  const status = report.project.status;
  return {
    judged,
    report,
    coverage: coverageOf(intents, parent, policy.min_hard_gates), // step 11
    policy_source: asked.policy_source,
    ledger: read.note,
    not_served: notServed,
    not_checkable: obligations.unchecked,
    policy_not_applied: asked.policy.not_applied,
    project_doubts: doubts,
    project_status: doubts.length > 0 && (status === 'passed' || status === 'nothing-required') ? 'unknown' : status,
  };
}

async function judge(asked) {
  const digests = checkInput(asked); // step 1
  return reportOf(asked, await snapshotOf(asked, digests));
}

// The command: bytes of standard input to the one object it prints.
async function projectStatus(bytes) {
  try {
    return await judge(readInput(bytes));
  } catch (error) {
    if (error instanceof Stop) return { refused: error.reason, detail: error.detail };
    throw error;
  }
}

module.exports = {
  projectStatus, readInput, isRelative, isPattern, segmentMatches, readProject, coverageOf, Stop,
  // Reused by the run command's checks of its own input (project-run.js).
  checkInput, isDirectory, fileId, stepsOf,
  // Reused by its plan: the same steps 2 to 10 and the same output.
  snapshotOf, reportOf, endSession,
};
