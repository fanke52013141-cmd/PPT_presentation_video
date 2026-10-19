// 勾画保存管线行为回归(R4-002/003/005/006 + 幂等):
// 在 Node VM 中以真实 annotations_workspace.js 驱动,用可控行为的 API 桩
// 复现审查报告中的交替时序。注释标注对应验收条款。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const sandbox = createSandbox();
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(root, 'static', 'annotations_core.js'), 'utf8'), sandbox);
vm.runInContext(fs.readFileSync(path.join(root, 'static', 'annotations_workspace.js'), 'utf8'), sandbox);

const core = sandbox.AnnotationsCore;
const WS = sandbox.window.ANNOTATIONS_WS;

// ------------------------------------------------------------ core 纯逻辑

// 本地操作合并:update/delete 引用 local_ id 时并入 add,不发给服务端
{
  const add = core.buildAddOperation({
    annotation_id: 'local_1',
    target: core.buildRegionTarget([[0, 0], [10, 0], [10, 10], [0, 10]]),
    style: { type: 'ellipse', color: '#F46A38' },
  });
  const { operations, failedOps } = core.coalesceLocalOperations(
    [add, core.buildUpdateOperation('local_1', { style: { type: 'ellipse', color: '#00AA00' } })],
    [],
    null,
    null
  );
  assert.equal(operations.length, 1);
  assert.equal(operations[0].item.style.color, '#00AA00');
  assert.deepEqual(failedOps, []);
  // delete 撤下 add
  const del = core.coalesceLocalOperations(
    [core.buildAddOperation({ annotation_id: 'local_2', target: core.buildRegionTarget([[1, 1], [2, 1], [2, 2], [1, 2]]) }),
     core.buildDeleteOperation('local_2')],
    [], null, null
  );
  assert.equal(del.operations.length, 0);
  // update 悬空引用被丢弃而非整批失败
  const dangling = core.coalesceLocalOperations([core.buildUpdateOperation('local_404', { style: {} })], [], null, null);
  assert.equal(dangling.operations.length, 0);
  // 失败暂存区中的 add 也能接收合并
  const hostAdd = core.buildAddOperation({ annotation_id: 'local_3', target: core.buildRegionTarget([[3, 3], [4, 3], [4, 4], [3, 4]]) });
  const merged = core.coalesceLocalOperations(
    [core.buildUpdateOperation('local_3', { timing: { draw_duration_sec: 0.9 } })],
    [hostAdd], null, null
  );
  assert.equal(merged.failedOps[0].item.timing.draw_duration_sec, 0.9);
}

// 服务端内容去重:网络响应丢失后,已生效的 add 不重发
{
  const appliedAdd = core.buildAddOperation({
    target: { kind: 'region', granularity: 'region', polygons: [[[7, 7], [9, 7], [9, 9], [7, 9]]], token_ids: [], quote: null },
  });
  const serverItems = [
    { annotation_id: 'ann_009', target: { kind: 'region', granularity: 'region', polygons: [[[7, 7], [9, 7], [9, 9], [7, 9]]], token_ids: [], quote: null } },
  ];
  const deduped = core.dedupeOperationsAgainstPage([appliedAdd], serverItems);
  assert.equal(deduped.applied.length, 1);
  assert.equal(deduped.remaining.length, 0);
  // 内容不同 → 保留重发
  const freshAdd = core.buildAddOperation({
    target: { kind: 'region', granularity: 'region', polygons: [[[11, 11], [12, 11], [12, 12], [11, 12]]], token_ids: [], quote: null },
  });
  const kept = core.dedupeOperationsAgainstPage([freshAdd], serverItems);
  assert.equal(kept.remaining.length, 1);
  // delete 已生效(条目不存在) → 不重发;update 目标已消失 → 丢弃
  const gone = core.dedupeOperationsAgainstPage(
    [core.buildDeleteOperation('ann_009'), core.buildUpdateOperation('ann_009', { style: {} })],
    [{ annotation_id: 'ann_001' }]
  );
  assert.equal(gone.applied.length, 2);
}

// ------------------------------------------------------------ VM 环境桩

