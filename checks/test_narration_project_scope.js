// Narration Step 6/7 + Step 1 cross-project scope regression (P0 family of 9-06 review).
//
// 加载真实的 workspace_navigation.js / narration_audio.js / article.js 到 vm 沙箱，
// 用可控定时器与可控 Promise 复现"编辑后立刻切项目"的时序。核心验收标准：
// 请求目标项目与 payload 所属项目始终一致；迟到响应绝不写进已切换项目的状态。
//
// 运行：node checks/test_narration_project_scope.js

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const STATIC_DIR = path.join(__dirname, '..', 'static');

function makeElement(id) {
  return {
    id,
    innerHTML: '',
    innerText: '',
    value: '',
    textContent: '',
    style: {},
    disabled: false,
    hidden: false,
    dataset: {},
    classList: {
      add() {},
      remove() {},
      toggle() {},
      contains() { return false; },
    },
    childNodes: [],
    appendChild(node) { this.childNodes.push(node); },
    replaceChildren(...nodes) { this.childNodes = nodes; },
    remove() {},
    querySelector() { return makeElement(`${id}-child`); },
    closest() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
    setAttribute() {},
    getAttribute() { return null; },
    removeAttribute() {},
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function createSandbox() {
  const sandbox = {
    console,
    Promise,
    Date,
    JSON,
    Math,
    Set,
    Map,
    Number,
    Array,
    Object,
    String,
    Boolean,
    Error,
    isFinite,
  };
  // ---- 可控定时器 ----
  const timers = [];
  let timerSeq = 0;
  sandbox.setTimeout = (fn, delay) => {
    timerSeq += 1;
    timers.push({ id: timerSeq, fn, delay });
    return timerSeq;
  };
  sandbox.clearTimeout = (id) => {
    const index = timers.findIndex(timer => timer.id === id);
    if (index >= 0) timers.splice(index, 1);
  };
  sandbox.timers = timers;
  sandbox.drainTimers = () => {
    while (timers.length) {
      const timer = timers.shift();
      timer.fn();
    }
  };

  // ---- DOM 桩 ----
  const elements = new Map();
  const audioSlots = [];
  sandbox.document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, makeElement(id));
      return elements.get(id);
    },
    querySelector() { return null; },
    querySelectorAll(selector) {
      if (selector === '.step6-slide-audio') return audioSlots;
      return [];
    },
    createElement(tag) { return makeElement(tag); },
    createTextNode(text) { return { textContent: text }; },
    body: {
      classList: {
        add() {},
        remove() {},
        contains(cls) { return cls === 'workspace-open' && sandbox.workspaceOpen.value; },
      },
      appendChild() {},
    },
    documentElement: { style: { setProperty() {}, removeProperty() {} } },
  };
  sandbox.workspaceOpen = { value: false };
  sandbox.openWorkspace = () => { sandbox.workspaceOpen.value = true; };
  sandbox.registerAudioSlot = (slideId) => {
    const slot = makeElement(`audio-slot-${slideId}`);
    slot.dataset.audioSlideId = slideId;
    audioSlots.push(slot);
    return slot;
  };
  sandbox.element = id => elements.get(id);

  // ---- 共享状态与工具桩（与生产模块约定同名） ----
  sandbox.state = {
    currentProject: null,
    currentStep: 6,
    activeSlideIndex: 0,
    step6AutoSaveTimer: null,
    step6AutoSavePromise: null,
    articleInputMode: 'article',
  };
  sandbox.window = sandbox;
  sandbox.escHtml = value => String(value ?? '');
  sandbox.toasts = [];
  sandbox.showToast = (...args) => sandbox.toasts.push(args[0]);
  sandbox.showCustomConfirm = (_title, _message, onOk) => onOk();
  sandbox.narrationDedupeKey = value => String(value || '').trim();
  sandbox.offerArtifactRepair = () => {};
  sandbox.requestAnimationFrame = () => {};
  sandbox.autoResizeTextarea = () => {};
  sandbox.renderPageTaskState = () => {};
  sandbox.setDisabledReason = (element, reason) => { if (element) element.disabled = !!reason; };
  sandbox.loadProjects = () => {};
  // mask_workspace.js 在生产加载顺序中先于 workspace_navigation 加载。
  sandbox.resetStep5ProjectState = () => {};
  sandbox.normalizeVisibleStep = step => Number(step);
  sandbox.projectFlowContext = () => ({});
  sandbox.getVisibleStepState = () => 'pending';
  sandbox.getProjectCanvasGeometry = () => ({ width: 1920, height: 1080, aspectRatio: '1920 / 1080' });
  sandbox.resolveProjectVisibleStep = project => Number(project.current_step || 1);

  // ---- 网络桩 ----
  sandbox.apiLog = { get: [], post: [] };
  const routes = new Map();
  sandbox.route = (pattern, handler) => routes.set(pattern, handler);
  const findRoute = url => [...routes.keys()]
    .sort((a, b) => b.length - a.length)
    .find(pattern => url.includes(pattern));
  sandbox.API = {
    get: async (url) => {
      sandbox.apiLog.get.push(url);
      const handler = findRoute(url);
      if (handler) return routes.get(handler)(url);
      return { success: false };
    },
    post: async (url, body) => {
      sandbox.apiLog.post.push({ url, body });
      const handler = findRoute(url);
      if (handler) return routes.get(handler)(url, body);
      return { success: false };
    },
    put: async (url, body) => {
      const response = await sandbox.fetch(url, { method: 'PUT', body: JSON.stringify(body) });
      const data = await response.json();
      if (!response.ok) {
        const error = new Error(data.detail || 'request failed');
        error.status = response.status || 500;
        throw error;
      }
      return data;
    },
  };
  sandbox.FormData = class {
    append() {}
  };
  sandbox.fetchLog = [];
  let fetchHandler = null;
  sandbox.setFetchHandler = handler => { fetchHandler = handler; };
  sandbox.fetch = async (url, options) => {
    sandbox.fetchLog.push({ url, options });
    if (fetchHandler) return fetchHandler(url, options);
    return { ok: true, json: async () => ({ success: true }) };
  };

  const context = vm.createContext(sandbox);
  for (const name of ['workspace_navigation.js', 'narration_audio.js', 'article.js']) {
    const code = fs.readFileSync(path.join(STATIC_DIR, name), 'utf8');
    vm.runInContext(code, context, { filename: name });
  }
  return sandbox;
}

