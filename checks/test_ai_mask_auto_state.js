const assert = require('node:assert/strict');
const { createAiMaskAutoState } = require('../static/ai_mask_auto_state.js');

const scheduled = [];
const cancelled = [];
const controller = createAiMaskAutoState({
  retryDelays: [1000, 3000],
  schedule(callback, delay) {
    const timer = { callback, delay };
    scheduled.push(timer);
    return timer;
  },
  cancel(timer) {
    cancelled.push(timer);
  },
});

assert.equal(controller.canStart('project-1'), true);
controller.begin('project-1', 'checking');
assert.equal(controller.canStart('project-1'), false);

let retried = 0;
assert.equal(controller.scheduleRetry('project-1', () => { retried += 1; }), 1000);
assert.equal(controller.get('project-1').status, 'retry_wait');
assert.equal(controller.get('project-1').retries, 1);
scheduled.shift().callback();
assert.equal(retried, 1);
assert.equal(controller.get('project-1').status, 'idle');

controller.begin('project-1');
assert.equal(controller.scheduleRetry('project-1', () => { retried += 1; }), 3000);
scheduled.shift().callback();
controller.begin('project-1');
assert.equal(controller.scheduleRetry('project-1', () => { retried += 1; }), null);
assert.equal(controller.get('project-1').status, 'failed');

controller.reset('project-1');
controller.waitForOneClick('project-1', () => { retried += 1; });
assert.equal(controller.get('project-1').status, 'waiting_one_click');
assert.equal(controller.get('project-1').retries, 0);
controller.reset();
assert.ok(cancelled.length >= 1);

console.log('AI Mask automatic state checks passed');
