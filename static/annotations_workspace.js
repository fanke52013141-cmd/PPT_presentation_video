// 勾画标注工作区(可见步骤 6，内部 Step 10):项目/页面生命周期、三栏渲染、选中联动、
// 自动保存与冲突处理。纯逻辑在 annotations_core.js;画布交互与属性编辑在
// annotations_editor.js;本模块不实现业务算法,只做编排与渲染。

const ANNOTATIONS_WS = {
  projectId: '',
  slideIds: [],
  activeIndex: 0,
  summary: null,
  settingsRevision: 0,
  page: { slide_id: '', revision: 0, items: [] },
  pendingOps: [],
  saveTimer: null,
  saveInFlight: false,
  saveGeneration: 0,
  pageGeneration: 0,
  histories: {},
  selectedAnnotationId: null,
  loading: false,
  // 422 被拒绝的操作:与待存队列隔离,由用户显式重试或丢弃
  failedOps: [],
  failedOpsMessage: '',
  // 409 冲突:保留被拒批次与服务端当前 revision,等待用户恢复
  conflict: null,
  // 跨项目/跨页暂存:`${projectId}::${slideId}` -> 未保存操作
  draftOps: {},
  // 讲稿文本选区暂存:先选旁白文字、再点文字候选时直接带上锚点
  pendingNarrationAnchor: null,
};

function annotationsApiBase(projectId = ANNOTATIONS_WS.projectId) {
  return `/api/projects/${projectId}/annotations`;
}

// 本地临时条目 id:时间戳+自增序号,避免同一毫秒内的两条标注 id 碰撞。
function nextLocalAnnotationId() {
  ANNOTATIONS_WS.localSeq = (ANNOTATIONS_WS.localSeq || 0) + 1;
  return `local_${Date.now()}_${ANNOTATIONS_WS.localSeq}`;
}

// ------------------------------------------------------------ 项目生命周期

function resetAnnotationsProjectState() {
  window.cancelAnnotationRepair?.();
  ++ANNOTATIONS_WS.saveGeneration;
  ++ANNOTATIONS_WS.pageGeneration;
  clearTimeout(ANNOTATIONS_WS.saveTimer);
  ANNOTATIONS_WS.saveTimer = null;
  // 被拒/在途操作在切换项目时无法跟随(draftOps 只按 project+slide 暂存
  // 合法 pending 操作),显式告知用户而非静默丢弃。
  if (ANNOTATIONS_WS.failedOps.length) {
    showToast(`已离开勾画页:${ANNOTATIONS_WS.failedOps.length} 条被拒绝的修改未保留。`, 5000);
  }
  ANNOTATIONS_WS.pendingOps = [];
  ANNOTATIONS_WS.saveInFlight = false;
  ANNOTATIONS_WS.savePromise = null;
  ANNOTATIONS_WS.failedOps = [];
  ANNOTATIONS_WS.failedOpsMessage = '';
  ANNOTATIONS_WS.conflict = null;
  // draftOps 按 project+slide 键控,跨项目保留用户未保存工作
  ANNOTATIONS_WS.histories = {};
  ANNOTATIONS_WS.projectId = '';
  ANNOTATIONS_WS.slideIds = [];
  ANNOTATIONS_WS.summary = null;
  ANNOTATIONS_WS.page = { slide_id: '', revision: 0, items: [] };
  ANNOTATIONS_WS.selectedAnnotationId = null;
  ANNOTATIONS_WS.pendingNarrationAnchor = null;
  if (typeof cancelAnnotationPreviewLoop === 'function') cancelAnnotationPreviewLoop();
  window.__annotationsEnabled = false;
  window.__annotationModuleState = 'not_started';
  renderAnnotationSaveStatus('idle');
}

function annotationDraftKey(projectId, slideId) {
  return `${projectId || ''}::${slideId || ''}`;
}

function stashAnnotationDraft(projectId, slideId, operations) {
  const ops = (operations || []).filter(Boolean);
  if (!projectId || !slideId || !ops.length) return;
  const key = annotationDraftKey(projectId, slideId);
  ANNOTATIONS_WS.draftOps[key] = [...(ANNOTATIONS_WS.draftOps[key] || []), ...ops];
}

// 保存期间的上下文三重守卫:请求代次、项目、页面任一变化即视为过期。
function annotationContextChanged(generation, projectId, slideId) {
  return generation !== ANNOTATIONS_WS.saveGeneration
    || ANNOTATIONS_WS.projectId !== projectId
    || ANNOTATIONS_WS.page.slide_id !== slideId;
}

// local_ 临时 id 的目标内容指纹(与 operationAlreadyApplied 同一组字段,
// 不取整个 target:自由笔迹的 path_points 不会原样回到服务端响应)。
function annotationTargetFingerprint(item) {
  const target = item?.target || {};
  return JSON.stringify([
    target.kind ?? null,
    target.granularity ?? null,
    target.polygons ?? null,
    target.token_ids ?? null,
    target.quote ?? null,
  ]);
}

// 保存成功后本地临时 id 已在服务端定型。把仍在队列/隔离区里引用 local_ id
// 的操作重写到新服务端 id(在飞窗口内的撤销/编辑),否则下一轮 flush 必然
// 以 unknown_id 整批被拒。已定型的 add 直接撤下。
function remapAnnotationLocalOps(batchOperations, responseItems) {
  const map = new Map();
  const usedIds = new Set();
  (Array.isArray(batchOperations) ? batchOperations : []).forEach(op => {
    if (!op || op.op !== 'add' || typeof op.__local_id !== 'string') return;
    const fingerprint = annotationTargetFingerprint(op.item);
    const match = (responseItems || []).find(item => {
      if (usedIds.has(item.annotation_id)) return false;
      return annotationTargetFingerprint(item) === fingerprint;
    });
    if (match) {
      map.set(op.__local_id, match.annotation_id);
      usedIds.add(match.annotation_id);
    }
  });
  if (!map.size) return;
  const rewrite = operations => operations
    .filter(op => !(op && op.op === 'add' && typeof op.__local_id === 'string' && map.has(op.__local_id)))
    .map(op => {
      if (op && typeof op.annotation_id === 'string'
        && op.annotation_id.startsWith('local_') && map.has(op.annotation_id)) {
        return { ...op, annotation_id: map.get(op.annotation_id) };
      }
      return op;
    });
  ANNOTATIONS_WS.pendingOps = rewrite(ANNOTATIONS_WS.pendingOps);
  ANNOTATIONS_WS.failedOps = rewrite(ANNOTATIONS_WS.failedOps);
}

async function flushAnnotationsSave() {
  window.flushAnnotationEditorEdits?.();
  const projectId = ANNOTATIONS_WS.projectId;
  const slideId = ANNOTATIONS_WS.page.slide_id;
  if (ANNOTATIONS_WS.savePromise) await ANNOTATIONS_WS.savePromise;
  while (projectId === ANNOTATIONS_WS.projectId && slideId === ANNOTATIONS_WS.page.slide_id) {
    if (ANNOTATIONS_WS.savePromise) {
      await ANNOTATIONS_WS.savePromise;
      continue;
    }
    window.flushAnnotationEditorEdits?.();
    window.finishAnnotationFreehand?.();
    if (!ANNOTATIONS_WS.pendingOps.length || ANNOTATIONS_WS.failedOps.length || ANNOTATIONS_WS.conflict) return;
    const promise = saveAnnotationBatch();
    ANNOTATIONS_WS.savePromise = promise;
    try { await promise; } finally {
      if (ANNOTATIONS_WS.savePromise === promise) ANNOTATIONS_WS.savePromise = null;
    }
  }
}

