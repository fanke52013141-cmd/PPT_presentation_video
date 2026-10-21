// 勾画编辑恢复行为回归:撤销/重做必须产生服务端操作(自比较修复)、
// 本地条目撤销撤下 add、延迟提交的文字候选、逐页确认调用、
// 在飞竞态后的 local id 重映射。真实 workspace/editor 源码在 Node VM 中驱动。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const sandbox = createSandbox();
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(root, 'static', 'annotation_playback.js'), 'utf8'), sandbox);
vm.runInContext(fs.readFileSync(path.join(root, 'static', 'annotations_core.js'), 'utf8'), sandbox);
vm.runInContext(fs.readFileSync(path.join(root, 'static', 'annotations_workspace.js'), 'utf8'), sandbox);
vm.runInContext(fs.readFileSync(path.join(root, 'static', 'annotations_editor.js'), 'utf8'), sandbox);

const core = sandbox.AnnotationsCore;
const WS = sandbox.window.ANNOTATIONS_WS;
const run = expr => vm.runInContext(expr, sandbox);
const await0 = () => new Promise(resolve => setImmediate(resolve));

(async () => {
const REGION_TARGET = {
  kind: 'region', layout_revision: null, token_ids: [],
  polygons: [[[100, 200], [400, 200], [400, 260], [100, 260]]],
  quote: null, granularity: 'region', mask_group_ids: [],
};

function setupProject(projectId, slideId, revision = 0) {
  run(`(() => {
    resetAnnotationsProjectState();
    ANNOTATIONS_WS.projectId = ${JSON.stringify(projectId)};
    ANNOTATIONS_WS.page = {
      slide_id: ${JSON.stringify(slideId)}, revision: ${revision}, items: [],
      narration: { beats: [{ beat_id: 'b1', spoken_text: '这是重点内容' }] },
      imageHash: 'a'.repeat(64),
    };
  })()`);
}

function regionItem(id, overrides = {}) {
  return {
    annotation_id: id,
    target: JSON.parse(JSON.stringify(REGION_TARGET)),
    anchor: null,
    style: { type: 'ellipse', color: '#F46A38', opacity: 0.85, width: 5, padding: 8, seed: 1 },
    timing: {
      trigger_mode: 'manual', offset_sec: 0, manual_start_sec: 0,
      draw_duration_sec: 0.6, hold_mode: 'slide_end', exit_duration_sec: 0.15,
    },
    status: { content: 'draft', spatial: 'valid', temporal: 'awaiting_audio' },
    protection: { source: 'manual', modified_fields: ['timing'], locked: false },
    ...overrides,
  };
}

// ------------------------------------------------------------ 撤销/重做

// 撤销删除服务端条目:必须重新入队 add(此前数组与自身比较,永远 0 操作)
{
  setupProject('pU', 'slide_001');
  WS.page.items = [regionItem('ann_001')];
  run('pushAnnotationHistory()');
  WS.page.items = []; // 模拟删除后
  run('undoAnnotationEdit()');
  assert.equal(WS.pendingOps.length, 1, '撤销必须重新入队操作');
  assert.equal(WS.pendingOps[0].op, 'add');
  assert.ok(WS.pendingOps[0].item.annotation_id.startsWith('local_'), '补偿 add 必须使用可重映射的本地 id');
  assert.equal(WS.page.items.length, 1);
  console.log('undo of delete requeues add ok');

  run('redoAnnotationEdit()');
  assert.equal(WS.pendingOps.length, 0, '重做撤回尚未提交的补偿 add');
  assert.equal(WS.page.items.length, 0);
  console.log('redo of undo requeues delete ok');
}

// 撤销刚画完(未保存)的本地条目:撤下排队中的 add,而不是发送 delete
{
  setupProject('pL', 'slide_001');
  run('pushAnnotationHistory()');
  const stored = { ...regionItem(''), annotation_id: 'local_42_1' };
  WS.page.items.push(stored);
  const addOp = core.buildAddOperation(stored);
  assert.equal(addOp.__local_id, 'local_42_1', '本地条目的 add 必须携带 __local_id');
  WS.pendingOps.push(addOp);
  run('undoAnnotationEdit()');
  assert.equal(WS.page.items.length, 0, '撤销移除本地条目');
  assert.equal(WS.pendingOps.length, 0, '排队的 add 必须被撤下,不得发送悬空 delete');
  console.log('undo of unsaved local item cancels pending add ok');
}

// 在飞竞态:保存请求在途时撤销本地条目 → delete 先入队,
// flush 成功后由 local id 重映射改写为服务端 id,下一轮 flush 删除服务端条目
{
  setupProject('pR', 'slide_001');
  let releasePatch;
  sandbox.__api.patch = (_url, _payload) => new Promise(resolve => { releasePatch = resolve; });
  const stored = { ...regionItem(''), annotation_id: 'local_7_1' };
  const targetFingerprint = JSON.stringify(stored.target);
  WS.page.items.push(stored);
  WS.pendingOps.push(core.buildAddOperation(stored));
  const flushPromise = run('flushAnnotationsSave()').catch(() => 'should-not-reject');
  // 在飞期间撤销:delete local_7_1 排队(add 已不在队列里)
  run('pushAnnotationHistory()');
  WS.page.items = [];
  WS.pendingOps.push(core.buildDeleteOperation('local_7_1'));
  sandbox.__api.patch = async (_url, payload) => {
    assert.equal(payload.operations[0].annotation_id, 'ann_005');
    assert.equal(payload.expected_revision, 2);
    return { revision: 3, items: [] };
  };
  releasePatch({ revision: 2, items: [{ annotation_id: 'ann_005', target: stored.target }] });
  await flushPromise;
  assert.equal(WS.pendingOps.length, 0, '保存屏障必须排空重映射后的删除');
  assert.equal(WS.page.items.length, 0);
  console.log('in-flight local id remap ok');
}

// ------------------------------------------------------------ 延迟提交的文字候选

// 无锚点时:本地草稿不入队;选中讲稿短语后随 add 一起提交
{
  setupProject('pC', 'slide_001');
  WS.candidates = [{
    token_id: 'tok_0001_0001', text: '重点',
    polygon: [[100, 200], [140, 200], [140, 240], [100, 240]],
    granularity: 'char', layout_revision: 2,
  }];
  WS.layoutRevision = 2;
  run('addAnnotationFromCandidate("tok_0001_0001")');
  assert.equal(WS.page.items.length, 1);
  assert.equal(WS.page.items[0].__deferredAdd, true, '无锚点文字候选必须延迟提交');
  assert.equal(WS.pendingOps.length, 0, '延迟条目不得先发 add(服务端要求锚点)');
  assert.equal(WS.selectedAnnotationId, WS.page.items[0].annotation_id, '延迟条目应被选中以接收锚点');

  const anchor = {
    beat_id: 'b1', offset_unit: 'unicode_codepoint', range: [2, 4],
    quote: '重点', occurrence: 1, context_before: '这是', context_after: '内容',
  };
  run(`annotationNarrationAnchorPicked(${JSON.stringify(anchor)})`);
  assert.equal(WS.pendingOps.length, 1, '锚点就位后必须入队 add');
  assert.equal(WS.pendingOps[0].op, 'add');
  assert.ok(WS.pendingOps[0].__local_id, '延迟条目的 add 必须携带 __local_id');
  assert.ok(WS.pendingOps[0].item.anchor, 'add 必须携带锚点(服务端对文字目标强制要求)');
  assert.ok(!WS.page.items[0].__deferredAdd, '入队后延迟标记必须清除');
  console.log('deferred text candidate commits with anchor ok');
}

// ------------------------------------------------------------ 逐页确认

// 常规确认:POST /confirm、状态本地落账、revision 更新
{
  setupProject('pF', 'slide_001', 3);
  WS.page.items = [regionItem('ann_001')];
  sandbox.__api.post = async (url, payload) => {
    assert.ok(url.endsWith('/annotations/slides/slide_001/confirm'), '确认必须调用 confirm 端点');
    assert.equal(payload.expected_revision, 3);
    assert.equal(payload.accepted_review.length, 0);
    return { slide_id: 'slide_001', revision: 4, confirmed: 1, timeline_built: true, timeline_error: '' };
  };
  await run('confirmAnnotationPage()');
  assert.equal(WS.page.revision, 4, '确认后必须采用服务端 revision');
  assert.equal(WS.page.items[0].status.content, 'confirmed', '确认后条目必须落为 confirmed');
  console.log('page confirm happy path ok');
}

// 复核项:服务端 review_required(UI 预检查未命中,模拟两端状态分歧)
// → 显式接受后带 accepted_review 重发
{
  setupProject('pV', 'slide_001', 1);
  WS.page.items = [regionItem('ann_001')];
  sandbox.__calls.post = [];
  let confirmCalls = 0;
  sandbox.__api.post = async (_url, payload) => {
    confirmCalls += 1;
    if (confirmCalls === 1) {
      assert.equal(payload.accepted_review.length, 0);
      const error = new Error('review required');
      error.status = 422;
      error.body = { detail: { code: 'review_required', items: [{ annotation_id: 'ann_001', reason: 'needs_review' }] } };
      throw error;
    }
    assert.equal(payload.accepted_review.length, 1, '重发必须显式接受复核项');
    assert.equal(payload.accepted_review[0], 'ann_001');
    return { slide_id: 'slide_001', revision: 2, confirmed: 1, timeline_built: false, timeline_error: 'audio_timeline_missing' };
  };
  await run('confirmAnnotationPage()');
  // 重试经 showCustomConfirm 回调触发(火后不理),等微任务排空后再断言
  await await0();
  await await0();
  assert.equal(confirmCalls, 2, 'review_required 必须确认后重发');
  assert.equal(WS.page.items[0].status.content, 'confirmed');
  assert.ok(sandbox.__toasts.some(message => message.includes('音频时间轴')), '时间轴缺失必须给出可操作提示');
  console.log('review_required acceptance ok');
}

// Immediately confirming must capture edits before the debounce timer fires.
{
  setupProject('pBarrier', 'slide_001', 1);
  WS.page.items = [regionItem('ann_001')];
  WS.selectedAnnotationId = 'ann_001';
  run("scheduleAnnotationStyleCommit('ann_001', item => ({timing: {...item.timing, manual_start_sec: 11.2}}))");
  sandbox.__api.patch = async (_url, payload) => {
    assert.equal(payload.operations[0].patch.timing.manual_start_sec, 11.2);
    return {revision: 2, items: [regionItem('ann_001', {timing: {...WS.page.items[0].timing}})]};
  };
  await run('flushAnnotationsSave()');
  assert.equal(WS.page.revision, 2);
  assert.equal(WS.pendingOps.length, 0);
  console.log('immediate edit save barrier ok');
}
{
  setupProject('pUnbound', 'slide_001', 1);
  WS.page.items = [regionItem('ann_001', {protection: {source: 'manual', modified_fields: []}})];
  sandbox.__api.post = async () => { throw new Error('unbound default must not confirm'); };
  await run('confirmAnnotationPage()');
  assert.equal(WS.page.revision, 1);
  assert.equal(WS.page.items[0].status.content, 'draft');
  console.log('unbound default trigger blocked ok');
}
{
  setupProject('videoRepair', 'slide_001');
  const item = regionItem('ann_001', {anchor: {beat_id: 'b1', quote: '重点', range: [2, 4]}});
  WS.page.items = [item];
  assert.equal(run("setAnnotationVideoStart('ann_001', 2.5)"), true);
  assert.equal(WS.page.items[0].timing.manual_start_sec, 2.5);
  assert.equal(WS.page.items[0].timing.time_reference, 'audio');
  assert.equal(WS.page.items[0].timing.offset_sec, 0);
  assert.equal(JSON.stringify(WS.page.items[0].anchor), JSON.stringify(item.anchor));
  assert.equal(JSON.stringify(WS.page.items[0].target), JSON.stringify(item.target));
  assert.equal(run("setAnnotationVideoStart('ann_001', -1)"), false);
  assert.equal(run("setAnnotationVideoStart('missing', 1)"), false);
  console.log('video timing repair preserves geometry and narration ok');
}
// 修正必须更新原条目，保留独立人工时间和讲稿，不创建重复标注。
{
  setupProject('pRepair', 'slide_001');
  const item = regionItem('ann_001', {
    anchor: {beat_id: 'b1', range: [2, 4], quote: '重点', occurrence: 1},
    timing: {trigger_mode: 'manual', manual_start_sec: 2.731, time_reference: 'audio'},
  });
  WS.page.items = [item]; WS.selectedAnnotationId = item.annotation_id;
  const polygon = [[200, 300], [600, 300], [600, 360], [200, 360]];
  run("beginAnnotationRepair('region')");
  run(`addAnnotationRegion(${JSON.stringify(polygon)})`);
  assert.equal(WS.page.items.length, 1);
  assert.equal(WS.pendingOps[0].op, 'update');
  assert.equal(WS.pendingOps[0].annotation_id, 'ann_001');
  assert.equal(JSON.stringify(WS.page.items[0].anchor), JSON.stringify(item.anchor));
  assert.equal(JSON.stringify(WS.page.items[0].timing), JSON.stringify(item.timing));
  run('undoAnnotationEdit()');
  assert.equal(JSON.stringify(WS.page.items[0].target.polygons), JSON.stringify(item.target.polygons));
  console.log('region repair preserves identity, anchor, manual time and undo ok');
}
{
  setupProject('pRepair', 'slide_001');
  WS.page.items = [regionItem('ann_001')]; WS.selectedAnnotationId = 'ann_001';
  run("beginAnnotationRepair('freehand'); ANNOTATIONS_ED.freehandStrokes = [[[100,200],[200,220],[300,210]]]");
  run('finishAnnotationFreehand()');
  assert.equal(WS.pendingOps.length, 0, '后台自动保存不能提前提交重画的半条笔迹');
  run('finishAnnotationFreehand(true)');
  assert.equal(WS.page.items.length, 1);
  assert.equal(WS.pendingOps[0].op, 'update');
  assert.equal(WS.page.items[0].target.path_strokes.length, 1);
  console.log('explicit freehand repair replaces original item ok');
}
{
  setupProject('pRepair', 'slide_001');
  WS.page.items = [regionItem('ann_001'), regionItem('ann_002')]; WS.selectedAnnotationId = 'ann_001';
  const before = JSON.stringify(WS.page.items);
  run("beginAnnotationRepair('freehand'); ANNOTATIONS_ED.freehandStrokes = [[[100,200],[200,220]]]; selectAnnotationItem('ann_002')");
  assert.equal(JSON.stringify(WS.page.items), before);
  assert.equal(run('ANNOTATIONS_ED.repair'), null);
  assert.equal(run('ANNOTATIONS_ED.drawMode'), null);
  assert.equal(WS.pendingOps.length, 0);
  console.log('selection change cancels uncommitted repair without changing original ok');
}
{
  setupProject('pRepair', 'slide_001');
  WS.page.items = [regionItem('ann_001')]; WS.selectedAnnotationId = 'ann_001';
  run("beginAnnotationRepair('region')");
  const beforeCalls = sandbox.__calls.post.length;
  await run('confirmAnnotationPage()');
  assert.equal(sandbox.__calls.post.length, beforeCalls, '未完成重画不能确认原标注');
  run('cancelAnnotationRepair()');
  WS.failedOps = [{op:'update',annotation_id:'ann_001',patch:{}}];
  await run('saveAnnotationEdits()');
  assert.match(sandbox.__toasts.at(-1), /尚未保存/);
  console.log('unfinished repair blocks confirmation and rejected edits never claim saved ok');
}
// Unsent delete + undo must retain the saved ID and confirmation without I/O.
{
  setupProject('pCancelDelete', 's');
  const item = regionItem('ann_saved', {status: {content: 'confirmed'}});
  WS.page.items = [item];
  run('pushAnnotationHistory()');
  WS.page.items = [];
  WS.pendingOps = [core.buildDeleteOperation('ann_saved')];
  WS.failedOps = [core.buildDeleteOperation('ann_saved')];
  run('undoAnnotationEdit()');
  assert.equal(WS.pendingOps.length, 0);
  assert.equal(WS.failedOps.length, 0);
  assert.equal(WS.page.items[0].annotation_id, 'ann_saved');
  assert.equal(WS.page.items[0].status.content, 'confirmed');
  run('redoAnnotationEdit()');
  assert.equal(WS.pendingOps[0].annotation_id, 'ann_saved');
}

// Undo a delete in flight: the pending compensating add remains visible and
// history/selection follow its assigned server ID for later redo.
{
  setupProject('pFlightDelete', 's', 1);
  WS.page.items = [regionItem('ann_old')];
  run('pushAnnotationHistory()');
  WS.page.items = [];
  WS.pendingOps = [core.buildDeleteOperation('ann_old')];
  let first, second;
  let calls = 0;
  sandbox.__api.patch = (_url, payload) => new Promise(resolve => {
    if (++calls === 1) first = resolve;
    else {
      assert.equal(WS.page.items.length, 1, 'save response must preserve the undo shown on screen');
      second = () => resolve({revision: 3, items: [regionItem('ann_new')]});
    }
  });
  const saving = run('flushAnnotationsSave()');
  await await0();
  run('undoAnnotationEdit()');
  assert.ok(WS.page.items[0].annotation_id.startsWith('local_'));
  first({revision: 2, items: []});
  await await0();
  assert.equal(WS.page.items.length, 1);
  second();
  await saving;
  assert.equal(WS.page.items[0].annotation_id, 'ann_new');
  run('redoAnnotationEdit()');
  assert.equal(WS.pendingOps[0].annotation_id, 'ann_new');
}

// New updates made while saving must overlay the older server response.
{
  setupProject('pOverlay', 's', 1);
  WS.page.items = [regionItem('ann_1')];
  const initial = core.buildUpdateOperation('ann_1', {style: {color: '#00AA00'}});
  WS.pendingOps = [initial];
  let release;
  let calls = 0;
  sandbox.__api.patch = (_url, payload) => {
    if (++calls === 1) return new Promise(resolve => { release = resolve; });
    assert.equal(WS.page.items[0].style.width, 12, 'new width cannot flash back during a save');
    return Promise.resolve({revision: 3, items: [regionItem('ann_1', {style: {color: '#00AA00', width: 12}})]});
  };
  const saving = run('flushAnnotationsSave()');
  await await0();
  WS.page.items[0].style.width = 12;
  WS.pendingOps.push(core.buildUpdateOperation('ann_1', {style: {width: 12}}));
  release({revision: 2, items: [regionItem('ann_1', {style: {color: '#00AA00', width: 5}})]});
  await saving;
  assert.equal(WS.page.items[0].style.width, 12);
}

// Identical targets do not let a new local add steal an existing saved ID.
{
  setupProject('pDuplicateTarget', 's');
  WS.page.items = [regionItem('ann_existing'), regionItem('local_same')];
  WS.pendingOps = [core.buildUpdateOperation('local_same', {style: {width: 9}})];
  sandbox.__mappingBatch = [core.buildAddOperation(WS.page.items[1])];
  sandbox.__mappingResponse = [regionItem('ann_existing'), regionItem('ann_new')];
  run('remapAnnotationLocalOps(__mappingBatch, __mappingResponse, new Set(["ann_existing"]))');
  assert.equal(WS.pendingOps[0].annotation_id, 'ann_new');
  assert.equal(WS.page.items[0].annotation_id, 'ann_existing');
  assert.equal(WS.page.items[1].annotation_id, 'ann_new');
}

// Continuous multi-character selection reuses the real OCR token IDs.
{
  setupProject('pWords', 's');
  WS.candidates = ['重', '点', '词'].map((text, i) => ({text, token_id: `t${i}`, line_id: 'l', granularity: 'char', polygon: REGION_TARGET.polygons[0]}));
  run('selectAnnotationCandidate("t0", false)');
  run('selectAnnotationCandidate("t2", true)');
  run('addAnnotationFromCandidate(ANNOTATIONS_WS.candidateSelection)');
  assert.equal(WS.page.items[0].target.quote, '重点词');
  assert.equal(WS.page.items[0].target.granularity, 'word');
  assert.deepEqual(Array.from(WS.page.items[0].target.token_ids), ['t0', 't1', 't2']);
  assert.equal(WS.page.items[0].__deferredAdd, true, 'unbound multi-character target remains a recoverable local draft');
}
{
  setupProject('pDeferred', 's');
  WS.slideIds = ['s', 'other'];
  WS.page.items = [regionItem('local_unbound', {__deferredAdd: true})];
  sandbox.__api.get = async url => url.endsWith('/text-layout') ? {candidates: []}
    : {revision: 1, items: [], narration: {beats: []}};
  await run('selectAnnotationPage(1)');
  assert.equal(WS.page.items.length, 0);
  await run('selectAnnotationPage(0)');
  assert.equal(WS.page.items[0].annotation_id, 'local_unbound');
  assert.equal(WS.page.items[0].__deferredAdd, true);
  assert.equal(WS.pendingOps.length, 0, 'unbound drafts must not be sent as invalid adds');
  assert.equal(run('hasUnsavedAnnotationEdits()'), true, 'unbound or stashed drafts must warn before a browser unload');
}
console.log('annotation edit recovery checks passed');
})().catch(error => { console.error(error); process.exit(1); });

