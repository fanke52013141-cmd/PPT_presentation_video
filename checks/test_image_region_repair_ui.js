const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const nodes = new Map();
const img = { naturalWidth: 1920, naturalHeight: 1080, style: {},
  getBoundingClientRect: () => ({ left: 0, top: 0, width: 400, height: 400 }),
  setPointerCapture: () => {} };
const box = { querySelector: () => img, appendChild: element => nodes.set(element.id, element),
  getBoundingClientRect: () => ({ left: 0, top: 0 }) };
nodes.set('step3-preview-box', box);
nodes.set('step3-repair-only-region', { checked: false });
nodes.set('step3-repair-control', { style: {} });
const document = { querySelector: () => null, getElementById: id => nodes.get(id) || null,
  createElement: () => ({ style: {}, remove() { nodes.delete(this.id); } }) };
const context = vm.createContext({ document, window: {}, showToast: () => {} });
vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/images.js'), 'utf8'), context);
context.bindStep3CandidateRepair({ image_sha256: 'a'.repeat(64), candidate_sha256: 'b'.repeat(64) });
const input = nodes.get('step3-repair-only-region');
input.checked = true;
input.onchange();
const pointer = (x, y) => ({ clientX: x, clientY: y, pointerId: 1, pointerType: 'mouse', button: 0, preventDefault() {} });
img.onpointerdown(pointer(100, 150));
img.onpointermove(pointer(200, 200));
img.onpointerup();
const payload = JSON.parse(JSON.stringify(context.step3RegionalRepairPayload()));
assert.deepStrictEqual(payload.regions, [[480, 300, 960, 540]]);
assert.strictEqual(payload.expected_candidate_sha256, 'b'.repeat(64));
img.onpointerdown(pointer(100, 150));
img.onpointercancel();
assert.deepStrictEqual(JSON.parse(JSON.stringify(context.step3RegionalRepairPayload())), {});
context.resetStep3CandidateRepair();
assert.strictEqual(input.checked, false);
assert.strictEqual(nodes.get('step3-repair-control').style.display, 'none');
img.naturalWidth = 1080; img.naturalHeight = 1920;
context.bindStep3CandidateRepair({ image_sha256: 'a'.repeat(64), candidate_sha256: 'b'.repeat(64) });
input.checked = true; input.onchange();
img.onpointerdown(pointer(150, 100)); img.onpointermove(pointer(200, 200)); img.onpointerup();
assert.deepStrictEqual(JSON.parse(JSON.stringify(context.step3RegionalRepairPayload())).regions, [[300, 480, 540, 960]]);
console.log('regional image repair UI coordinates and reset passed');