async function saveAnnotationBatch() {
  window.finishAnnotationFreehand?.();
  if (!ANNOTATIONS_WS.projectId || !ANNOTATIONS_WS.page.slide_id) return;
  if (ANNOTATIONS_WS.saveInFlight || !ANNOTATIONS_WS.pendingOps.length) {
    return;
  }
  clearTimeout(ANNOTATIONS_WS.saveTimer);
  ANNOTATIONS_WS.saveTimer = null;
  const generation = ++ANNOTATIONS_WS.saveGeneration;
  const projectId = ANNOTATIONS_WS.projectId;
  const slideId = ANNOTATIONS_WS.page.slide_id;
  // 本地条目的 update/delete 合并进对应 add,避免服务端 unknown_id 整批拒绝
  const coalesced = AnnotationsCore.coalesceLocalOperations(
    ANNOTATIONS_WS.pendingOps,
    ANNOTATIONS_WS.failedOps,
    null,
    localId => {
      const itemIndex = (ANNOTATIONS_WS.page.items || []).findIndex(item => item.annotation_id === localId);
      if (itemIndex >= 0) ANNOTATIONS_WS.page.items.splice(itemIndex, 1);
    }
  );
  const operations = coalesced.operations;
  ANNOTATIONS_WS.failedOps = coalesced.failedOps;
  ANNOTATIONS_WS.pendingOps = [];
  const expectedRevision = ANNOTATIONS_WS.page.revision;
  if (!operations.length) {
    renderAnnotationSaveStatus(ANNOTATIONS_WS.failedOps.length ? 'invalid' : 'idle');
    return;
  }
  ANNOTATIONS_WS.saveInFlight = true;
  renderAnnotationSaveStatus('saving');
  let res = null;
  let error = null;
  try {
    res = await API.patch(
      `${annotationsApiBase(projectId)}/slides/${encodeURIComponent(slideId)}`,
      { expected_revision: expectedRevision, operations },
      { silent: true }
    );
  } catch (err) {
    error = err;
  }

  // ---- 过期响应:绝不触碰当前(可能已属于其他项目/页面)的状态 ----
  if (annotationContextChanged(generation, projectId, slideId)) {
    // 代次仍归属本次请求(仅切页,未开新 flush)时必须复位在飞标志,
    // 否则自动保存永久停摆(B1);项目已切换时由新上下文自管标志。
    if (generation === ANNOTATIONS_WS.saveGeneration) {
      ANNOTATIONS_WS.saveInFlight = false;
    }
    if (error !== null) {
      // 旧上下文的失败批次:归属原页草稿,等待用户回到该页时恢复
      stashAnnotationDraft(projectId, slideId, operations);
    }
    // 旧上下文的成功响应:成果已在服务端,无需暂存(回页时重新加载即可)
    return;
  }

  // ---- 当前上下文:成功路径(状态更新与渲染分离,R4-002) ----
  if (error === null) {
    ANNOTATIONS_WS.page.revision = res.revision;
    ANNOTATIONS_WS.page.items = res.items;
    remapAnnotationLocalOps(operations, res.items || []);
    ANNOTATIONS_WS.saveInFlight = false;
    ANNOTATIONS_WS.conflict = null;
    delete ANNOTATIONS_WS.draftOps[annotationDraftKey(projectId, slideId)];
    // 服务端条目已替换本地临时 id;选中态失效时就近改选最后一项
    const selectionMissing = !(res.items || []).some(entry => entry.annotation_id === ANNOTATIONS_WS.selectedAnnotationId);
    if (selectionMissing) {
      ANNOTATIONS_WS.selectedAnnotationId = (res.items || []).length
        ? res.items[res.items.length - 1].annotation_id
        : null;
    }
    renderAnnotationSaveStatus(ANNOTATIONS_WS.pendingOps.length || ANNOTATIONS_WS.failedOps.length ? 'pending' : 'saved');
    // UI 渲染故障绝不影响保存结果,也绝不触发操作重发(R4-002)
    try {
      renderAnnotationItems();
      renderAnnotationOverlay();
      renderAnnotationNarrationHighlights();
      if (typeof renderAnnotationItemEditor === 'function') renderAnnotationItemEditor();
      refreshAnnotationsStepFlag();
    } catch (renderError) {
      console.error('annotation render failed after save:', renderError);
    }
    return;
  }

  // ---- 当前上下文:失败路径(R4-003/R4-006) ----
  ANNOTATIONS_WS.saveInFlight = false;
  const failure = AnnotationsCore.classifyPatchFailure(error.status, error.body);
  if (failure.kind === 'revision_conflict') {
    ANNOTATIONS_WS.conflict = {
      projectId,
      slideId,
      operations,
      currentRevision: failure.currentRevision,
    };
    renderAnnotationSaveStatus('conflict', failure.message);
    showToast(`保存失败：${failure.message} 点击状态条可载入服务端版本并重放。`);
  } else if (failure.kind === 'validation_failed') {
    // 422:被拒操作隔离到失败草稿,不自动重试也不静默丢弃
    ANNOTATIONS_WS.failedOps = [...ANNOTATIONS_WS.failedOps, ...operations];
    const first = failure.issues?.[0];
    ANNOTATIONS_WS.failedOpsMessage = first ? `${first.path} ${first.message}` : failure.message;
    renderAnnotationSaveStatus('invalid', `${ANNOTATIONS_WS.failedOpsMessage}(点击状态条可重试)`);
    showToast(`保存被拒绝:${ANNOTATIONS_WS.failedOpsMessage}`);
  } else {
    // 网络/5xx:结果未知。重取服务端页面做内容去重:已生效的操作直接落账,
    // 未生效的放回队列等待显式重试(点击状态条或下一次编辑)。
    let remaining = operations;
    let appliedOnServer = false;
    try {
      const page = await API.get(`${annotationsApiBase(projectId)}/slides/${encodeURIComponent(slideId)}`, { silent: true });
      if (!annotationContextChanged(generation, projectId, slideId)) {
        const deduped = AnnotationsCore.dedupeOperationsAgainstPage(operations, page.items || []);
        remaining = deduped.remaining;
        appliedOnServer = deduped.applied.length > 0;
        // 服务端真值始终落账:重试以最新 revision 发起,避免必败的 409 循环(B3)
        ANNOTATIONS_WS.page.revision = page.revision || ANNOTATIONS_WS.page.revision;
        ANNOTATIONS_WS.page.items = page.items || [];
        if (!remaining.length) {
          appliedOnServer = true;
        }
      }
    } catch (refetchError) {
      /* 服务端不可达:全部操作按未生效处理 */
    }
    if (remaining.length) {
      ANNOTATIONS_WS.pendingOps = [...remaining, ...ANNOTATIONS_WS.pendingOps];
      renderAnnotationSaveStatus(appliedOnServer ? 'pending' : 'error', failure.message);
      showToast(`保存失败：${failure.message} 保存内容已保留,点击状态条重试。`);
    } else {
      ANNOTATIONS_WS.saveInFlight = false;
      renderAnnotationSaveStatus('saved');
      try {
        renderAnnotationItems();
        renderAnnotationOverlay();
        renderAnnotationNarrationHighlights();
        if (typeof renderAnnotationItemEditor === 'function') renderAnnotationItemEditor();
      } catch (renderError) {
        console.error('annotation render failed after dedupe:', renderError);
      }
    }
  }
  throw error;
}

// 409 恢复:载入服务端版本,重放被拒批次;重放仍被拒的部分走 422 隔离。
async function resolveAnnotationConflict() {
  const conflict = ANNOTATIONS_WS.conflict;
  if (!conflict) return;
  const projectId = ANNOTATIONS_WS.projectId;
  const slideId = ANNOTATIONS_WS.page.slide_id;
  if (conflict.projectId !== projectId || conflict.slideId !== slideId) {
    ANNOTATIONS_WS.conflict = null;
    return;
  }
  let page;
  try {
    page = await API.get(`${annotationsApiBase(projectId)}/slides/${encodeURIComponent(slideId)}`);
  } catch (error) {
    showToast('载入服务端版本失败,请稍后重试。');
    return;
  }
  if (ANNOTATIONS_WS.conflict !== conflict
    || ANNOTATIONS_WS.projectId !== projectId
    || ANNOTATIONS_WS.page.slide_id !== slideId) {
    return;
  }
  ANNOTATIONS_WS.page.revision = page.revision || 0;
  ANNOTATIONS_WS.page.items = page.items || [];
  ANNOTATIONS_WS.conflict = null;
  ANNOTATIONS_WS.pendingOps = [...(conflict.operations || []), ...ANNOTATIONS_WS.pendingOps];
  renderAnnotationSaveStatus('pending');
  try {
    renderAnnotationItems();
    renderAnnotationOverlay();
  } catch (renderError) {
    console.error('annotation render failed after conflict reload:', renderError);
  }
  await flushAnnotationsSave().catch(() => {});
}