function createSandbox() {
  const toasts = [];
  const calls = { patch: [], get: [] };
  const state = { currentProject: { id: 'pA' }, currentStep: 10 };
  const nodeStub = () => ({
    style: {}, dataset: {}, textContent: '', innerHTML: '', title: '',
    onclick: null, checked: false, value: '',
    display: undefined,
    querySelectorAll: () => [],
    querySelector: () => null,
    appendChild: () => {},
    addEventListener: () => {},
    classList: { toggle: () => {}, add: () => {}, remove: () => {} },
  });
  const document = { getElementById: () => nodeStub(), createElement: () => nodeStub() };
  const windowObj = {};
  const base = {
    console,
    setTimeout: (fn, _ms) => { queue.push(fn); return queue.length; },
    clearTimeout: () => {},
    Date, Math, JSON, Number, String, Boolean, Array, Object, Promise, Error,
    isNaN, parseInt, parseFloat,
  };
  const queue = [];
  const sandbox = {
    ...base,
    document,
    window: windowObj,
    state,
    showToast: message => toasts.push(message),
    escHtml: value => String(value ?? ''),
    updateStepperUI: () => {},
    renderAnnotationItems: () => {},
    renderAnnotationOverlay: () => {},
    renderAnnotationNarrationHighlights: () => {},
    renderAnnotationItemEditor: () => {},
    refreshAnnotationsStepFlag: () => {},
    selectAnnotationItem: () => {},
    renderAnnotationWorkspace: () => {},
    renderAnnotationCandidates: () => {},
    renderAnnotationMissingState: () => {},
    renderAnnotationThumbnails: () => {},
    renderAnnotationNarration: () => {},
    renderAnnotationJobProgress: () => {},
    annotationPrerequisitesBlocked: () => false,
    __api: {},
    __calls: calls,
    __toasts: toasts,
    __queue: queue,
  };
  // API 桩:由用例注入行为;记录调用便于断言
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
    async getOptional(url) {
      calls.get.push({ url });
      const handler = sandbox.__api && (sandbox.__api.getOptional || sandbox.__api.get);
      if (!handler) return { success: false };
      return handler(url);
    },
    async post(url, payload) {
      calls.post = calls.post || [];
      calls.post.push({ url, payload });
      const handler = sandbox.__api && sandbox.__api.post;
      if (!handler) throw new Error('post handler not set');
      return handler(url, payload);
    },
    async put(url, payload) {
      calls.put = calls.put || [];
      calls.put.push({ url, payload });
      const handler = sandbox.__api && sandbox.__api.put;
      if (!handler) throw new Error('put handler not set');
      return handler(url, payload);
    },
  };
  return sandbox;
}

const run = expr => vm.runInContext(expr, sandbox);
const g = expr => vm.runInContext(expr, sandbox);

function setupProject(projectId, slideId, revision = 0) {
  g(`(() => {
    resetAnnotationsProjectState();
    ANNOTATIONS_WS.projectId = ${JSON.stringify(projectId)};
    ANNOTATIONS_WS.page = { slide_id: ${JSON.stringify(slideId)}, revision: ${revision}, items: [] };
  })()`);
}

const REGION_TARGET = {
  kind: 'region', layout_revision: null, token_ids: [],
  polygons: [[[100, 200], [400, 200], [400, 260], [100, 260]]],
  quote: null, granularity: 'region', mask_group_ids: [],
};

function await0() { return new Promise(resolve => setImmediate(resolve)); }

