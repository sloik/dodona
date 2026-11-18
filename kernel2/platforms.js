'use strict';
// Results on more than one platform (MODEL.md section 4, conformance/README.md, platforms scenarios).
// `recorded` maps a key to a map from platform to the set of verdicts recorded
// there (one verdict, or both if the platform has conflicting records).

const vocabulary = require('./vocabulary');

function platformMap(recorded, key) {
  return recorded.get(key) || new Map();
}

// The verdicts seen for a key, over all platforms.
function verdictsOf(recorded, key) {
  const seen = new Set();
  for (const verdicts of platformMap(recorded, key).values()) for (const verdict of verdicts) seen.add(verdict);
  return seen;
}

// True if the key has both verdicts recorded, on one platform or several.
function keyDiffers(recorded, key) {
  return verdictsOf(recorded, key).size > 1;
}

// How many platforms have this verdict recorded for the key.
function platformsWith(recorded, key, verdict) {
  return [...platformMap(recorded, key).values()].filter((verdicts) => verdicts.has(verdict)).length;
}

// True if at least two platforms have a verdict for the key and all are the same.
function keyAgrees(recorded, key) {
  return !keyDiffers(recorded, key) && platformMap(recorded, key).size >= 2;
}

// The claim of platform independence is verified when some key has the same
// verdict on at least two platforms and no key has different verdicts anywhere.
function claimVerified(recorded, keys) {
  const sameOnTwo = keys.some((key) => platformsWith(recorded, key, 'passed') >= 2 || platformsWith(recorded, key, 'failed') >= 2);
  return sameOnTwo && !keys.some((key) => keyDiffers(recorded, key));
}

// `differs`, `agrees` or `unknown`.
function reproducibility(recorded, key) {
  if (keyDiffers(recorded, key)) return 'differs';
  if (keyAgrees(recorded, key)) return 'agrees';
  return 'unknown';
}

function compareText(a, b) {
  return a < b ? -1 : a > b ? 1 : 0;
}

function judge(scenario, recorded) {
  const providerClaims = scenario.provider_claims !== false;
  const mayStandIn = scenario.stand_in_allowed && providerClaims && claimVerified(recorded, scenario.keys);
  const status = {};
  const reproduced = {};
  const stoodIn = [];
  for (const key of scenario.keys) {
    status[key] = {};
    reproduced[key] = reproducibility(recorded, key);
    for (const platform of scenario.platforms) {
      const own = platformMap(recorded, key).get(platform);
      const others = [...platformMap(recorded, key).entries()].filter(([other]) => other !== platform);
      if (own !== undefined) {
        status[key][platform] = own.size > 1 ? 'conflict' : [...own][0];
      } else if (mayStandIn && others.length > 0) {
        status[key][platform] = [...others[0][1]][0];
        stoodIn.push([key, platform]);
      } else {
        status[key][platform] = 'unknown';
      }
    }
  }
  stoodIn.sort((a, b) => compareText(a[0], b[0]) || compareText(a[1], b[1]));
  return { status, stood_in: stoodIn, reproducibility: reproduced };
}

function runScenario(scenario) {
  const recorded = new Map();
  const results = [];
  for (const { do: step } of scenario.steps) {
    const valid = step.record && scenario.keys.includes(step.record.key) && scenario.platforms.includes(step.record.platform)
      && vocabulary.VERDICTS.includes(step.record.verdict);
    if (valid) {
      const { key, platform, verdict } = step.record;
      if (!recorded.has(key)) recorded.set(key, new Map());
      if (!recorded.get(key).has(platform)) recorded.get(key).set(platform, new Set());
      recorded.get(key).get(platform).add(verdict);
    }
    results.push(judge(scenario, recorded));
  }
  return results;
}

module.exports = { claimVerified, reproducibility, judge, runScenario };