// 422 隔离区重试:由用户显式触发(点击状态条),单次有界。
async function retryAnnotationFailedOps() {
  if (!ANNOTATIONS_WS.failedOps.length) return;
  ANNOTATIONS_WS.pendingOps = [...ANNOTATIONS_WS.failedOps, ...ANNOTATIONS_WS.pendingOps];
  ANNOTATIONS_WS.failedOps = [];
  ANNOTATIONS_WS.failedOpsMessage = '';
  await flushAnnotationsSave().catch(() => {});
}

// 422 隔离区丢弃:被拒操作在修正前会阻塞本页所有自动保存(flush 见
// failedOps 非空即返回)。当用户无法/不想修正时,显式丢弃被拒操作,
// 让 pendingOps 中的合法编辑恢复落盘,避免整页死锁与退出时静默丢失。
async function discardAnnotationFailedOps() {
  if (!ANNOTATIONS_WS.failedOps.length) return;
  const count = ANNOTATIONS_WS.failedOps.length;
  let confirmed = false;
  if (typeof window.showCustomConfirm === 'function') {
    confirmed = await new Promise(resolve => {
      window.showCustomConfirm(
        '丢弃被拒绝的修改',
        `有 ${count} 条修改因内容非法被服务端拒绝（${ANNOTATIONS_WS.failedOpsMessage || '原因见上方提示'}）。丢弃后这些修改将不可恢复，其余未保存的编辑会继续自动保存。`,
        () => resolve(true),
        () => resolve(false),
      );
    });
  } else {
    confirmed = window.confirm(`丢弃 ${count} 条被拒绝的修改？此操作不可恢复。`);
  }
  if (!confirmed) return;
  ANNOTATIONS_WS.failedOps = [];
  ANNOTATIONS_WS.failedOpsMessage = '';
  renderAnnotationSaveStatus(ANNOTATIONS_WS.pendingOps.length ? 'pending' : 'idle');
  await flushAnnotationsSave().catch(() => {});
}

function queueAnnotationSave(operationOrList) {
  const operations = Array.isArray(operationOrList) ? operationOrList : [operationOrList];
  if (!operations.length) return;
  ANNOTATIONS_WS.editGeneration = (ANNOTATIONS_WS.editGeneration || 0) + 1;
  ANNOTATIONS_WS.pendingOps.push(...operations.filter(Boolean));
  renderAnnotationSaveStatus('pending');
  clearTimeout(ANNOTATIONS_WS.saveTimer);
  ANNOTATIONS_WS.saveTimer = setTimeout(() => {
    flushAnnotationsSave().catch(() => {});
  }, 700);
}

// ------------------------------------------------------------ 数据加载

async function loadStep10Data() {
  const projectId = state.currentProject?.id;
  if (!projectId) return;
  await flushAnnotationsSave().catch(() => {});
  resetAnnotationsProjectState();
  ANNOTATIONS_WS.projectId = projectId;
  ANNOTATIONS_WS.loading = true;
  try {
    const diagnostics = await API.get('/api/runtime/diagnostics', {silent: true});
    if (diagnostics.annotation_runtime?.version !== 'annotation_batch_bcd_v1'
        || !diagnostics.annotation_runtime?.ready) {
      showToast('勾画服务版本未就绪，请重启应用服务后刷新页面。');
      ANNOTATIONS_WS.runtimeBlocked = true;
      renderAnnotationMissingState();
      return;
    }
    ANNOTATIONS_WS.runtimeBlocked = false;
    await reloadAnnotationsSummary();
    if (ANNOTATIONS_WS.slideIds.length) {
      await selectAnnotationPage(0);
    }
  } finally {
    ANNOTATIONS_WS.loading = false;
  }
}

async function reloadAnnotationsSummary(optional = false) {
  const projectId = ANNOTATIONS_WS.projectId;
  const summary = await (optional ? API.getOptional(annotationsApiBase(projectId)) : API.get(annotationsApiBase(projectId)));
  if (optional && summary?.success === false) return;
  // 响应返回时项目已切换:丢弃过期 summary,不污染新项目状态(R4-005)
  if (!projectId || ANNOTATIONS_WS.projectId !== projectId) return;
  ANNOTATIONS_WS.summary = summary;
  ANNOTATIONS_WS.settingsRevision = summary?.settings?.revision || 0;
  ANNOTATIONS_WS.slideIds = (summary?.slides || []).map(item => item.slide_id);
  const enabledToggle = document.getElementById('annotation-enabled-toggle');
  if (enabledToggle) enabledToggle.checked = summary?.settings?.enabled === true;
  const emphasis = document.getElementById('annotation-ai-emphasis');
  if (emphasis) emphasis.value = summary?.settings?.defaults?.emphasis || 'moderate';
  updateAnnotationDecisionButton();
  refreshAnnotationsStepFlag();
}

// Restore the saved decision even when reopening directly into Output.
async function loadAnnotationWorkflowState(projectId) {
  if (!projectId || state.currentProject?.id !== projectId) return;
  ANNOTATIONS_WS.projectId = projectId;
  await reloadAnnotationsSummary(true);
}

window.loadAnnotationWorkflowState = loadAnnotationWorkflowState;

function refreshAnnotationsStepFlag() {
  const enabled = ANNOTATIONS_WS.summary?.settings?.enabled === true;
  const moduleState = ANNOTATIONS_WS.summary?.module_state || 'not_started';
  const changed = window.__annotationsEnabled !== enabled || window.__annotationModuleState !== moduleState;
  window.__annotationsEnabled = enabled;
  window.__annotationModuleState = moduleState;
  if (changed && state.currentProject && typeof updateStepperUI === 'function') {
    updateStepperUI(state.currentStep, state.currentProject.step_status || {});
  }
}

function refreshAnnotationModuleState() {
  refreshAnnotationsStepFlag();
}

// ------------------------------------------------------------ 决策与逐页确认

function updateAnnotationDecisionButton() {
  const button = document.getElementById('annotation-btn-decision');
  if (!button) return;
  const decision = ANNOTATIONS_WS.summary?.settings?.decision || 'none';
  button.textContent = decision === 'no_annotations' ? '恢复勾画决策' : '本项目不加勾画';
}

function requestAnnotationDecision() {
  const current = ANNOTATIONS_WS.summary?.settings?.decision || 'none';
  if (current !== 'no_annotations') {
    showCustomConfirm('本项目不加勾画', '将把本项目标记为"明确不使用勾画标注",本步骤视为完成;已有草稿会保留,随时可恢复。', () => {
      setAnnotationDecision('no_annotations');
    });
    return;
  }
  setAnnotationDecision('none');
}

async function setAnnotationDecision(decision) {
  const projectId = ANNOTATIONS_WS.projectId;
  if (!projectId) return;
  try {
    const res = await API.put(`${annotationsApiBase()}/settings`, {
      expected_revision: ANNOTATIONS_WS.settingsRevision,
      enabled: ANNOTATIONS_WS.summary?.settings?.enabled === true,
      decision,
    }, { silent: true });
    if (ANNOTATIONS_WS.projectId !== projectId) return;
    ANNOTATIONS_WS.settingsRevision = res.revision;
    if (ANNOTATIONS_WS.summary?.settings) {
      ANNOTATIONS_WS.summary.settings.decision = res.decision;
      ANNOTATIONS_WS.summary.settings.revision = res.revision;
    }
    refreshAnnotationModuleState();
    updateAnnotationDecisionButton();
    showToast(decision === 'no_annotations' ? '已记录:本项目不添加勾画。' : '已恢复勾画决策。');
  } catch (error) {
    showToast(`决策保存失败：${error.message || '未知错误'}`);
  }
}

function updateAnnotationConfirmButton() {
  const button = document.getElementById('annotation-btn-confirm-page');
  if (!button) return;
  const items = ANNOTATIONS_WS.page.items || [];
  const active = items.filter(item => item.status?.content !== 'disabled');
  if (!active.length) {
    button.disabled = true;
    button.textContent = '确认本页';
    return;
  }
  const allConfirmed = active.every(item => item.status?.content === 'confirmed');
  button.disabled = Boolean(ANNOTATIONS_WS.activeJob);
  button.textContent = allConfirmed ? '重新确认本页' : '确认本页';
}

function annotationTimelineErrorText(error) {
  const text = String(error || '');
  if (text === 'audio_timeline_missing') return '该页还没有音频时间轴';
  if (text === 'text_layout_missing') return '文字布局缺失,请重新识别文字';
  if (text.startsWith('unconfirmed:')) return '仍有未确认条目';
  return '构建失败';
}