function projectFixture(id, currentStep = 6) {
  return {
    id,
    name: `项目 ${id}`,
    current_step: currentStep,
    step_status: { '7': 'completed' },
    audio_confirmed: false,
    ai_mode: 'auto',
  };
}

const beatsFor = text => ({ slides: [{ slide_id: 'slide_001', beats: [{ tts_text: text, spoken_text: text }] }] });

function routeProjectB(box) {
  box.route('/api/projects/proj-B', () => projectFixture('proj-B'));
  box.route('/api/projects/proj-B/steps/6/result', () => ({ success: true, beats: beatsFor('B原文') }));
  box.route('/api/projects/proj-B/steps/3/images', () => ({ success: true, images: [] }));
  box.route('/api/projects/proj-B/steps/7/audio-status', () => ({ slides: [] }));
}

// 保存当前模块级 narrationData，返回 { url, payload }；用于断言共享状态归属。
async function snapshotNarrationState(box) {
  const before = box.fetchLog.length;
  const saved = await box.saveStep6Narration({ silent: true });
  assert.equal(saved, true, 'snapshot save must succeed');
  const call = box.fetchLog[box.fetchLog.length - 1];
  assert.equal(box.fetchLog.length, before + 1, 'snapshot save must issue exactly one PUT');
  return { url: call.url, payload: JSON.parse(call.options.body) };
}

// ---------- 场景 1：A 编辑后 700ms 内切到 B，不产生指向 B 的旁白 PUT ----------
async function scenarioSwitchWithinDebounce() {
  const box = createSandbox();
  box.state.currentProject = projectFixture('proj-A');
  box.openWorkspace();
  box.route('/api/projects/proj-A/steps/6/result', () => ({ success: true, beats: beatsFor('A原文') }));
  await box.loadStep6Data();

  box.updateNarrationBeatText(0, 0, 'A修改后');
  assert.equal(box.timers.length, 1, 'edit must schedule exactly one autosave timer');

  // 700ms 内切到 B：enterWorkspace 是生产切换路径（版本自增 + 统一清理）。
  routeProjectB(box);
  await box.enterWorkspace('proj-B');

  assert.equal(box.timers.length, 0, 'resetProjectScopedAsyncUi must clear the pending step6 timer');
  box.drainTimers();
  assert.equal(box.fetchLog.length, 1, 'leaving must flush the pending A edit exactly once');
  assert.ok(box.fetchLog[0].url.includes('/projects/proj-A/steps/6/result'));
  assert.equal(JSON.parse(box.fetchLog[0].options.body).slides[0].beats[0].tts_text, 'A修改后');

  // 共享状态归属 B：保存只能指向 B 且携带 B 的旁白。
  const snapshot = await snapshotNarrationState(box);
  assert.ok(snapshot.url.includes('/projects/proj-B/'), `state belongs to B: ${snapshot.url}`);
  assert.equal(snapshot.payload.slides[0].beats[0].tts_text, 'B原文');
  assert.ok(!JSON.stringify(snapshot.payload).includes('A原文'), 'A narration must not leak into B state');

  // B 工作区内的编辑正常调度自动保存并指向 B。
  box.updateNarrationBeatText(0, 0, 'B修改后');
  box.drainTimers();
  await box.state.step6AutoSavePromise;
  const lastPut = box.fetchLog[box.fetchLog.length - 1];
  assert.ok(lastPut.url.includes('/projects/proj-B/'), 'edit inside B must autosave to B');
  assert.equal(JSON.parse(lastPut.options.body).slides[0].beats[0].tts_text, 'B修改后');
}

