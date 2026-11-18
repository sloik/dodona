'use strict';
// The values the conformance tables allow. A step carrying any other value changes nothing.

module.exports = {
  GATES: ['hard', 'soft', 'deferred'],
  CHECKS: ['unknown', 'passed', 'failed', 'conflict'],
  VERDICTS: ['passed', 'failed'],
  RESULTS: ['agreed', 'refused'],
  SOURCES: ['declared', 'attested'],
  BACKENDS: ['up', 'down'],
};