async function submitAnnotationConfirm(projectId, slideId, acceptedReviewIds) {
  let res;
  const editGeneration = ANNOTATIONS_WS.editGeneration || 0;
  try {
    res = await API.post(
      `${annotationsApiBase(projectId)}/slides/${encodeURIComponent(slideId)}/confirm`,
      { expected_revision: ANNOTATIONS_WS.page.revision, accepted_review: acceptedReviewIds,
        prepared_build_id: typeof ANNOTATION_PREVIEW !== 'undefined'
          && ANNOTATION_PREVIEW.prepared?.projectId === projectId
          && ANNOTATION_PREVIEW.prepared?.slideId === slideId
          && ANNOTATION_PREVIEW.prepared?.revision === ANNOTATIONS_WS.page.revision
          ? ANNOTATION_PREVIEW.prepared.result.build_id : undefined },
      { silent: true }
    );
  } catch (error) {
    if (error?.status === 409) {
      showToast('页面已被其他窗口修改,正在重新加载。');
      await selectAnnotationPage(ANNOTATIONS_WS.activeIndex).catch(() => {});
      return;
    }
    const detail = error?.body?.detail;
    if (error?.status === 422 && detail?.code === 'review_required'
      && Array.isArray(detail.items) && detail.items.length && !acceptedReviewIds.length) {
      showCustomConfirm('确认含复核项的标注',
        `有 ${detail.items.length} 条标注带几何复核提示(如整行降级识别)。确认后将按当前形态带入视频。`,
        () => { submitAnnotationConfirm(projectId, slideId, detail.items.map(entry => entry.annotation_id)); });
      return;
    }
    showToast(`确认失败：${typeof annotationPrepareError === 'function' ? annotationPrepareError(error) : error?.message || '未知错误'}`);
    return;
  }
  if (ANNOTATIONS_WS.projectId !== projectId || ANNOTATIONS_WS.page.slide_id !== slideId) return;
  window.flushAnnotationEditorEdits?.();
  if (editGeneration !== (ANNOTATIONS_WS.editGeneration || 0)) {
    ANNOTATIONS_WS.page.revision = res.revision;
    showToast('确认期间标注已修改，请保存并重新预览确认。');
    return;
  }
  ANNOTATIONS_WS.page.revision = res.revision;
  (ANNOTATIONS_WS.page.items || []).forEach(item => {
    if (item.status?.content !== 'disabled') {
      item.status = { ...(item.status || {}), content: 'confirmed' };
    }
  });
  // Read the authoritative timing status as well as the confirmation revision.
  await selectAnnotationPage(ANNOTATIONS_WS.activeIndex);
  await reloadAnnotationsSummary().catch(() => {});
  if (res.timeline_built) {
    showToast(`已确认本页 ${res.confirmed} 条标注,动画时间轴已生成。`);
  } else if (res.timeline_error) {
    showToast(`已确认本页 ${res.confirmed} 条标注;时间轴暂未生成(${annotationTimelineErrorText(res.timeline_error)}),生成音频后重新确认即可。`);
  } else {
    showToast(`已确认本页 ${res.confirmed} 条标注。`);
  }
}

async function confirmAnnotationPage() {
  if (window.annotationRepairPending?.()) {
    showToast('请先完成重画，或取消重画，再确认本页。');
    return;
  }
  const projectId = ANNOTATIONS_WS.projectId;
  const slideId = ANNOTATIONS_WS.page.slide_id;
  if (!projectId || !slideId) return;
  if (annotationPrerequisitesBlocked()) return;
  // 确认必须基于服务端当前版本:先把未保存编辑落盘
  await flushAnnotationsSave().catch(() => {});
  if (ANNOTATIONS_WS.projectId !== projectId || ANNOTATIONS_WS.page.slide_id !== slideId) return;
  if (ANNOTATIONS_WS.conflict || ANNOTATIONS_WS.failedOps.length || ANNOTATIONS_WS.pendingOps.length) {
    showToast('当前页还有未保存或未解决的编辑,请先处理保存状态再确认。');
    return;
  }
  const active = (ANNOTATIONS_WS.page.items || []).filter(item => item.status?.content !== 'disabled');
  if (annotationTriggerNeedsSelection(active)) return;
  if (!active.length) {
    showToast('当前页没有可确认的标注。');
    return;
  }
  const reviewBlocked = active.filter(item =>
    item.status?.spatial === 'needs_review' || (item.review_issues?.length));
  if (reviewBlocked.length) {
    showCustomConfirm('确认含复核项的标注',
      `有 ${reviewBlocked.length} 条标注带几何复核提示(如整行降级识别)。确认后将按当前形态带入视频。`,
      () => { submitAnnotationConfirm(projectId, slideId, reviewBlocked.map(item => item.annotation_id)); });
    return;
  }
  await submitAnnotationConfirm(projectId, slideId, []);
}

function annotationTriggerNeedsSelection(items = ANNOTATIONS_WS.page.items || []) {
  const unresolved = items.filter(item => item.status?.content !== 'disabled'
    && !item.anchor && item.status?.content !== 'confirmed'
    && !(item.protection?.modified_fields || []).includes('timing'));
  if (!unresolved.length) return false;
  showToast('请为未关联标注选择讲稿，或明确设置指定起笔时间后再预览确认。');
  return true;
}

async function selectAnnotationPage(index) {
  window.cancelAnnotationRepair?.();
  window.finishAnnotationFreehand?.();
  const projectId = ANNOTATIONS_WS.projectId;
  const previousSlideId = ANNOTATIONS_WS.page.slide_id;
  // 离开当前页:flush 尽力而为;残留的未保存操作(含冲突/被拒批次)归属原页草稿,
  // 冲突未处理不得静默丢弃本地工作(R4-005)
  await flushAnnotationsSave().catch(() => {});
  const leftovers = [...ANNOTATIONS_WS.pendingOps, ...ANNOTATIONS_WS.failedOps];
  if (ANNOTATIONS_WS.conflict && ANNOTATIONS_WS.conflict.projectId === projectId
    && ANNOTATIONS_WS.conflict.slideId === previousSlideId) {
    leftovers.push(...ANNOTATIONS_WS.conflict.operations);
  }
  stashAnnotationDraft(projectId, previousSlideId, leftovers);
  ANNOTATIONS_WS.pendingOps = [];
  ANNOTATIONS_WS.failedOps = [];
  ANNOTATIONS_WS.failedOpsMessage = '';
  ANNOTATIONS_WS.conflict = null;
  const slideId = ANNOTATIONS_WS.slideIds[index];
  if (!slideId || ANNOTATIONS_WS.projectId !== projectId) return;
  const generation = ++ANNOTATIONS_WS.pageGeneration;
  ANNOTATIONS_WS.activeIndex = index;
  ANNOTATIONS_WS.selectedAnnotationId = null;
  // 跨页的讲稿选区暂存不再适用:锚点必须绑定当前页语块
  ANNOTATIONS_WS.pendingNarrationAnchor = null;
  const page = await API.get(`${annotationsApiBase(projectId)}/slides/${encodeURIComponent(slideId)}`);
  // 过期页面响应丢弃:仅当项目与页面代次都未变化才落账(R4-005)
  if (ANNOTATIONS_WS.projectId !== projectId
    || generation !== ANNOTATIONS_WS.pageGeneration
    || ANNOTATIONS_WS.slideIds[index] !== slideId) {
    return;
  }
  ANNOTATIONS_WS.page = {
    slide_id: slideId,
    revision: page.revision || 0,
    items: page.items || [],
    narration: page.narration || { beats: [] },
    mask_groups: page.mask_groups || [],
    audio_locator: page.audio_locator || {},
    audio_start_sec: Number.isFinite(page.audio_start_sec) ? page.audio_start_sec : 0,
    imageHash: page.image?.hash || null,
    aiSnapshot: page.ai_suggestion_snapshot || null,
  };
  if (!ANNOTATIONS_WS.histories[slideId]) {
    ANNOTATIONS_WS.histories[slideId] = AnnotationsCore.createPageHistory();
  }
  renderAnnotationWorkspace();
  // 恢复该页此前暂存的未保存操作,等待下次 flush
  const draftKey = annotationDraftKey(projectId, slideId);
  if (ANNOTATIONS_WS.draftOps[draftKey]?.length) {
    // 恢复的暂存批次视为一次有界重放:重放仍被拒时走 422 隔离,不无限循环
    const restored = ANNOTATIONS_WS.draftOps[draftKey].map(op => ({
      ...op,
      __conflictAttempt: Math.max(op.__conflictAttempt || 0, 1),
    }));
    ANNOTATIONS_WS.pendingOps.push(...restored);
    delete ANNOTATIONS_WS.draftOps[draftKey];
    renderAnnotationSaveStatus('pending');
  }
  await loadAnnotationCandidates();
}