// ---------- 场景 2：A 的保存正在等待重试，切到 B —— 重试仍只指向 A ----------
async function scenarioRetryStaysOnOriginalProject() {
  const box = createSandbox();
  box.state.currentProject = projectFixture('proj-A');
  box.openWorkspace();
  box.route('/api/projects/proj-A/steps/6/result', () => ({ success: true, beats: beatsFor('A原文') }));
  await box.loadStep6Data();

  let fetchCalls = 0;
  box.setFetchHandler(async () => {
    fetchCalls += 1;
    if (fetchCalls === 1) {
      // 第一次：网络层错误（非 HTTP 错误），触发 500ms 重试等待。
      throw new Error('network dropped');
    }
    return { ok: true, json: async () => ({ success: true }) };
  });

  const saving = box.saveStep6Narration({ silent: true });
  await Promise.resolve();
  assert.equal(box.fetchLog.length, 1);

  // 等待重试期间切到 B。
  routeProjectB(box);
  await box.enterWorkspace('proj-B');

  box.drainTimers(); // 释放 500ms 重试等待
  const saved = await saving;
  assert.equal(saved, true);

  const putUrls = box.fetchLog.map(call => call.url);
  assert.equal(putUrls.length, 2, 'retry must complete exactly one more attempt');
  for (const url of putUrls) {
    assert.ok(url.includes('/projects/proj-A/steps/6/result'), `retry must stay on project A: ${url}`);
  }
  const payload = JSON.parse(box.fetchLog[0].options.body);
  assert.equal(payload.slides[0].beats[0].tts_text, 'A原文', 'payload must belong to project A');

  // B 的状态未被污染：当前共享状态仍归属 B。
  const snapshot = await snapshotNarrationState(box);
  assert.ok(snapshot.url.includes('/projects/proj-B/'));
  assert.equal(snapshot.payload.slides[0].beats[0].tts_text, 'B原文');
}

// ---------- 场景 3：A 的加载 / AI 标注晚于 B 的加载完成，不得覆盖 B ----------
async function scenarioStaleResponsesDoNotOverwrite() {
  const box = createSandbox();
  box.state.currentProject = projectFixture('proj-A');
  box.openWorkspace();
  const deferredA = deferred();
  box.route('/api/projects/proj-A/steps/6/result', () => deferredA.promise);

  const loadingA = box.loadStep6Data(); // 挂起在 A 的响应上

  // B 先完成加载。
  routeProjectB(box);
  await box.enterWorkspace('proj-B');

  // A 的迟到响应此刻才到达：不得覆盖 B 的共享状态。
  deferredA.resolve({ success: true, beats: beatsFor('A迟到响应') });
  await loadingA;
  const snapshot = await snapshotNarrationState(box);
  assert.ok(snapshot.url.includes('/projects/proj-B/'), 'shared state must belong to B');
  assert.equal(
    snapshot.payload.slides[0].beats[0].tts_text,
    'B原文',
    'stale load response must not overwrite project B narration',
  );

  // AI 标注同族：请求已发出，切换后响应到达，不得应用。
  box.route('/api/projects/proj-A', () => projectFixture('proj-A'));
  box.state.currentProject = projectFixture('proj-A');
  box.route('/api/projects/proj-A/steps/6/result', () => ({ success: true, beats: beatsFor('A原文') }));
  await box.loadStep6Data();
  const deferredAnnotate = deferred();
  box.route('/api/projects/proj-A/steps/6/annotate', () => deferredAnnotate.promise);
  const annotating = box.annotateStep6Narration();
  await Promise.resolve();
  routeProjectB(box);
  await box.enterWorkspace('proj-B');
  deferredAnnotate.resolve({ success: true, beats: beatsFor('A标注结果'), annotated_count: 1 });
  await annotating;
  const snapshotAfter = await snapshotNarrationState(box);
  assert.ok(snapshotAfter.url.includes('/projects/proj-B/'));
  assert.equal(
    snapshotAfter.payload.slides[0].beats[0].tts_text,
    'B原文',
    'stale annotation must not overwrite project B narration',
  );
}

