// Visible Step 5 narration editing and audio production lifecycle.
// Shared project state, API helpers, and workflow navigation live in ui_foundation.js / workflow_state.js / api_client.js.

// ==================== 步骤 6: 演讲稿编辑 ====================

let narrationData = null;
// narrationData 的归属快照。旁白的每个异步操作（自动保存、初始化、AI 标注、
// 音频状态刷新）都必须绑定启动时的项目快照；禁止中途重读 state.currentProject——
// 那是切换项目后把 A 项目旁白 PUT 到 B 项目（并误清 B 音频确认）的根源。
// 归属由 loadStep6Data/initStep6Narration 绑定，随 resetStep6ProjectState 清空。
let narrationProjectScope = null;

function bindStep6ProjectScope(projectId, sessionVersion) {
  narrationProjectScope = { projectId, sessionVersion };
  return narrationProjectScope;
}

function resetStep6ProjectState() {
  if (state.step6AutoSaveTimer) {
    clearTimeout(state.step6AutoSaveTimer);
    state.step6AutoSaveTimer = null;
  }
  state.step6AutoSavePromise = null;
  narrationData = null;
  narrationProjectScope = null;
}
window.resetStep6ProjectState = resetStep6ProjectState;

async function loadStep6Data() {
  const projectId = state.currentProject?.id;
  const sessionVersion = workspaceNavigationVersion;
  if (!projectId) return;
  const res = await API.get(`/api/projects/${projectId}/steps/6/result`);
  if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
  if (res.success && res.beats) {
    narrationData = res.beats;
    bindStep6ProjectScope(projectId, sessionVersion);
    normalizeStep6Data();
    renderStep6Workspace();
    void offerArtifactRepair(res, '演讲稿数据', loadStep6Data);
  } else {
    // 浏览未开始的步骤不触发写入或缺失依赖错误；用户可主动点击同步。
    narrationData = { slides: [] };
    renderStep6Workspace();
  }
}

async function initStep6Narration() {
  const projectId = state.currentProject?.id;
  const sessionVersion = workspaceNavigationVersion;
  if (!projectId) return;
  showToast('📝 正在根据视觉合约自动初始化演讲稿旁白文本...');
  const res = await API.post(`/api/projects/${projectId}/steps/6/init`);
  if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
  if (res.success) {
    narrationData = res.beats;
    bindStep6ProjectScope(projectId, sessionVersion);
    normalizeStep6Data();
    updateStep6AutosaveStatus('已同步模板');
    renderStep6Workspace();
  }
}

function composeStep6AnnotationPrompt(systemContent, outputExample) {
  return `${String(systemContent || '').trim()}\n\n<OutputExample>\n${String(outputExample || '').trim()}\n</OutputExample>`;
}

function updateStep6AnnotationFullPrompt() {
  const systemInput = document.getElementById('step6-ai-system-prompt');
  const exampleInput = document.getElementById('step6-ai-output-example');
  const fullInput = document.getElementById('step6-ai-full-prompt');
  if (!systemInput || !exampleInput || !fullInput) return;
  fullInput.value = composeStep6AnnotationPrompt(systemInput.value, exampleInput.value);
}

async function openStep6AnnotationPromptModal() {
  const modal = document.getElementById('modal-step6-ai-prompt');
  const systemInput = document.getElementById('step6-ai-system-prompt');
  const exampleInput = document.getElementById('step6-ai-output-example');
  const fullInput = document.getElementById('step6-ai-full-prompt');
  if (!modal || !systemInput || !exampleInput || !fullInput) return;

  modal.style.display = 'flex';
  systemInput.value = '加载中...';
  exampleInput.value = '';
  fullInput.value = '';
  try {
    const res = await API.get('/api/settings/narration-annotation');
    const prompts = res.prompts || {};
    systemInput.value = prompts.system_content || '';
    exampleInput.value = prompts.output_example || '';
    fullInput.value = prompts.full_prompt || '';
    updateStep6AnnotationFullPrompt();
  } catch (error) {
    closeStep6AnnotationPromptModal();
  }
}