// ------------------------------------------------------------ 渲染

function renderAnnotationWorkspace() {
  renderAnnotationMissingState();
  if (annotationPrerequisitesBlocked()) return;
  renderAnnotationThumbnails();
  renderAnnotationNarration();
  renderAnnotationItems();
  renderAnnotationOverlay();
  renderAnnotationItemEditor();
}

function annotationPrerequisitesBlocked() {
  const page = ANNOTATIONS_WS.page;
  return ANNOTATIONS_WS.runtimeBlocked === true || !page.imageHash || !(page.narration?.beats?.length);
}

function renderAnnotationMissingState() {
  const missing = document.getElementById('annotation-missing-state');
  const body = document.getElementById('annotation-workspace-body');
  if (!missing || !body) return;
  const blocked = annotationPrerequisitesBlocked();
  missing.style.display = blocked ? 'block' : 'none';
  body.style.display = blocked ? 'none' : 'block';
  if (!blocked) return;
  const reasons = [];
  if (ANNOTATIONS_WS.runtimeBlocked) reasons.push('勾画服务版本未就绪，请重启应用服务并刷新');
  if (!ANNOTATIONS_WS.page.imageHash) reasons.push('当前页面还没有图片');
  if (!(ANNOTATIONS_WS.page.narration?.beats?.length)) reasons.push('当前页面还没有有效讲稿');
  const reason = document.getElementById('annotation-missing-reason');
  if (reason) reason.textContent = `${reasons.join(';')}。补齐后即可编辑勾画。`;
}

function renderAnnotationThumbnails() {
  const strip = document.getElementById('annotation-thumb-strip');
  if (!strip) return;
  strip.innerHTML = '';
  const summaryBySlide = new Map((ANNOTATIONS_WS.summary?.slides || []).map(item => [item.slide_id, item]));
  ANNOTATIONS_WS.slideIds.forEach((slideId, index) => {
    const counts = summaryBySlide.get(slideId)?.counts || { total: 0 };
    const item = document.createElement('button');
    item.type = 'button';
    // 文字页签与 Step 4 的「第 N 页」同构；数量角标保留为已有标注指示
    item.className = `annotation-page-tab${index === ANNOTATIONS_WS.activeIndex ? ' active' : ''}`;
    item.dataset.slideId = slideId;
    item.setAttribute('aria-label', `切换到第 ${index + 1} 页`);
    const label = document.createElement('span');
    label.className = 'page-label';
    label.textContent = `第 ${index + 1} 页`;
    const badge = document.createElement('span');
    badge.className = 'annotation-thumb-badge';
    badge.textContent = counts.total ? String(counts.total) : '';
    item.appendChild(label);
    item.appendChild(badge);
    item.addEventListener('click', () => {
      if (index !== ANNOTATIONS_WS.activeIndex) {
        selectAnnotationPage(index).catch(() => showToast('页面加载失败,请重试。'));
      }
    });
    strip.appendChild(item);
  });
}

function annotationNarrationBeatHtml(beat) {
  const spoken = String(beat.spoken_text || '');
  return `<div class="annotation-beat" data-beat-id="${escHtml(beat.beat_id || '')}" data-spoken="${escHtml(spoken)}">
    <div class="annotation-beat-text">${escHtml(spoken)}</div>
  </div>`;
}

function renderAnnotationNarration() {
  const container = document.getElementById('annotation-narration-beats');
  if (!container) return;
  const beats = ANNOTATIONS_WS.page.narration?.beats || [];
  container.innerHTML = beats.map(annotationNarrationBeatHtml).join('');
  container.querySelectorAll('.annotation-beat').forEach(node => {
    node.addEventListener('mouseup', handleAnnotationNarrationSelection);
  });
  const bind = document.createElement('button');
  bind.type = 'button';
  bind.className = 'secondary compact-action-btn';
  bind.textContent = '将所选讲稿关联到当前标注';
  bind.addEventListener('mousedown', event => event.preventDefault());
  bind.addEventListener('click', () => {
    const anchor = ANNOTATIONS_WS.pendingNarrationAnchor;
    if (!anchor) { showToast('请先选中当前页讲稿中的触发内容。'); return; }
    window.annotationNarrationAnchorPicked?.(anchor);
  });
  container.appendChild(bind);
  renderAnnotationNarrationHighlights();
}

function renderAnnotationNarrationHighlights() {
  const container = document.getElementById('annotation-narration-beats');
  if (!container) return;
  const beats = ANNOTATIONS_WS.page.narration?.beats || [];
  const items = ANNOTATIONS_WS.page.items || [];
  container.querySelectorAll('.annotation-beat').forEach(node => {
    const beat = beats.find(entry => entry.beat_id === node.dataset.beatId);
    if (!beat) return;
    const spoken = String(beat.spoken_text || '');
    const marks = [];
    for (let i = 0; i < spoken.length; i += 1) {
      marks.push(null);
    }
    items.forEach((item, itemIndex) => {
      const anchor = item.anchor;
      if (!anchor || anchor.beat_id !== beat.beat_id) return;
      const utf16Start = AnnotationsCore.codepointIndexToUtf16Index(spoken, anchor.range?.[0] ?? 0);
      const utf16End = AnnotationsCore.codepointIndexToUtf16Index(spoken, anchor.range?.[1] ?? 0);
      for (let i = utf16Start; i < utf16End && i < marks.length; i += 1) {
        marks[i] = itemIndex;
      }
    });
    let html = '';
    let index = 0;
    while (index < marks.length) {
      const owner = marks[index];
      if (owner === null) {
        let end = index;
        while (end < marks.length && marks[end] === null) end += 1;
        html += escHtml(spoken.slice(index, end));
        index = end;
      } else {
        let end = index;
        while (end < marks.length && marks[end] === owner) end += 1;
        const selected = ANNOTATIONS_WS.selectedAnnotationId === items[owner].annotation_id;
        html += `<mark class="annotation-anchor-mark${selected ? ' selected' : ''}" data-owner="${escHtml(items[owner].annotation_id)}">${escHtml(spoken.slice(index, end))}</mark>`;
        index = end;
      }
    }
    node.querySelector('.annotation-beat-text').innerHTML = html || '<span class="annotation-beat-empty">(空语块)</span>';
  });
  container.querySelectorAll('.annotation-anchor-mark').forEach(mark => {
    mark.addEventListener('click', () => {
      selectAnnotationItem(mark.dataset.owner);
    });
  });
}

function handleAnnotationNarrationSelection(event) {
  const selection = window.getSelection();
  const node = event.currentTarget;
  const spoken = node.dataset.spoken || '';
  if (!selection || !selection.rangeCount || !spoken) return;
  const text = selection.toString();
  if (!text.trim()) return;
  const range = selection.getRangeAt(0);
  const measure = document.createElement('span');
  const host = node.querySelector('.annotation-beat-text');
  if (!host || !host.contains(range.commonAncestorContainer)) return;
  measure.innerHTML = '&nbsp;';
  const probeStart = document.createRange();
  probeStart.selectNodeContents(host);
  probeStart.setEnd(range.startContainer, range.startOffset);
  const utf16Start = probeStart.toString().length;
  const utf16End = utf16Start + text.length;
  // 前端预校验锚点长度:契约 quote 上限 200 字符(UTF-16),超限选区
  // 直接拒绝,避免 422 隔离区堵塞本页自动保存。
  if (text.length > 200) {
    ANNOTATIONS_WS.pendingNarrationAnchor = null;
    showToast(`选中的讲稿片段过长（${text.length} 字，上限 200 字），请缩短后再关联。`, 5000);
    return;
  }
  const anchor = AnnotationsCore.buildAnchor(node.dataset.beatId, spoken, utf16Start, utf16End);
  // 暂存选区:先选旁白文字、再点文字候选时直接带上锚点
  ANNOTATIONS_WS.pendingNarrationAnchor = anchor;
  if (typeof window.annotationNarrationAnchorPicked === 'function') {
    window.annotationNarrationAnchorPicked(anchor);
  }
}