// ------------------------------------------------------------ VM 环境桩

function createSandbox() {
  const toasts = [];
  const confirms = [];
  const calls = { patch: [], get: [], post: [], put: [] };
  const state = { currentProject: { id: 'pA' }, currentStep: 10, step_status: {} };
  const nodeStub = () => ({
    style: {}, dataset: {}, textContent: '', innerHTML: '', title: '',
    onclick: null, checked: false, value: '', disabled: false,
    setAttribute: () => {}, getAttribute: () => null,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 960, height: 540 }),
    remove: () => {}, append: () => {}, appendChild: () => {},
    querySelectorAll: () => [], querySelector: () => null,
    addEventListener: () => {},
    classList: { toggle: () => {}, add: () => {}, remove: () => {} },
  });
  const document = { getElementById: () => nodeStub(), createElement: () => nodeStub(), createElementNS: () => nodeStub(), querySelectorAll: () => [] };
  const windowObj = {};
  const queue = [];
  const sandbox = {
    console,
    setTimeout: (fn, _ms) => { queue.push(fn); return queue.length; },
    clearTimeout: () => {},
    performance,
    Date, Math, JSON, Number, String, Boolean, Array, Object, Promise, Error, Set, Map,
    isNaN, parseInt, parseFloat,
    document,
    window: windowObj,
    state,
    showToast: message => toasts.push(message),
    showCustomConfirm: (_title, _message, onConfirm) => { confirms.push(_title); onConfirm(); },
    escHtml: value => String(value ?? ''),
    updateStepperUI: () => {},
    getProjectCanvasGeometry: () => ({ width: 1920, height: 1080 }),
    PPTFlow: { mapClientPointToCanvas: (_x, _y, _rect, width, height) => ({ x: 0, y: 0, width, height }) },
    selectAnnotationItem: id => { windowObj.ANNOTATIONS_WS.selectedAnnotationId = id; },
    renderAnnotationCandidates: () => {},
    renderAnnotationJobProgress: () => {},
    __api: {},
    __calls: calls,
    __toasts: toasts,
    __confirms: confirms,
    __queue: queue,
  };
  sandbox.API = {
    async patch(url, payload) {
      calls.patch.push({ url, payload });
      const handler = sandbox.__api && sandbox.__api.patch;
      if (!handler) throw new Error('patch handler not set');
      return handler(url, payload);
    },
    async get(url) {
      calls.get.push({ url });
      const handler = sandbox.__api && sandbox.__api.get;
      if (!handler) throw new Error('get handler not set');
      return handler(url);
    },
    async post(url, payload) {
      calls.post.push({ url, payload });
      const handler = sandbox.__api && sandbox.__api.post;
      if (!handler) throw new Error('post handler not set');
      return handler(url, payload);
    },
    async put(url, payload) {
      calls.put.push({ url, payload });
      const handler = sandbox.__api && sandbox.__api.put;
      if (!handler) throw new Error('put handler not set');
      return handler(url, payload);
    },
  };
  return sandbox;
}
