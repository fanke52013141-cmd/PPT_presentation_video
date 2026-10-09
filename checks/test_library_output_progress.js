const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const source = fs.readFileSync(process.argv[2] || path.join(__dirname, '../static/courses.js'), 'utf8');
const begin = source.indexOf('  function projectProgress(project) {');
const end = source.indexOf('  function renderNewVideoCard()', begin);
const scope = {
  calculateVisibleProgress: (status) => status['8'] === 'completed' ? 100 : 0,
  projectFlowContext: () => ({}),
};
vm.runInNewContext(source.slice(begin, end), scope);
assert.equal(scope.projectProgress({ latest_output_type: 'video', latest_output_at: '2026-10-09T20:54:14', current_step: 8 }), 100,
  'actual course-tree brief without step_status must show full progress after video export');
assert.equal(scope.projectProgress({ latest_output_type: 'pptx', latest_output_at: '2026-10-09T20:54:14' }), 100);
assert.equal(scope.projectProgress({ current_step: 8, step_status: {} }), 0,
  'merely navigating to output cannot count as a successful export');
assert.equal(scope.projectProgress({ step_status: { 8: 'completed' } }), 100);
console.log('library output progress checks passed');