function annotationStatusChips(item) {
  const labels = AnnotationsCore.STATUS_LABELS;
  const chips = [`<span class="annotation-chip content-${escHtml(item.status?.content || 'draft')}">${escHtml(labels.content[item.status?.content] || '待确认')}</span>`];
  if (item.status?.spatial && item.status.spatial !== 'valid') chips.push(`<span class="annotation-chip spatial-${escHtml(item.status.spatial)}">${item.status.spatial === 'stale' ? '位置需更新' : '检查勾画范围'}</span>`);
  const temporal = {awaiting_audio: '语音待定位', sentence_fallback: '按整句起笔', failed: '语音定位失败', stale: '起笔时间需更新'};
  if (temporal[item.status?.temporal]) chips.push(`<span class="annotation-chip temporal-${escHtml(item.status.temporal)}">${temporal[item.status.temporal]}</span>`);
  return chips.join('');
}

function renderAnnotationFlow(task) {
  const items = (ANNOTATIONS_WS.page.items || []).filter(item => item.status?.content !== 'disabled');
  const confirmed = items.filter(item => item.status?.content === 'confirmed').length;
  const busy = task ? ['queued', 'running'].includes(task.status) : Boolean(ANNOTATIONS_WS.activeJob);
  const phase = busy || !items.length ? 1 : confirmed === items.length ? 3 : 2;
  document.querySelectorAll('[data-annotation-phase]').forEach(node => {
    const step = Number(node.dataset.annotationPhase);
    node.classList.toggle('is-current', step === phase);
    node.classList.toggle('is-complete', step < phase || (step === 3 && items.length > 0 && confirmed === items.length));
    if (step === phase) node.setAttribute('aria-current', 'step'); else node.removeAttribute('aria-current');
  });
  const count = document.getElementById('annotation-result-count');
  if (count) count.textContent = items.length ? `${items.length} 处勾画 · ${confirmed}/${items.length} 已确认` : '尚未添加';
  const hint = document.getElementById('annotation-next-action');
  if (hint) hint.textContent = busy ? '自动处理完成后，在这里检查勾画结果。' : !items.length ? '点击 AI 勾画本页，自动选择重点并匹配语音。' : confirmed === items.length ? '本页已确认，可切换下一页检查。' : '点击下方勾画调整位置，再用同步预览检查起笔时机。';
  const confirmHint = document.getElementById('annotation-confirm-hint');
  if (confirmHint) confirmHint.textContent = confirmed && confirmed === items.length ? '本页勾画已确认' : '检查预览后确认当前页';
  ['annotation-btn-ai-plan', 'annotation-btn-ai-all'].forEach(id => {
    const button = document.getElementById(id);
    if (button) button.disabled = busy;
  });
  const generate = document.getElementById('annotation-btn-ai-plan');
  if (generate) {
    generate.dataset.hasItems = String(items.length > 0);
    generate.textContent = items.length ? '重新 AI 勾画本页' : 'AI 勾画本页';
  }
  const preview = document.getElementById('annotation-btn-preview');
  if (preview) preview.classList.toggle('annotation-recommended-action', !busy && items.length > 0 && confirmed < items.length);
  const confirm = document.getElementById('annotation-btn-confirm-page');
  if (confirm) confirm.disabled = busy || !items.length;
  const feedback = document.getElementById('annotation-stage-feedback');
  if (feedback) {
    feedback.hidden = !busy;
    const operation = ANNOTATIONS_WS.activeJob?.operation;
    feedback.textContent = busy ? (task?.label || ({detect_text: '正在识别画面文字', plan: '正在选择重点并生成勾画', align: '正在匹配语音与起笔时间'}[operation] || '正在处理勾画')) : '';
  }
}

function renderAnnotationItems() {
  const container = document.getElementById('annotation-items');
  if (!container) return;
  const items = ANNOTATIONS_WS.page.items || [];
  renderAnnotationFlow();
  if (!items.length) {
    container.innerHTML = '<div class="annotation-items-empty"><strong>这页还没有勾画</strong><span>自动勾画后，重点词句会显示在这里。</span></div>';
    updateAnnotationConfirmButton();
    return;
  }
  container.innerHTML = items.map((item, index) => {
    const selected = item.annotation_id === ANNOTATIONS_WS.selectedAnnotationId;
    const quote = item.anchor?.quote || '(未关联讲稿)';
    const lockBadge = item.protection?.locked ? '<span class="annotation-chip locked">🔒 已锁定</span>' : '';
    const disabledBadge = item.status?.content === 'disabled' ? '<span class="annotation-chip disabled-chip">已禁用</span>' : '';
    const reason = item.recommendation?.reason
      ? `<div class="annotation-recommendation">AI 建议：${escHtml(item.recommendation.reason)}</div>`
      : '';
    return `<div class="annotation-card${selected ? ' selected' : ''}${item.status?.content === 'disabled' ? ' is-disabled' : ''}"
        data-annotation-id="${escHtml(item.annotation_id)}" tabindex="0" role="button">
      <div class="annotation-card-title">${escHtml(String(index + 1).padStart(2, '0'))} · ${escHtml(AnnotationsCore.STATUS_LABELS.styleType[item.style?.type] || '勾画')}${lockBadge}${disabledBadge}</div>
      <div class="annotation-card-quote">"${escHtml(quote)}"</div>
      ${reason}
      <div class="annotation-card-status">${annotationStatusChips(item)}</div>
    </div>`;
  }).join('');
  container.querySelectorAll('.annotation-card').forEach(card => {
    card.addEventListener('click', () => selectAnnotationItem(card.dataset.annotationId));
    card.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        selectAnnotationItem(card.dataset.annotationId);
      }
    });
  });
  updateAnnotationConfirmButton();
}

function selectAnnotationItem(annotationId) {
  if (annotationId !== ANNOTATIONS_WS.selectedAnnotationId) window.cancelAnnotationRepair?.();
  window.flushAnnotationEditorEdits?.();
  ANNOTATIONS_WS.selectedAnnotationId = annotationId;
  renderAnnotationItems();
  renderAnnotationOverlay();
  renderAnnotationNarrationHighlights();
  renderAnnotationItemEditor();
  if (typeof window.annotationSelectionChanged === 'function') {
    window.annotationSelectionChanged(annotationId);
  }
}

function renderAnnotationSaveStatus(mode, message = '') {
  const node = document.getElementById('annotation-save-status');
  if (!node) return;
  const map = {
    idle: '',
    pending: '待保存…',
    saving: '保存中…',
    saved: '已保存',
    conflict: '版本冲突,待处理',
    invalid: '内容被拒绝,待修改',
    error: '保存失败,待重试',
  };
  node.dataset.state = mode;
  node.textContent = message || map[mode] || '';
  node.style.display = mode === 'idle' ? 'none' : 'inline-block';
  // 422 被拒操作会阻塞本页所有自动保存,必须同时提供重试与丢弃两个出口。
  if (mode === 'invalid') {
    const discardBtn = document.createElement('button');
    discardBtn.type = 'button';
    discardBtn.className = 'annotation-failed-discard';
    discardBtn.textContent = '丢弃被拒修改';
    discardBtn.title = '丢弃因内容非法被拒绝的修改,恢复其余编辑的自动保存';
    discardBtn.onclick = event => {
      event.stopPropagation();
      discardAnnotationFailedOps().catch(() => {});
    };
    node.appendChild(discardBtn);
  }
  // 状态条可点击恢复:冲突→载入服务端并重放;422→重试被拒操作;网络失败→立即重试
  if (mode === 'conflict') {
    node.title = '点击载入服务端版本并重放保存';
    node.onclick = () => { resolveAnnotationConflict().catch(() => {}); };
  } else if (mode === 'invalid') {
    node.title = '点击重试被拒绝的操作';
    node.onclick = () => { retryAnnotationFailedOps().catch(() => {}); };
  } else if (mode === 'error') {
    node.title = '点击立即重试保存';
    node.onclick = () => { flushAnnotationsSave().catch(() => {}); };
  } else {
    node.title = '';
    node.onclick = null;
  }
}