// ---------- 场景 4：始终留在 A，自动保存 / 初始化 / 标注 / 音频展示正常 ----------
async function scenarioHappyPathUnchanged() {
  const box = createSandbox();
  box.state.currentProject = projectFixture('proj-A');
  box.openWorkspace();
  // 保存成功路径会调用真实的 refreshCurrentProjectStatus 拉取项目详情。
  box.route('/api/projects/proj-A', () => projectFixture('proj-A'));
  box.route('/api/projects/proj-A/steps/6/result', () => ({ success: true, beats: beatsFor('A原文') }));
  await box.loadStep6Data();

  box.updateNarrationBeatText(0, 0, 'A修改后');
  box.drainTimers();
  await box.state.step6AutoSavePromise;
  const puts = box.fetchLog.filter(call => call.url === '/api/projects/proj-A/steps/6/result');
  assert.equal(puts.length, 1, 'autosave must PUT once to project A');
  const payload = JSON.parse(puts[0].options.body);
  assert.equal(payload.slides[0].beats[0].tts_text, 'A修改后');
  assert.equal(box.element('step6-autosave-status').innerText, '已自动保存');

  // 音频状态展示：槽位按 slide_id 匹配并渲染 <audio>。
  const slot = box.registerAudioSlot('slide_001');
  box.route('/api/projects/proj-A/steps/3/images', () => ({ success: true, images: [{ slide_id: 'slide_001' }] }));
  box.route('/api/projects/proj-A/steps/7/audio-status', () => ({
    slides: [{ slide_id: 'slide_001', audio_exists: true, stale: false }],
    complete: true,
  }));
  await box.loadStep7Data();
  assert.ok(slot.innerHTML.includes('<audio'), 'audio player must render for the current project');
  assert.ok(slot.innerHTML.includes('/api/projects/proj-A/slides/slide_001/audio'), 'audio URL must target project A');

  // Step 1：加载与生成正常回填。
  box.route('/api/projects/proj-A/steps/1/result', () => ({
    success: true,
    brief: { content: '文章正文', title: '标题', summary: '摘要' },
  }));
  await box.loadStep1Data();
  assert.equal(box.element('step1-article-input').value, '文章正文');

  box.document.getElementById('step1-topic-input').value = '测试话题';
  box.route('/api/projects/proj-A/steps/1/generate-article', () => ({ success: true, content: '新生成文章' }));
  await box.generateStep1Article();
  assert.equal(box.element('step1-article-input').value, '新生成文章');
}

async function scenarioArticleImportScope() {
  for (const destination of ['other', 'exit', 'return', 'same']) {
    const box = createSandbox();
    box.state.currentProject = projectFixture('proj-A');
    box.openWorkspace();
    // Use a plain text editor stub while running the real submit function.
    box.syncStep1MarkdownToSource = () => 'A article';
    box.updateStepperUI = () => {};
    const navigations = [];
    box.navigateToStep = async step => navigations.push(step);
    const pending = deferred();
    box.route('/api/projects/proj-A/steps/1/import', () => pending.promise);
    const importing = box.submitStep1();
    assert.equal(box.apiLog.post[0].url, '/api/projects/proj-A/steps/1/import');
    const target = projectFixture('proj-B');
    if (destination !== 'same') {
      vm.runInContext('workspaceNavigationVersion += 1', vm.createContext(box));
      box.state.currentProject = destination === 'exit' ? null : target;
      box.resetProjectScopedAsyncUi();
      if (destination === 'return') box.state.currentProject = projectFixture('proj-A');
      box.document.getElementById('step1-btn-submit').innerHTML = 'new session';
      box.document.getElementById('step1-res-title').value = 'new title';
    }
    pending.resolve({ success: true, brief: { title: 'A title', summary: '' } });
    await importing;
    if (destination === 'same') {
      assert.equal(box.element('step1-res-title').value, 'A title');
      assert.deepEqual(navigations, [2]);
      assert.equal(box.state.currentProject.step_status['1'], 'completed');
    } else {
      assert.equal(box.element('step1-res-title').value, 'new title');
      assert.equal(box.element('step1-btn-submit').innerHTML, 'new session');
      assert.deepEqual(navigations, []);
      assert.equal(target.step_status['1'], undefined);
    }
  }
  const closed = createSandbox();
  await closed.submitStep1();
  assert.equal(closed.apiLog.post.length, 0);
}

(async () => {
  await scenarioSwitchWithinDebounce();
  await scenarioRetryStaysOnOriginalProject();
  await scenarioStaleResponsesDoNotOverwrite();
  await scenarioHappyPathUnchanged();
  await scenarioArticleImportScope();
  console.log('narration project scope checks passed');
})().catch(error => {
  console.error(error);
  process.exit(1);
});