function closeStep6AnnotationPromptModal() {
  const modal = document.getElementById('modal-step6-ai-prompt');
  if (modal) modal.style.display = 'none';
}

async function saveStep6AnnotationPrompts() {
  const systemContent = document.getElementById('step6-ai-system-prompt')?.value.trim() || '';
  const outputExample = document.getElementById('step6-ai-output-example')?.value.trim() || '';
  if (!systemContent || !outputExample) {
    showToast('System Content 和 Output Example 不能为空');
    return;
  }
  const button = document.getElementById('btn-step6-ai-prompt-save');
  if (button) button.disabled = true;
  try {
    await API.put('/api/settings/narration-annotation', {
      prompts: {
        system_content: systemContent,
        output_example: outputExample,
      },
    });
    showToast('旁白 AI 标注 Prompt 已保存');
    closeStep6AnnotationPromptModal();
  } finally {
    if (button) button.disabled = false;
  }
}

async function annotateStep6Narration() {
  const projectId = state.currentProject?.id;
  const sessionVersion = workspaceNavigationVersion;
  if (!projectId) return;
  if (!narrationData) {
    await initStep6Narration();
  }
  if (!narrationData) return;
  if (state.step6AutoSaveTimer) {
    clearTimeout(state.step6AutoSaveTimer);
    state.step6AutoSaveTimer = null;
  }
  if (state.step6AutoSavePromise) {
    try {
      await state.step6AutoSavePromise;
    } catch (error) {
      // The annotation request below contains the latest editor state.
    }
  }
  // 等待初始化/保存期间可能已切换项目：归属不符就放弃本次标注。
  if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
  saveStep6CurrentState();
  normalizeStep6Data();
  const btn = document.getElementById('step6-btn-ai-annotate');
  try {
    if (btn) btn.disabled = true;
    updateStep6AutosaveStatus('AI 标注中...');
    showToast('AI 正在标注停顿和语气...');
    // AI 标注逐句段调用 LLM，可能超过 2 分钟，给足前端超时。
    const res = await API.post(
      `/api/projects/${projectId}/steps/6/annotate`,
      narrationData,
      { timeoutMs: 300000 },
    );
    // 标注请求最长 5 分钟：响应回来时必须重新核对归属，否则 A 项目的
    // 标注结果会渲染进当前已切换到的 B 项目工作区。
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
    if (res.success && res.beats) {
      narrationData = res.beats;
      bindStep6ProjectScope(projectId, sessionVersion);
      normalizeStep6Data();
      renderStep6Workspace();
      updateStep6AutosaveStatus('AI 标注已保存');
      showToast(`AI 标注完成：${res.annotated_count || 0} 个句段`);
      refreshCurrentProjectStatus(6).catch(() => {});
    }
  } catch (e) {
    if (isCurrentWorkspaceProject(projectId, sessionVersion)) {
      updateStep6AutosaveStatus('AI 标注失败');
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

const STEP6_ALLOWED_TTS_EXPRESSION_TAGS = new Set([
  '(applause)', '(breath)', '(burps)', '(chuckle)', '(clear-throat)', '(coughs)',
  '(crying)', '(emm)', '(exhale)', '(gasps)', '(groans)', '(hissing)', '(humming)',
  '(inhale)', '(laughs)', '(lip-smacking)', '(pant)', '(sneezes)', '(sniffs)',
  '(snorts)', '(sighs)', '(whistles)',
]);

function stripStep6TtsMarkup(value) {
  return String(value || '')
    .replace(/<#\d+(?:\.\d{1,2})?#>/g, '')
    .replace(/\([A-Za-z-]+\)/g, tag => STEP6_ALLOWED_TTS_EXPRESSION_TAGS.has(tag) ? '' : tag)
    .replace(/\s+/g, ' ')
    .trim();
}

function syncStep6BeatText(beat, value) {
  if (!beat || typeof beat !== 'object') return;
  const ttsText = String(value || '').trim();
  const plainText = stripStep6TtsMarkup(ttsText);
  beat.tts_text = ttsText;
  beat.source_text = plainText;
  beat.spoken_text = plainText;
}

function normalizeStep6Beat(beat, idx) {
  if (!beat || typeof beat !== 'object') return null;
  const visibleText = String(beat.tts_text || beat.spoken_text || beat.source_text || '').trim();
  syncStep6BeatText(beat, visibleText);
  beat.id = beat.id || `sentence_${idx + 1}`;
  return beat;
}

function normalizeStep6Data() {
  if (!narrationData || !Array.isArray(narrationData.slides)) {
    narrationData = { slides: [] };
  }
  narrationData.slides.forEach(slide => {
    if (!Array.isArray(slide.beats)) slide.beats = [];
    const seen = new Set();
    slide.beats = slide.beats.map(normalizeStep6Beat).filter(Boolean).filter(beat => {
      const key = narrationDedupeKey(beat.spoken_text || beat.tts_text || beat.source_text || '');
      if (key && seen.has(key)) return false;
      if (key) seen.add(key);
      return true;
    });
  });
  if (state.activeSlideIndex >= narrationData.slides.length) {
    state.activeSlideIndex = Math.max(0, narrationData.slides.length - 1);
  }
}

function renderStep6Workspace() {
  const container = document.getElementById('step6-beats-list');
  if (!container) return;
  container.innerHTML = '';

  if (!narrationData?.slides?.length) {
    container.innerHTML = '<div class="soft-outline step6-empty-state ws-empty">暂无演讲稿，请先同步演讲稿模板。</div>';
    return;
  }

  narrationData.slides.forEach((slide, slideIndex) => {
    const slideRow = document.createElement('section');
    slideRow.className = 'step6-slide-row';
    slideRow.dataset.slideId = slide.slide_id;
    slideRow.innerHTML = `
      <div class="step6-slide-row-head">
        <h3>第 ${slideIndex + 1} 页</h3>
        <span class="step6-slide-state" hidden></span>
        <span class="step6-slide-status">${slide.beats.length ? `${slide.beats.length} 条旁白` : '暂无旁白'}</span>
        <button class="secondary compact-action-btn step6-generate-slide" type="button" data-slide-id="${escHtml(slide.slide_id)}" title="只重新生成当前 Slide 的旁白音频" ${slide.beats.length ? '' : 'disabled'}>单独生成</button>
      </div>
      <div class="step6-slide-beats"></div>
      <div class="step6-slide-audio" data-audio-slide-id="${escHtml(slide.slide_id)}"></div>
    `;
    slideRow.querySelector('.step6-generate-slide')?.addEventListener('click', () => {
      runStep7TTS({ slideId: slide.slide_id, force: true });
    });
    const beatsContainer = slideRow.querySelector('.step6-slide-beats');
    if (!slide.beats.length) {
      beatsContainer.innerHTML = '<div class="step6-empty-state ws-empty">当前 Slide 暂无旁白。可返回元素动画页建立语块，或重新同步旁白。</div>';
    }
    slide.beats.forEach((beat, beatIndex) => {
      normalizeStep6Beat(beat, beatIndex);
      const row = document.createElement('div');
      row.className = 'step6-beat-row';
      row.innerHTML = `
        <textarea class="step6-tts-input" rows="1" data-slide-index="${slideIndex}" data-beat-index="${beatIndex}" aria-label="${escHtml(slide.slide_id)} 旁白" placeholder="输入旁白文本，可保留停顿和语气标记">${escHtml(beat.tts_text || beat.spoken_text || '')}</textarea>
      `;
      const textarea = row.querySelector('textarea');
      textarea.addEventListener('input', (event) => {
        autoResizeNarrationTextarea(event.target);
        updateNarrationBeatText(slideIndex, beatIndex, event.target.value);
      });
      beatsContainer.appendChild(row);
      autoResizeNarrationTextarea(textarea);
    });
    container.appendChild(slideRow);
  });
}

function autoResizeNarrationTextarea(textarea) {
  if (!textarea) return;
  _resizeNarrationTextarea(textarea);
  // 布局可能尚未稳定（如步骤面板刚切换显示），下一帧再校准一次。
  requestAnimationFrame(() => _resizeNarrationTextarea(textarea));
}

function _resizeNarrationTextarea(textarea) {
  textarea.style.height = 'auto';
  // box-sizing: border-box 下，height 含 border 而 scrollHeight 不含，
  // 需补上边框厚度（约 2px）+ 子像素舍入余量（2px），避免长句末行被裁。
  const newHeight = Math.max(28, textarea.scrollHeight + 4);
  textarea.style.height = `${newHeight}px`;
}

function updateNarrationBeatText(slideIndex, beatIndex, val) {
  const slide = narrationData.slides[slideIndex];
  if (slide && slide.beats[beatIndex]) {
    syncStep6BeatText(slide.beats[beatIndex], val);
    scheduleStep6Autosave();
  }
}

function saveStep6CurrentState() {
  const list = document.getElementById('step6-beats-list');
  if (!list || !narrationData?.slides) return;
  list.querySelectorAll('.step6-tts-input').forEach(ta => {
    const slideIdx = Number(ta.dataset.slideIndex);
    const beatIdx = Number(ta.dataset.beatIndex);
    const beat = narrationData.slides?.[slideIdx]?.beats?.[beatIdx];
    if (beat) {
      syncStep6BeatText(beat, ta.value);
    }
  });
}

function updateStep6AutosaveStatus(text) {
  const el = document.getElementById('step6-autosave-status');
  if (el) el.innerText = text || '';
}

function scheduleStep6Autosave() {
  // 归属在调度时冻结：定时器迟到（切项目/切步骤）也只可能保存回原项目。
  const scope = narrationProjectScope
    || (state.currentProject
      ? { projectId: state.currentProject.id, sessionVersion: workspaceNavigationVersion }
      : null);
  if (!scope?.projectId) return;
  if (state.step6AutoSaveTimer) clearTimeout(state.step6AutoSaveTimer);
  updateStep6AutosaveStatus('自动保存中...');
  state.step6AutoSaveTimer = setTimeout(() => {
    state.step6AutoSaveTimer = null;
    if (narrationProjectScope?.projectId !== scope.projectId) return;
    saveStep6Narration({ silent: true, scope });
  }, 700);
}

async function flushStep6Autosave(options = {}) {
  if (state.step6AutoSaveTimer) {
    clearTimeout(state.step6AutoSaveTimer);
    state.step6AutoSaveTimer = null;
  }
  return saveStep6Narration({ silent: true, ...options });
}

async function putStep6NarrationWithRetry(projectId, payload) {
  let lastError = null;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      return await API.put(`/api/projects/${projectId}/steps/6/result`, payload, { silent: true });
    } catch (error) {
      lastError = error;
      if (error.status || attempt === 1) break;
      await new Promise(resolve => setTimeout(resolve, 500));
    }
  }
  throw lastError || new Error('保存演讲稿失败');
}

async function saveStep6Narration(options = {}) {
  const silent = !!options.silent;
  const scope = options.scope || narrationProjectScope;
  if (!narrationData) return true;
  if (!scope?.projectId) return true;
  // 显式保存时解释影响；自动保存后用状态提示，避免打断连续输入。
  if (options.userInitiated === true && state.currentProject?.audio_confirmed === true) {
    const confirmed = await new Promise(resolve => {
      showCustomConfirm(
        '旁白修改会影响音频',
        '保存后的旁白若与旧音频不匹配，新视频需要更新音频。旧音频和已输出视频会保留。',
        () => resolve(true),
        () => resolve(false),
      );
    });
    if (!confirmed) return false;
  }
  if (state.step6AutoSavePromise) {
    try {
      await state.step6AutoSavePromise;
    } catch (error) {
      // Retry below with the newest editor snapshot.
    }
  }
  // 归属复查：等待前一个保存期间可能已切换项目并重置旁白状态（narrationData
  // 已被 resetStep6ProjectState 清空或重绑到新项目），此时绝不能再按旧快照保存。
  if (narrationProjectScope?.projectId !== scope.projectId) return false;
  saveStep6CurrentState();
  normalizeStep6Data();
  const payload = JSON.parse(JSON.stringify(narrationData));
  if (!silent) showToast('💾 正在保存并校验台词信息...');
  // 请求目标固定为调度时的项目：即使保存等待期间切到 B，这次 PUT 仍指向
  // 原 project（其自身的编辑写回其自身），绝不读 state.currentProject。
  const savePromise = putStep6NarrationWithRetry(scope.projectId, payload);
  state.step6AutoSavePromise = savePromise;
  try {
    const res = await savePromise;
    if (res.success) {
      // 成功提示只影响当前仍在原项目工作区时的界面；切换后静默收敛。
      if (isCurrentWorkspaceProject(scope.projectId, scope.sessionVersion)) {
        updateStep6AutosaveStatus('已自动保存');
        if (!silent) showToast('🎉 演讲稿修改保存成功！');
        refreshCurrentProjectStatus(6).catch(() => {});
      }
      return true;
    }
  } catch (e) {
    if (isCurrentWorkspaceProject(scope.projectId, scope.sessionVersion)) {
      updateStep6AutosaveStatus('保存失败，请重试');
      showToast(`❌ 演讲稿保存失败：${e.message || '网络连接中断'}`);
    }
    return false;
  } finally {
    if (state.step6AutoSavePromise === savePromise) {
      state.step6AutoSavePromise = null;
    }
  }
  return false;
}

// ==================== 可见步骤 6 的音频阶段（内部步骤 7） ====================

// 本次合成任务的目标页：这些卡片显示「生成中」，任务结束后清空并重取状态。
let step7ActiveTtsSlides = new Set();

function renderStep7SlideState(stateBadge, slideId, audio) {
  if (!stateBadge) return;
  stateBadge.classList.remove('is-generating', 'is-done', 'is-pending');
  stateBadge.removeAttribute('title');
  if (audio?.generating || step7ActiveTtsSlides.has(slideId)) {
    stateBadge.hidden = false;
    stateBadge.classList.add('is-generating');
    setUiTaskState(stateBadge, 'running', '生成中');
    return;
  }
  if (audio?.audio_exists && !audio?.stale) {
    stateBadge.hidden = false;
    stateBadge.classList.add('is-done');
    setUiTaskState(stateBadge, 'done', '已完成');
    return;
  }
  stateBadge.hidden = false;
  stateBadge.classList.add('is-pending');
  setUiTaskState(stateBadge, 'pending', '待生成');
  stateBadge.title = audio?.voice_config_stale
    ? '语音配置已变更，需重新生成'
    : audio?.stale ? '旁白已修改，需重新生成' : '音频尚未生成';
}

// 清空全部音频槽位（仅在确需整体重置时调用；轮询刷新禁止整体清空重建）。
function resetStep7AudioSlots() {
  document.querySelectorAll('.step6-slide-audio').forEach(slot => {
    if (!slot.dataset.step7Rendered && !slot.classList.contains('has-audio')) return;
    slot.innerHTML = '';
    slot.classList.remove('has-audio');
    delete slot.dataset.step7Rendered;
  });
}

async function loadStep7Data() {
  const projectId = state.currentProject?.id;
  const sessionVersion = workspaceNavigationVersion;
  if (!projectId) return;
  const emptyState = document.getElementById('step7-empty-state');
  const synthButton = document.getElementById('step7-btn-synthesize');
  const forceAllButton = document.getElementById('step7-btn-force-all');
  const step7Status = state.currentProject?.step_status?.['7'] || 'pending';
  const stepAllowsAudio = ['in_progress', 'completed', 'pending_reconfirmation'].includes(step7Status);

  // 确认按钮常驻可点，未就绪时在点击处 Toast 提示，不在标题栏挂提示文字。
  synthButton.style.display = stepAllowsAudio ? 'inline-flex' : 'none';
  if (forceAllButton) forceAllButton.style.display = stepAllowsAudio ? 'inline-flex' : 'none';

  if (!narrationData?.slides?.length) {
    emptyState.style.display = 'block';
    emptyState.innerText = '尚未生成音频。先准备旁白，再点击“生成音频”。';
    return;
  }

  const [res, audioStatus] = await Promise.all([
    API.get(`/api/projects/${projectId}/steps/3/images`),
    API.get(`/api/projects/${projectId}/steps/7/audio-status`)
  ]);
  // 音频槽位按通用 slide_id 匹配（slide_001 等跨项目同名）：A 项目的音频状态
  // 响应迟到时若不守卫，会渲染进当前项目（B）的槽位。
  if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
  const hasExistingAudio = (audioStatus.slides || []).some(item => item?.audio_exists);
  const canLoadAudio = stepAllowsAudio || hasExistingAudio || (audioStatus.active_slide_ids || []).length > 0;
  synthButton.style.display = canLoadAudio ? 'inline-flex' : 'none';
  if (forceAllButton) forceAllButton.style.display = canLoadAudio ? 'inline-flex' : 'none';
  if (!canLoadAudio) {
    resetStep7AudioSlots();
    emptyState.style.display = 'block';
    emptyState.innerText = '尚未生成音频。确认旁白后，点击“生成音频”。';
    return;
  }
  if (!res.success) return;
  const audioBySlide = new Map((audioStatus.slides || []).map(item => [item.slide_id, {...item, generating: (audioStatus.active_slide_ids || []).includes(item.slide_id)}]));
  res.images.forEach(img => {
    const slot = Array.from(document.querySelectorAll('.step6-slide-audio'))
      .find(item => item.dataset.audioSlideId === img.slide_id);
    if (!slot) return;
    const audio = audioBySlide.get(img.slide_id);
    // 三态徽章挂在卡片标题行右侧（2026-10-06 用户裁决 + Stitch 参考稿）：
    // 生成中 / 已生成 / 待生成，原因只留在悬浮 title。
    const stateBadge = slot.closest('.step6-slide-row')?.querySelector('.step6-slide-state');
    renderStep7SlideState(stateBadge, img.slide_id, audio);
    const busy = audio?.generating || step7ActiveTtsSlides.has(img.slide_id);
    const target = audio?.audio_exists && !audio?.stale && !busy ? 'audio' : (busy ? 'busy' : 'pending');
    // 合成任务轮询每 2 秒进入本函数：槽位 DOM 只在状态切换时重建。
    // 无条件清空重建会让 <audio> 播放器与骨架屏每轮销毁重现，页面高度
    // 反复塌陷回流、动画重启，表现为整页抽搐。
    const rendered = target === 'audio'
      ? slot.querySelector('audio.step7-audio-player')
      : slot.querySelector('[data-page-task-key="audio"]');
    if (slot.dataset.step7Rendered === target && rendered) return;
    if (target === 'audio') {
      // 仅在（重新）进入已完成态时加时间戳，避免轮询期间反复穿透缓存。
      const audioUrl = `/api/projects/${projectId}/slides/${img.slide_id}/audio?t=${Date.now()}`;
      slot.innerHTML = `<audio controls preload="metadata" src="${audioUrl}" class="step7-audio-player" aria-label="${escHtml(img.slide_id)} 音频"></audio>`;
      slot.classList.add('has-audio');
    } else {
      slot.innerHTML = '';
      slot.classList.remove('has-audio');
      renderPageTaskState(slot, 'audio', busy ? 'running' : 'pending', busy ? '正在生成本页音频' : '待生成', 'audio');
    }
    slot.dataset.step7Rendered = target;
  });

  const allAudioComplete = audioStatus.complete === true;
  // 确认按钮常驻可点：未就绪时点击给出 Toast 提示（验收 2026-10-06：标题栏不再挂提示文字）。
  if (!allAudioComplete) {
    // Each slide already shows its actionable audio state.  Do not repeat a
    // long, non-actionable missing-slide list above the editor.
    emptyState.style.display = 'none';
    emptyState.innerText = '';
  } else if (step7Status === 'pending_reconfirmation') {
    emptyState.style.display = 'none';
    emptyState.innerText = '';
  } else {
    emptyState.style.display = 'none';
    // 命名统一为「进入勾画标注」（UI 审查第四轮：进入类按钮不带「确认」）。
    // 音频未就绪时由后端门控拦截，完整语义保留在按钮 title 上。
    const confirmLabel = document.getElementById('step6-audio-confirm-label');
    confirmLabel.innerText = '进入勾画标注';
    const confirmBtn = document.getElementById('step6-btn-audio-confirm-next');
    if (confirmBtn) confirmBtn.title = state.currentProject.audio_confirmed
      ? '进入勾画标注'
      : '确认当前音频已就绪，进入勾画标注步骤；勾画标注默认不需要，可跳过';
  }
}

async function runStep7TTS(options = {}) {
  const projectId = state.currentProject?.id;
  const sessionVersion = workspaceNavigationVersion;
  if (!projectId) return false;
  const targetSlideId = String(options.slideId || '').trim();
  if (!options.alreadySaved) {
    const saved = await flushStep6Autosave({ userInitiated: false });
    if (!saved || !isCurrentWorkspaceProject(projectId, sessionVersion)) return false;
  }
  const synthButton = document.getElementById('step7-btn-synthesize');
  const saveAndTtsButton = document.getElementById('step6-btn-save-and-tts');
  const forceAllButton = document.getElementById('step7-btn-force-all');
  const confirmButton = document.getElementById('step6-btn-audio-confirm-next');
  synthButton.disabled = true;
  saveAndTtsButton.disabled = true;
  if (forceAllButton) forceAllButton.disabled = true;
  confirmButton.disabled = true;
  document.querySelectorAll('.step6-generate-slide').forEach(button => { button.disabled = true; });

  // 顶部不再挂全局加载条（2026-10-06 用户裁决）：本次合成的目标页直接在
  // 卡片上显示「生成中」，任务结束后清空标记并重取音频状态。
  try {
    const statusRes = await API.get(`/api/projects/${projectId}/steps/7/audio-status`, { silent: true });
    const slides = statusRes?.slides || [];
    step7ActiveTtsSlides = new Set(targetSlideId
      ? [targetSlideId]
      : options.force
        ? slides.map(item => item.slide_id).filter(Boolean)
        : slides
          .filter(item => !item?.audio_exists || item?.stale || item?.voice_config_stale)
          .map(item => item.slide_id));
  } catch (_) {
    step7ActiveTtsSlides = new Set();
  }
  if (isCurrentWorkspaceProject(projectId, sessionVersion)) await loadStep7Data();

  // TTS 后台任务（M-09 第二步）：提交即返回 job_id，前端轮询直至终态。
  // 客户端断连/代理超时不再中断合成，状态经 local_jobs 持久化。
  let pollTimer = null;
  try {
    const submitted = await API.post(
      `/api/projects/${projectId}/steps/7/synthesize-async`,
      {
        ...(targetSlideId ? { slide_id: targetSlideId } : {}),
        ...(options.force ? { force: true } : {}),
      },
    );
    if (!submitted.success || !submitted.job) {
      throw new Error(submitted.message || '无法创建合成任务');
    }
    const jobId = submitted.job.id;
    step7ActiveTtsSlides = new Set();

    const finalJob = await new Promise((resolve, reject) => {
      const started = Date.now();
      const tick = async () => {
        try {
          // 轮询目标固定为提交时的项目；切换项目后旧任务照常跟踪，
          // 但其结果只回写到原项目（见终态守卫）。
          const res = await API.get(
            `/api/projects/${projectId}/steps/7/synthesize-jobs/${jobId}`,
            { silent: true },
          );
          const job = res.job || {};
          if (isCurrentWorkspaceProject(projectId, sessionVersion)) await loadStep7Data();
          if (['completed', 'failed', 'interrupted', 'cancelled'].includes(job.status)) {
            resolve(job);
            return;
          }
          if (Date.now() - started > 30 * 60 * 1000) {
            reject(new Error('合成任务轮询超时（30 分钟），请稍后刷新页面查看状态。'));
            return;
          }
          pollTimer = setTimeout(tick, 2000);
        } catch (err) {
          reject(err);
        }
      };
      tick();
    });

    step7ActiveTtsSlides.clear();

    // 轮询可达 30 分钟：终态只回写原项目的工作区；已切走时仅收敛按钮状态。
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) {
      return finalJob.status === 'completed';
    }

    if (finalJob.status === 'completed') {
      await refreshCurrentProjectStatus(6);
      await loadStep7Data();
      return true;
    }

    const failedIds = Array.isArray(finalJob.result?.failed_ids)
      ? finalJob.result.failed_ids.filter(Boolean)
      : [];
    if (finalJob.status === 'cancelled') {
      await loadStep7Data();
      return false;
    }
    const fallback = failedIds.length ? `部分页面失败：${failedIds.join('、')}` : '音频生成未完成';
    showToast(`音频生成失败：${finalJob.error || fallback}`, 7000);
    await refreshCurrentProjectStatus(6);
    await loadStep7Data();
    return false;
  } catch (e) {
    step7ActiveTtsSlides.clear();
    showToast(`音频生成失败：${e.message}`, 7000);
    return false;
  } finally {
    if (pollTimer) clearTimeout(pollTimer);
    if (isCurrentWorkspaceProject(projectId, sessionVersion)) {
    synthButton.disabled = false;
    saveAndTtsButton.disabled = false;
    confirmButton.disabled = false;
    if (forceAllButton) forceAllButton.disabled = false;
    document.querySelectorAll('.step6-generate-slide').forEach(button => { button.disabled = false; });
    }
  }
}

async function confirmForceRegenerateAllTTS() {
  const confirmed = await new Promise(resolve => {
    showCustomConfirm(
      '强制重生成全部音频',
      '将忽略现有音频缓存，重新合成所有页面。新音频生成成功后才会替换旧文件，合成失败时仍保留旧文件。',
      () => resolve(true),
      () => resolve(false),
    );
  });
  if (!confirmed) return false;
  return runStep7TTS({ force: true });
}

async function saveNarrationAndRunTTS() {
  // 显式保存路径：需要用户确认音频状态被清除；静默自动保存不会到达这里。
  const saved = await flushStep6Autosave({ userInitiated: true });
  if (!saved) return false;
  return runStep7TTS({ alreadySaved: true });
}

async function confirmStep7Audio() {
  const projectId = state.currentProject?.id;
  const sessionVersion = workspaceNavigationVersion;
  if (!projectId) return false;
  const confirmButton = document.getElementById('step6-btn-audio-confirm-next');
  if (!narrationData?.slides?.length) {
    showToast('请先准备旁白并生成音频');
    return false;
  }
  confirmButton.disabled = true;
  try {
    // 常驻可点按钮的点击前置校验：未就绪时提示而不是静默失败。
    const audioStatus = await API.get(`/api/projects/${projectId}/steps/7/audio-status`);
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return false;
    if (audioStatus?.complete !== true) {
      showToast('请先生成全部页面音频，并逐页试听');
      return false;
    }
    const step7Status = state.currentProject?.step_status?.['7'] || 'pending';
    if (step7Status === 'pending_reconfirmation') {
      showToast('音频已变更，请先重新生成后再确认');
      return false;
    }
    const res = await API.post(`/api/projects/${projectId}/steps/7/confirm`, {});
    // 确认响应迟到时不得刷新/提示到切换后的项目上。
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return false;
    if (res.success) {
      await refreshCurrentProjectStatus(6);
      return true;
    }
  } catch (e) {
    if (isCurrentWorkspaceProject(projectId, sessionVersion)) {
      showToast(`音频确认失败：${e.message}`, 7000);
    }
    return false;
  } finally {
    confirmButton.disabled = false;
  }
  return false;
}