// ------------------------------------------------------------ 设置开关

async function setAnnotationsEnabled(enabled) {
  const projectId = ANNOTATIONS_WS.projectId;
  if (!projectId) return;
  try {
    const res = await API.put(`${annotationsApiBase(projectId)}/settings`, {
      expected_revision: ANNOTATIONS_WS.settingsRevision,
      enabled: enabled === true,
    }, { silent: true });
    if (ANNOTATIONS_WS.projectId !== projectId) return;
    ANNOTATIONS_WS.settingsRevision = res.revision;
    if (ANNOTATIONS_WS.summary?.settings) {
      ANNOTATIONS_WS.summary.settings.enabled = res.enabled;
      ANNOTATIONS_WS.summary.settings.revision = res.revision;
    }
    refreshAnnotationsStepFlag();
    showToast(enabled ? '已在视频中启用勾画;导出前需逐页确认标注。' : '已关闭视频勾画;草稿会保留。');
  } catch (error) {
    const failure = AnnotationsCore.classifyPatchFailure(error.status, error.body);
    if (failure.kind === 'revision_conflict') {
      showToast('设置已被其他窗口修改,正在重新加载。');
      await reloadAnnotationsSummary();
    } else {
      showToast(`设置保存失败：${failure.message}`);
    }
    const enabledToggle = document.getElementById('annotation-enabled-toggle');
    if (enabledToggle) enabledToggle.checked = ANNOTATIONS_WS.summary?.settings?.enabled === true;
  }
}

async function setAnnotationEmphasis(emphasis) {
  if (!['weak', 'moderate', 'strong'].includes(emphasis)) return;
  const projectId = ANNOTATIONS_WS.projectId;
  if (!projectId) return;
  const settings = ANNOTATIONS_WS.summary?.settings || {};
  const defaults = { ...(settings.defaults || {}), emphasis };
  try {
    const res = await API.put(`${annotationsApiBase(projectId)}/settings`, {
      expected_revision: ANNOTATIONS_WS.settingsRevision,
      enabled: settings.enabled === true,
      defaults,
    }, { silent: true });
    if (ANNOTATIONS_WS.projectId !== projectId) return;
    ANNOTATIONS_WS.settingsRevision = res.revision;
    ANNOTATIONS_WS.summary.settings = {
      ...settings,
      revision: res.revision,
      defaults: res.defaults || defaults,
    };
    showToast(`AI 重点密度已设为${{ weak: '少量', moderate: '标准', strong: '较多' }[emphasis]}。`);
  } catch (error) {
    showToast(`AI 重点密度保存失败：${error.message || '未知错误'}`);
    await reloadAnnotationsSummary();
  }
}

// ------------------------------------------------------------ 显式桥接

window.loadStep10Data = loadStep10Data;
window.resetAnnotationsProjectState = resetAnnotationsProjectState;
window.flushAnnotationsSave = flushAnnotationsSave;
window.queueAnnotationSave = queueAnnotationSave;
window.reloadAnnotationsSummary = reloadAnnotationsSummary;
window.setAnnotationsEnabled = setAnnotationsEnabled;
window.setAnnotationEmphasis = setAnnotationEmphasis;
window.selectAnnotationPage = selectAnnotationPage;
window.selectAnnotationItem = selectAnnotationItem;
window.refreshAnnotationModuleState = refreshAnnotationModuleState;
window.setAnnotationDecision = setAnnotationDecision;
window.requestAnnotationDecision = requestAnnotationDecision;
window.confirmAnnotationPage = confirmAnnotationPage;
window.resolveAnnotationConflict = resolveAnnotationConflict;
window.retryAnnotationFailedOps = retryAnnotationFailedOps;
window.discardAnnotationFailedOps = discardAnnotationFailedOps;
window.ANNOTATIONS_WS = ANNOTATIONS_WS;

// ------------------------------------------------------------ W3: 文字候选与 AI 规划

ANNOTATIONS_WS.jobTimer = null;
ANNOTATIONS_WS.candidates = [];

function stopAnnotationJobPolling() {
  clearTimeout(ANNOTATIONS_WS.jobTimer);
  ANNOTATIONS_WS.jobTimer = null;
}

// 重置项目状态时一并停止任务轮询(挂在既有复位函数之后)
const _resetAnnotationsBase = resetAnnotationsProjectState;
resetAnnotationsProjectState = function () {
  stopAnnotationJobPolling();
  ANNOTATIONS_WS.candidates = [];
  ANNOTATIONS_WS.activeJob = null;
  _resetAnnotationsBase();
};

async function submitAnnotationJob(operation, options = {}) {
  const projectId = ANNOTATIONS_WS.projectId;
  if (!projectId) return;
  const slideId = ANNOTATIONS_WS.page.slide_id;
  if (ANNOTATIONS_WS.activeJob?.projectId === projectId) {
    showToast('已有勾画任务在执行，请等待完成后再提交。');
    return;
  }
  ANNOTATIONS_WS.activeJob = {projectId, slideId, operation};
  try { await flushAnnotationsSave(); } catch (error) {
    ANNOTATIONS_WS.activeJob = null;
    showToast(`请先保存编辑：${error.message}`);
    return;
  }
  if (ANNOTATIONS_WS.projectId !== projectId || ANNOTATIONS_WS.page.slide_id !== slideId
      || ANNOTATIONS_WS.failedOps.length || ANNOTATIONS_WS.conflict) {
    ANNOTATIONS_WS.activeJob = null;
    return;
  }
  const requestKey = `${operation}-${projectId}-${slideId}-${Date.now()}`;
  const body = {
    operation,
    slide_ids: options.slideIds || (slideId ? [slideId] : undefined),
    request_key: requestKey,
  };
  if (operation === 'plan') ANNOTATIONS_WS.activePlanSlideIds = options.slideIds;
  let res;
  try {
    res = await API.post(`${annotationsApiBase(projectId)}/jobs`, body, { silent: true });
  } catch (error) {
    ANNOTATIONS_WS.activeJob = null;
    showToast(`任务提交失败：${error.message || '未知错误'}`);
    return;
  }
  if (ANNOTATIONS_WS.projectId !== projectId) return;
  renderAnnotationJobProgress(operation, res.job_id, 'queued', 0);
  pollAnnotationJob(res.job_id, operation, projectId, slideId);
}

// 任务成功收场时如实上报页级失败:部分页失败(跳过原因如缺讲稿)不算失败,
// 有 failed 页就必须告诉用户,否则"已生成"提示掩盖了空结果。
function annotationJobSlideFailure(job) {
  const slides = Array.isArray(job?.result?.slides) ? job.result.slides : [];
  const failed = slides.filter(entry => entry?.status === 'failed');
  if (!failed.length) return '';
  const error = String(failed[0]?.error || '未知错误');
  return failed.length === slides.length ? error : `${failed.length}/${slides.length} 页失败:${error}`;
}

function pollAnnotationJob(jobId, operation, projectId, slideId) {
  stopAnnotationJobPolling();
  const tick = async () => {
    // 项目已切换:轮询结果与当前工作区无关,直接终止(R4-005)
    if (ANNOTATIONS_WS.projectId !== projectId) return;
    let job;
    try {
      job = await API.get(`${annotationsApiBase(projectId)}/jobs/${encodeURIComponent(jobId)}`, { silent: true });
    } catch (error) {
      if (ANNOTATIONS_WS.projectId !== projectId) return;
      ANNOTATIONS_WS.activeJob = null;
      renderAnnotationJobProgress(operation, jobId, 'error', 0, error.message);
      return;
    }
    if (ANNOTATIONS_WS.projectId !== projectId) return;
    renderAnnotationJobProgress(operation, jobId, job.status, job.progress, job.error);
    if (job.status === 'succeeded') {
      ANNOTATIONS_WS.activeJob = null;
      const slideFailure = annotationJobSlideFailure(job);
      if (operation === 'detect_text') {
        await loadAnnotationCandidates();
        if (ANNOTATIONS_WS.projectId === projectId) {
          showToast(slideFailure ? `文字识别完成,但有页面失败:${slideFailure}` : '文字识别完成;可点选候选生成文字标注。');
        }
        const next = annotationAutoPlanRequest;
        annotationAutoPlanRequest = null;
        if (!slideFailure && (job.result?.slides || []).every(entry => entry.status !== 'skipped') && next?.projectId === projectId && next?.slideId === ANNOTATIONS_WS.page.slide_id) {
          await submitAnnotationJob('plan', {slideIds: next.slideIds});
        }
      } else if (operation === 'align') {
        showToast(slideFailure ? `音频定位失败：${slideFailure}。可人工试听校准。`
          : '音频文字定位完成，请同步预览；无法可靠定位的文字可人工试听校准。');
      } else if (operation === 'plan') {
        // 仅当用户仍停留在发起页才重载,避免把 AI 条目刷进别的页面(R4-005)
        if (ANNOTATIONS_WS.page.slide_id === slideId) {
          await selectAnnotationPage(ANNOTATIONS_WS.activeIndex);
        }
        if (ANNOTATIONS_WS.projectId === projectId) {
          showToast(slideFailure ? `AI 重点未能生成:${slideFailure}` : 'AI 重点已生成，开始定位音频文字。');
          if (!slideFailure && ANNOTATIONS_WS.page.slide_id === slideId) await submitAnnotationJob('align', {slideIds: ANNOTATIONS_WS.activePlanSlideIds});
        }
      }
      return;
    }
    if (job.status === 'running' || job.status === 'queued') {
      ANNOTATIONS_WS.jobTimer = setTimeout(tick, 1200);
    } else {
      ANNOTATIONS_WS.activeJob = null;
    }
  };
  ANNOTATIONS_WS.jobTimer = setTimeout(tick, 800);
}