(async () => {
  // Reopening into Output restores the saved decision; an old project's
  // delayed response must not overwrite the newly opened project's state.
  {
    setupProject('pA', 'slide_001');
    sandbox.state.currentProject = { id: 'pA' };
    sandbox.__api.get = async () => ({ settings: { enabled: true }, module_state: 'confirmed', slides: [] });
    await run('loadAnnotationWorkflowState("pA")');
    assert.equal(sandbox.window.__annotationModuleState, 'confirmed');
    assert.equal(sandbox.window.__annotationsEnabled, true);
    let finish;
    sandbox.__api.get = () => new Promise(resolve => { finish = resolve; });
    const pending = run('loadAnnotationWorkflowState("pA")');
    run('resetAnnotationsProjectState()');
    sandbox.state.currentProject = { id: 'pB' };
    finish({ settings: { enabled: true }, module_state: 'confirmed', slides: [] });
    await pending;
    assert.equal(sandbox.window.__annotationModuleState, 'not_started');
    assert.equal(sandbox.window.__annotationsEnabled, false);
    sandbox.state.currentProject = { id: 'pA' };
  }
  // ------------------------------------------------------------ R4-002(主流程)
  {
    setupProject('pA', 'slide_001');
    sandbox.__api.patch = async () => ({ revision: 1, items: [{ annotation_id: 'ann_001', target: REGION_TARGET }] });
    let renderThrows = false;
    sandbox.renderAnnotationItems = () => { if (renderThrows) throw new Error('overlay boom'); };
    renderThrows = true;
    g(`ANNOTATIONS_WS.pendingOps.push(AnnotationsCore.buildAddOperation({ target: AnnotationsCore.buildRegionTarget([[100, 200], [400, 200], [400, 260], [100, 260]]) }))`);
    await run('flushAnnotationsSave()').catch(error => { throw new Error('flush should not reject on render failure'); });
    assert.equal(WS.pendingOps.length, 0, 'R4-002: 服务端已提交后覆盖层故障,操作不得重新入队');
    assert.equal(WS.page.revision, 1);
    console.log('R4-002 ok');
  }

  // ------------------------------------------------------------ R4-003: A 项目失败回调晚于 B 项目载入
  {
    setupProject('pA', 'slide_001');
    let releaseA;
    sandbox.__api.patch = () => new Promise((_, reject) => { releaseA = reject; });
    g(`ANNOTATIONS_WS.pendingOps.push(AnnotationsCore.buildAddOperation({ target: AnnotationsCore.buildRegionTarget([[10, 10], [20, 10], [20, 20], [10, 20]]) }))`);
    const flushPromise = run('flushAnnotationsSave()').catch(() => 'rejected-as-expected');
    // A 请求在途时切换到 B 项目
    setupProject('pB', 'slide_001');
    g(`ANNOTATIONS_WS.pendingOps.push(AnnotationsCore.buildAddOperation({ target: AnnotationsCore.buildRegionTarget([[50, 50], [60, 50], [60, 60], [50, 60]]) }))`);
    const bOpsBefore = JSON.parse(JSON.stringify(WS.pendingOps));
    releaseA({ status: 0, message: 'network gone', body: null });
    await flushPromise;
    assert.equal(WS.pendingOps.length, 1, 'R4-003: A 的失败操作不得进入 B 的队列');
    assert.equal(JSON.stringify(WS.pendingOps), JSON.stringify(bOpsBefore));
    assert.equal(WS.draftOps['pA::slide_001'].length, 1, 'A 的失败操作归属 A 页草稿');
    console.log('R4-003 cross-project ok');
  }

  // ------------------------------------------------------------ R4-003: A 项目成功回调晚于 B 项目载入
  {
    setupProject('pStale', 'slide_001');
    let releaseA;
    sandbox.__api.patch = () => new Promise(resolve => { releaseA = resolve; });
    g(`ANNOTATIONS_WS.pendingOps.push(AnnotationsCore.buildAddOperation({ target: AnnotationsCore.buildRegionTarget([[10, 10], [20, 10], [20, 20], [10, 20]]) }))`);
    const flushPromise = run('flushAnnotationsSave()').catch(() => 'should-not-reject');
    setupProject('pStaleB', 'slide_001');
    g(`ANNOTATIONS_WS.pendingOps.push(AnnotationsCore.buildAddOperation({ target: AnnotationsCore.buildRegionTarget([[50, 50], [60, 50], [60, 60], [50, 60]]) }))`);
    const bOpsBefore = JSON.parse(JSON.stringify(WS.pendingOps));
    releaseA({ revision: 9, items: [] });
    await flushPromise;
    assert.equal(WS.pendingOps.length, 1, 'A 的成功响应不得清掉 B 的队列');
    assert.equal(JSON.stringify(WS.pendingOps), JSON.stringify(bOpsBefore));
    assert.equal(WS.draftOps['pStale::slide_001'], undefined, 'A 已在服务端生效,不得暂存重发(避免重复)');
    console.log('R4-003 stale-success ok');
  }

  // ------------------------------------------------------------ R4-006: 409 冲突恢复
  {
    setupProject('pA', 'slide_001');
    let patchCall = 0;
    sandbox.__api.patch = async (_url, payload) => {
      patchCall += 1;
      if (patchCall === 1) {
        const error = new Error('conflict');
        error.status = 409;
        error.body = { detail: { code: 'revision_conflict', current_revision: 7 } };
        throw error;
      }
      assert.equal(payload.expected_revision, 7, '重放必须使用服务端当前 revision');
      return { revision: 8, items: [{ annotation_id: 'ann_002', target: REGION_TARGET }] };
    };
    sandbox.__api.get = async () => ({ revision: 7, items: [{ annotation_id: 'ann_100', target: REGION_TARGET }] });
    g(`ANNOTATIONS_WS.pendingOps.push(AnnotationsCore.buildAddOperation({ target: AnnotationsCore.buildRegionTarget([[100, 200], [400, 200], [400, 260], [100, 260]]) }))`);
    await run('flushAnnotationsSave()').catch(() => 'expected rejection');
    assert.ok(WS.conflict, '409 后冲突批次必须被保留');
    assert.equal(WS.conflict.currentRevision, 7);
    assert.equal(WS.pendingOps.length, 0, '冲突批次不自动重试');
    await run('resolveAnnotationConflict()');
    assert.equal(WS.conflict, null, '恢复流程清空冲突');
    assert.equal(WS.page.revision, 8);
    assert.equal(WS.pendingOps.length, 0);
    console.log('R4-006 conflict recovery ok');
  }

  // ------------------------------------------------------------ R4-003: 422 隔离,不无限重试不静默丢弃
  {
    setupProject('pA', 'slide_001');
    let patchCall = 0;
    sandbox.__api.patch = async () => {
      patchCall += 1;
      if (patchCall === 1) {
        const error = new Error('invalid');
        error.status = 422;
        error.body = { detail: { code: 'validation_failed', issues: [{ path: 'operations[0].item.style.width', code: 'out_of_range', message: '宽度超出范围' }] } };
        throw error;
      }
      return { revision: 2, items: [] };
    };
    g(`ANNOTATIONS_WS.pendingOps.push(AnnotationsCore.buildAddOperation({ target: AnnotationsCore.buildRegionTarget([[100, 200], [400, 200], [400, 260], [100, 260]]) }))`);
    await run('flushAnnotationsSave()').catch(() => 'expected rejection');
    assert.equal(WS.pendingOps.length, 0, '422 不得留在待存队列里无限重试');
    assert.equal(WS.failedOps.length, 1, '422 操作隔离到失败草稿,不静默丢弃');
    await run('retryAnnotationFailedOps()');
    assert.equal(WS.failedOps.length, 0, '用户显式重试后可恢复');
    assert.equal(patchCall, 2);
    console.log('R4-003 validation isolation ok');
  }

  // ------------------------------------------------------------ 幂等:网络响应丢失,add 已在服务端生效
  {
    setupProject('pA', 'slide_001', 2);
    sandbox.__api.patch = async () => {
      const error = new Error('response lost');
      error.status = 0;
      throw error;
    };
    sandbox.__api.get = async () => ({
      revision: 3,
      items: [{ annotation_id: 'ann_009', target: REGION_TARGET }],
    });
    g(`ANNOTATIONS_WS.pendingOps.push(AnnotationsCore.buildAddOperation({ target: AnnotationsCore.buildRegionTarget([[100, 200], [400, 200], [400, 260], [100, 260]]) }))`);
    await run('flushAnnotationsSave()').catch(() => 'expected rejection');
    assert.equal(WS.pendingOps.length, 0, '已在服务端生效的 add 不得重发(避免标注重复)');
    assert.equal(WS.page.revision, 3, '采用服务端真值');
    assert.equal(WS.page.items.length, 1);
    console.log('idempotent add dedupe ok');
  }

  // ------------------------------------------------------------ 本地操作合并进入请求
  {
    setupProject('pA', 'slide_001');
    let captured = null;
    sandbox.__api.patch = async (_url, payload) => {
      captured = payload;
      return { revision: 1, items: [] };
    };
    g(`(() => {
      const localItem = { annotation_id: 'local_x', target: AnnotationsCore.buildRegionTarget([[1, 1], [5, 1], [5, 5], [1, 5]]), style: { type: 'ellipse', color: '#F46A38' } };
      ANNOTATIONS_WS.page.items.push(localItem);
      ANNOTATIONS_WS.pendingOps.push(AnnotationsCore.buildAddOperation(localItem));
      ANNOTATIONS_WS.pendingOps.push(AnnotationsCore.buildUpdateOperation('local_x', { style: { type: 'ellipse', color: '#123456' } }));
    })()`);
    await run('flushAnnotationsSave()');
    assert.equal(captured.operations.length, 1, '本地 update 合并进 add,服务端不会收到 unknown_id');
    assert.equal(captured.operations[0].item.style.color, '#123456');
    assert.notEqual(captured.operations[0].client_op_id, undefined, 'add 携带幂等键');
    console.log('local coalesce ok');
  }

  // ------------------------------------------------------------ R4-005: 候选响应晚于切页
  {
    setupProject('pA', 'slide_001');
    sandbox.__api.get = async () => {
      // 响应返回前模拟用户已切到下一页
      WS.pageGeneration += 1;
      WS.page = { slide_id: 'slide_002', revision: 0, items: [] };
      return { candidates: [{ token_id: 'token_A', text: '旧页文字', polygon: [[0, 0], [1, 0], [1, 1], [0, 1]] }], layout_revision: 4 };
    };
    await run('loadAnnotationCandidates()');
    assert.equal(WS.candidates.length, 0, 'A 页候选不得落进 B 页');
    console.log('R4-005 candidate guard ok');
  }

  // ------------------------------------------------------------ R4-005: 切页保留未保存草稿
  {
    setupProject('pSwitch', 'slide_001');
    sandbox.__api.patch = async () => { throw Object.assign(new Error('offline'), { status: 0 }); };
    sandbox.__api.get = async url => {
      if (url.endsWith('/text-layout')) throw Object.assign(new Error('offline'), { status: 0 });
      return { revision: 0, items: [] };
    };
    g(`ANNOTATIONS_WS.pendingOps.push(AnnotationsCore.buildAddOperation({ target: AnnotationsCore.buildRegionTarget([[100, 200], [400, 200], [400, 260], [100, 260]]) }))`);
    await run('selectAnnotationPage(0)').catch(() => {});
    // selectAnnotationPage 的内部 flush 失败后,残留操作应暂存在原页草稿
    assert.equal(WS.draftOps['pSwitch::slide_001']?.length >= 1, true, '切页时未保存操作归属原页草稿,不静默丢弃');
    console.log('R4-005 page-switch draft ok');
  }


  // ------------------------------------------------------------ B1: 切页后过期响应复位 saveInFlight
  {
    setupProject('pStale2', 'slide_001');
    g(`ANNOTATIONS_WS.slideIds = ['slide_001', 'slide_002']`);
    let releaseA;
    sandbox.__api.patch = () => new Promise(resolve => { releaseA = resolve; });
    sandbox.__api.get = async url => {
      if (url.endsWith('/text-layout')) return { candidates: [], layout_revision: 0 };
      return { revision: 0, items: [], narration: { beats: [] }, image: { hash: 'h' } };
    };
    g(`ANNOTATIONS_WS.pendingOps.push(AnnotationsCore.buildAddOperation({ target: AnnotationsCore.buildRegionTarget([[10, 10], [20, 10], [20, 20], [10, 20]]) }))`);
    const flushPromise = run('flushAnnotationsSave()').catch(() => 'should-not-reject');
    // 真实完成切页:页面代次 bump、page.slide_id 变为 slide_002
    const switchPromise = run('selectAnnotationPage(1)').catch(() => {});
    releaseA({ revision: 9, items: [] });
    await switchPromise;
    assert.equal(WS.page.slide_id, 'slide_002', '前置:切页确实完成');
    releaseA({ revision: 9, items: [] });
    await flushPromise;
    assert.equal(WS.saveInFlight, false, 'B1: 过期响应早退必须复位 saveInFlight,否则自动保存停摆');
    assert.equal(WS.page.slide_id, 'slide_002', '过期响应不得触碰新页面');
    assert.equal(WS.page.revision, 0, '新页面的 revision 不被旧响应覆盖');
    console.log('B1 stale-release saveInFlight ok');
  }

  console.log('annotation save flow checks passed');
})().catch(error => {
  console.error('FAILED:', error && error.message);
  console.error(error && error.stack);
  process.exit(1);
});
