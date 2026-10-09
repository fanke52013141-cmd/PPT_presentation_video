const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const filename = process.argv[2] || path.join(__dirname, '../static/flow.js');
for (const light of [false, true]) {
  const scope = { module: { exports: {} } };
  if (light) scope.PPTStudioDistribution = { features: { digital_human: false, handwritten_annotations: false } };
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), scope);
  const flow = scope.module.exports;
  const rendered = { 1: 'completed', 2: 'completed', 3: 'completed', 4: 'completed',
    5: 'pending', 6: 'completed', 7: 'completed', 8: 'completed' };
  assert.equal(flow.calculateVisibleProgress(rendered, { audioConfirmed: false }), 100,
    'published static video must finish progress even without automatic Masks');
  assert.ok(flow.calculateVisibleProgress({ ...rendered, 8: 'in_progress' }, { audioConfirmed: true }) < 100,
    'entering output or rendering does not mean it succeeded');
  assert.ok(flow.calculateVisibleProgress({ ...rendered, 8: 'pending' }, { audioConfirmed: true }) < 100,
    'invalidated output must stop showing full progress');
  assert.ok(flow.calculateVisibleProgress({ ...rendered, 5: 'pending_reconfirmation' }, { audioConfirmed: true }) < 100,
    'legacy completed output must not hide pending input reconfirmation');
}
console.log('output completion progress checks passed');