function renderAnnotationJobProgress(operation, jobId, status, progress, error) {
  const node = document.getElementById('annotation-job-status');
  if (!node) return;
  const label = operation === 'detect_text' ? '文字识别' : operation === 'align' ? '音频文字定位' : 'AI 生成重点';
  renderAnnotationFlow({status, label: status === 'queued' ? `${label}排队中` : `${label}中`});
  if (status === 'succeeded') {
    node.style.display = 'inline-flex';
    setUiTaskState(node, 'done', `${label}完成`);
    return;
  }
  node.style.display = 'inline-flex';
  if (status === 'failed' || status === 'error') {
    node.dataset.state = 'error';
    setUiTaskState(node, 'error', `${label}失败:${error || '请重试'}`);
    return;
  }
  node.dataset.state = 'saving';
  setUiTaskState(node, status === 'queued' ? 'queued' : 'running', status === 'queued' ? `${label}排队中` : `${label}中${Number(progress) > 0 ? ` · ${Math.round(progress)}%` : ''}`);
}

async function loadAnnotationCandidates() {
  const projectId = ANNOTATIONS_WS.projectId;
  const slideId = ANNOTATIONS_WS.page.slide_id;
  const generation = ANNOTATIONS_WS.pageGeneration;
  if (!projectId || !slideId) return;
  try {
    const res = await API.get(`${annotationsApiBase(projectId)}/slides/${encodeURIComponent(slideId)}/text-layout`, { silent: true });
    // 响应返回时已切页/切项目:丢弃过期候选,防止 A 页几何落进 B 页(R4-005)
    if (ANNOTATIONS_WS.projectId !== projectId
      || generation !== ANNOTATIONS_WS.pageGeneration
      || ANNOTATIONS_WS.page.slide_id !== slideId) {
      return;
    }
    ANNOTATIONS_WS.candidates = res.candidates || [];
    ANNOTATIONS_WS.layoutRevision = res.layout_revision || 0;
  } catch (error) {
    if (ANNOTATIONS_WS.projectId !== projectId
      || generation !== ANNOTATIONS_WS.pageGeneration
      || ANNOTATIONS_WS.page.slide_id !== slideId) {
      return;
    }
    ANNOTATIONS_WS.candidates = [];
  }
  renderAnnotationCandidates();
}

function renderAnnotationCandidates() {
  const container = document.getElementById('annotation-candidates');
  if (!container) return;
  const candidates = ANNOTATIONS_WS.candidates || [];
  if (!candidates.length) {
    container.innerHTML = '<div class="annotation-items-empty">尚未识别文字。点击"识别文字"后可点选候选。</div>';
    return;
  }
  container.innerHTML = candidates.map(candidate => {
    const granularityTag = candidate.granularity === 'line' ? '<span class="annotation-chip">整行</span>' : '';
    return `<button type="button" class="annotation-candidate" data-token-id="${escHtml(candidate.token_id)}" title="${escHtml(candidate.text)}">
      <span class="annotation-candidate-text">${escHtml(candidate.text)}</span>${granularityTag}
    </button>`;
  }).join('');
  container.querySelectorAll('.annotation-candidate').forEach(node => {
    node.addEventListener('click', () => addAnnotationFromCandidate(node.dataset.tokenId));
  });
}

function addAnnotationFromCandidate(tokenId) {
  const candidate = (ANNOTATIONS_WS.candidates || []).find(entry => entry.token_id === tokenId);
  if (!candidate) return;
  const defaults = ANNOTATIONS_WS.summary?.settings?.defaults || {};
  const polygon = candidate.polygon;
  if (!polygon || polygon.length !== 4) {
    showToast('该候选缺少有效几何,请重新识别文字。');
    return;
  }
  // 工具栏"新标注样式"对文字候选同样生效
  const styleType = document.getElementById('annotation-new-style')?.value || defaults.type || 'ellipse';
  const anchor = ANNOTATIONS_WS.pendingNarrationAnchor || null;
  const timing = {
    trigger_mode: anchor ? 'anchor_start' : 'manual',
    offset_sec: 0,
    draw_duration_sec: Number(defaults.draw_duration_sec || 0.6),
    hold_mode: anchor ? 'beat_end' : 'slide_end',
    exit_duration_sec: Number(defaults.exit_duration_sec || 0.15),
  };
  if (!anchor) {
    timing.manual_start_sec = 0;
  }
  pushAnnotationHistory();
  const item = {
    target: {
      kind: 'text',
      layout_revision: ANNOTATIONS_WS.layoutRevision || 1,
      token_ids: [tokenId],
      polygons: [polygon],
      quote: candidate.text,
      granularity: candidate.granularity || 'char',
      mask_group_ids: [],
    },
    anchor,
    style: {
      type: styleType,
      color: document.getElementById('annotation-new-style')?.value === 'highlighter' ? '#F6CE46' : defaults.color || '#F46A38',
      opacity: document.getElementById('annotation-new-style')?.value === 'highlighter' ? 0.28 : Number(defaults.opacity ?? 0.85),
      width: Number(defaults.width || 5),
      padding: Number(defaults.padding || 8),
      seed: Math.floor(Math.random() * 2147483647),
    },
    timing,
  };
  const localId = nextLocalAnnotationId();
  const stored = { ...item, annotation_id: localId };
  if (!anchor) {
    // 服务端要求文字目标必须带讲稿锚点:先建本地草稿,选中短语后随 add 提交
    stored.__deferredAdd = true;
  }
  ANNOTATIONS_WS.page.items.push(stored);
  if (!stored.__deferredAdd) {
    // add 操作携带 local id(→ __local_id),保存前合并才能接住后续 update/delete
    queueAnnotationSave(AnnotationsCore.buildAddOperation(stored));
  }
  renderAnnotationItems();
  renderAnnotationOverlay();
  selectAnnotationItem(localId);
  showToast(anchor
    ? '已添加文字标注并关联讲稿。'
    : '已添加文字标注;到讲稿中选中短语完成关联后自动保存。');
}

window.submitAnnotationJob = submitAnnotationJob;
window.loadAnnotationCandidates = loadAnnotationCandidates;

// One action prepares recognition, then plans and aligns through existing jobs.
let annotationAutoPlanRequest = null;
async function autoAnnotateCurrentPage(allPages = false) {
  if (ANNOTATIONS_WS.activeJob) { showToast('当前任务仍在执行，请等待完成。'); return; }
  annotationAutoPlanRequest = {projectId: ANNOTATIONS_WS.projectId, slideId: ANNOTATIONS_WS.page.slide_id, slideIds: allPages ? [...ANNOTATIONS_WS.slideIds] : undefined};
  await submitAnnotationJob('detect_text', {slideIds: annotationAutoPlanRequest.slideIds});
  if (!ANNOTATIONS_WS.activeJob) annotationAutoPlanRequest = null;
}
window.autoAnnotateCurrentPage = autoAnnotateCurrentPage;
