const assert = require('node:assert/strict');
const flow = require('../static/flow.js');

assert.equal(flow.normalizeVisibleStep(4), 5);
assert.equal(flow.normalizeVisibleStep(7), 6);
assert.equal(flow.resolveProjectVisibleStep({ current_step: 7, audio_confirmed: false }), 6);
assert.equal(flow.resolveProjectVisibleStep({ current_step: 7, audio_confirmed: true }), 8);
assert.deepEqual(flow.VISIBLE_FLOW_STEPS, [1, 2, 3, 5, 6, 8]);

const confirmedImages = {
  1: 'completed',
  2: 'completed',
  3: 'completed',
  4: 'completed',
  5: 'pending',
  6: 'pending',
  7: 'pending',
  8: 'pending'
};
assert.equal(flow.getVisibleStepState(3, confirmedImages), 'completed');
assert.equal(flow.isVisibleStepUnlocked(5, confirmedImages, 4), true);

const generatedOnly = { ...confirmedImages, 4: 'pending' };
assert.equal(flow.getVisibleStepState(3, generatedOnly), 'pending');

const audioGenerated = {
  ...confirmedImages,
  5: 'completed',
  6: 'completed',
  7: 'in_progress'
};
assert.equal(
  flow.getVisibleStepState(6, audioGenerated, { audioConfirmed: false }),
  'in_progress'
);
assert.equal(
  flow.isVisibleStepUnlocked(8, audioGenerated, 7, { audioConfirmed: false }),
  false
);

const audioConfirmed = { ...audioGenerated, 7: 'completed' };
assert.equal(
  flow.getVisibleStepState(6, audioConfirmed, { audioConfirmed: true }),
  'completed'
);
assert.equal(
  flow.isVisibleStepUnlocked(8, audioConfirmed, 7, { audioConfirmed: true }),
  true
);
assert.equal(
  flow.isVisibleStepUnlocked(8, audioConfirmed, 7, { audioConfirmed: false }),
  false
);

assert.equal(
  flow.calculateVisibleProgress(audioConfirmed, { audioConfirmed: true }),
  83
);

console.log('visible flow checks passed');
