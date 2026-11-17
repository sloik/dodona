'use strict';
// Results on more than one platform (MODEL.md section 4, conformance/README.md, platforms scenarios).
// `verdicts` maps a key to a map from platform to verdict.

function verdictsOf(verdicts, key) {
  return Object.values(verdicts[key] || {});
}

// True if two platforms differ for this key.
function platformsDiffer(verdicts, key) {
  return verdictsOf(verdicts, key).includes('passed') && verdictsOf(verdicts, key).includes('failed');
}

// True if two platforms agree for this key.
function platformsAgree(verdicts, key) {
  const seen = verdictsOf(verdicts, key);
  return seen.filter((verdict) => verdict === 'passed').length >= 2 || seen.filter((verdict) => verdict === 'failed').length >= 2;
}

// The claim of platform independence is verified when some key has the same
// verdict on two platforms and no key has different verdicts on two platforms.
function claimVerified(verdicts, keys) {
  return keys.some((key) => platformsAgree(verdicts, key)) && !keys.some((key) => platformsDiffer(verdicts, key));
}

// `failed` if two platforms differ, `passed` if two agree, otherwise `unknown`.
function reproducibility(verdicts, key) {
  if (platformsDiffer(verdicts, key)) return 'failed';
  if (platformsAgree(verdicts, key)) return 'passed';
  return 'unknown';
}

function judge(scenario, verdicts) {
  const verified = claimVerified(verdicts, scenario.keys);
  const status = {};
  const reproduced = {};
  const stoodIn = [];
  for (const key of scenario.keys) {
    status[key] = {};
    reproduced[key] = reproducibility(verdicts, key);
    for (const platform of scenario.platforms) {
      const own = (verdicts[key] || {})[platform];
      const others = scenario.platforms.filter((other) => other !== platform && (verdicts[key] || {})[other] !== undefined);
      if (own !== undefined) {
        status[key][platform] = own;
      } else if (scenario.stand_in_allowed && verified && others.length > 0) {
        status[key][platform] = verdicts[key][others[0]];
        stoodIn.push([key, platform]);
      } else {
        status[key][platform] = 'unknown';
      }
    }
  }
  stoodIn.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0));
  return { status, stood_in: stoodIn, reproducibility: reproduced };
}

function runScenario(scenario) {
  const verdicts = {};
  const results = [];
  for (const { do: step } of scenario.steps) {
    if (step.record) {
      const { key, platform, verdict } = step.record;
      if (!verdicts[key]) verdicts[key] = {};
      verdicts[key][platform] = verdict;
    }
    results.push(judge(scenario, verdicts));
  }
  return results;
}

module.exports = { claimVerified, reproducibility, judge, runScenario };
