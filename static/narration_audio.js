// Visible Step 5 narration editing and audio production lifecycle.
// Shared project state, API helpers, and workflow navigation live in ui_foundation.js / workflow_state.js / api_client.js.

// ==================== 步骤 6: 演讲稿编辑 ====================

let narrationData = null;

async function loadStep6Data() {
  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/6/result`);
  if (res.success && res.beats) {
    narrationData = res.beats;
    normalizeStep6Data();
    renderStep6Workspace();
    void offerArtifactRepair(res, '演讲稿数据', loadStep6Data);
  } else {
    // 首次进入没有演讲稿，提示同步初始化
    await initStep6Narration();
  }
}

async function initStep6Narration() {
  showToast('📝 正在根据视觉合约自动初始化演讲稿旁白文本...');
  const res = await API.post(`/api/projects/${state.currentProject.id}/steps/6/init`);
  if (res.success) {
    narrationData = res.beats;
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
  if (!state.currentProject) return;
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
  saveStep6CurrentState();
  normalizeStep6Data();
  const btn = document.getElementById('step6-btn-ai-annotate');
  try {
    if (btn) btn.disabled = true;
    updateStep6AutosaveStatus('AI 标注中...');
    showToast('AI 正在标注停顿和语气...');
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/6/annotate`, narrationData);
    if (res.success && res.beats) {
      narrationData = res.beats;
      normalizeStep6Data();
      renderStep6Workspace();
      updateStep6AutosaveStatus('AI 标注已保存');
      showToast(`AI 标注完成：${res.annotated_count || 0} 个句段`);
      refreshCurrentProjectStatus(6).catch(() => {});
    }
  } catch (e) {
    updateStep6AutosaveStatus('AI 标注失败');
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
    container.innerHTML = '<div class="soft-outline step6-empty-state">暂无演讲稿，请先同步演讲稿模板。</div>';
    return;
  }

  narrationData.slides.forEach((slide, slideIndex) => {
    const slideRow = document.createElement('section');
    slideRow.className = 'step6-slide-row';
    slideRow.dataset.slideId = slide.slide_id;
    slideRow.innerHTML = `
      <div class="step6-slide-row-head">
        <h3>${escHtml(slide.slide_id)}</h3>
        <span class="step6-slide-status">${slide.beats.length ? `${slide.beats.length} 条旁白` : '暂无旁白'}</span>
      </div>
      <div class="step6-slide-beats"></div>
      <div class="step6-slide-audio" data-audio-slide-id="${escHtml(slide.slide_id)}"></div>
    `;
    const beatsContainer = slideRow.querySelector('.step6-slide-beats');
    if (!slide.beats.length) {
      beatsContainer.innerHTML = '<div class="step6-empty-state">当前 Slide 暂无旁白。可返回 Mask 标注页建立语块，或重新同步旁白。</div>';
    }
    slide.beats.forEach((beat, beatIndex) => {
      normalizeStep6Beat(beat, beatIndex);
      const row = document.createElement('div');
      row.className = 'step6-beat-row';
      row.innerHTML = `
        <span class="step6-beat-number">${beatIndex + 1}</span>
        <textarea class="step6-tts-input" rows="1" data-slide-index="${slideIndex}" data-beat-index="${beatIndex}" aria-label="${escHtml(slide.slide_id)} 第 ${beatIndex + 1} 条旁白" placeholder="输入旁白文本，可保留停顿和语气标记">${escHtml(beat.tts_text || beat.spoken_text || '')}</textarea>
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
  if (state.step6AutoSaveTimer) clearTimeout(state.step6AutoSaveTimer);
  updateStep6AutosaveStatus('自动保存中...');
  state.step6AutoSaveTimer = setTimeout(() => {
    saveStep6Narration({ silent: true });
  }, 700);
}

async function flushStep6Autosave() {
  if (state.step6AutoSaveTimer) {
    clearTimeout(state.step6AutoSaveTimer);
    state.step6AutoSaveTimer = null;
  }
  return saveStep6Narration({ silent: true });
}

async function putStep6NarrationWithRetry(payload) {
  let lastError = null;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const response = await fetch(`/api/projects/${state.currentProject.id}/steps/6/result`, {
        method: 'PUT',
        body: JSON.stringify(payload),
        headers: { 'Content-Type': 'application/json', 'X-PPT-Studio-Request': '1' }
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(data.detail || '保存演讲稿失败');
        error.isHttpError = true;
        throw error;
      }
      return data;
    } catch (error) {
      lastError = error;
      if (error.isHttpError || attempt === 1) break;
      await new Promise(resolve => setTimeout(resolve, 500));
    }
  }
  throw lastError || new Error('保存演讲稿失败');
}

async function saveStep6Narration(options = {}) {
  const silent = !!options.silent;
  if (!narrationData) return true;
  if (state.step6AutoSavePromise) {
    try {
      await state.step6AutoSavePromise;
    } catch (error) {
      // Retry below with the newest editor snapshot.
    }
  }
  saveStep6CurrentState();
  normalizeStep6Data();
  const payload = JSON.parse(JSON.stringify(narrationData));
  if (!silent) showToast('💾 正在保存并校验台词信息...');
  const savePromise = putStep6NarrationWithRetry(payload);
  state.step6AutoSavePromise = savePromise;
  try {
    const res = await savePromise;
    if (res.success) {
      updateStep6AutosaveStatus('已自动保存');
      if (!silent) showToast('🎉 演讲稿修改保存成功！');
      refreshCurrentProjectStatus(6).catch(() => {});
      return true;
    }
  } catch (e) {
    updateStep6AutosaveStatus('保存失败，请重试');
    showToast(`❌ 演讲稿保存失败：${e.message || '网络连接中断'}`);
    return false;
  } finally {
    if (state.step6AutoSavePromise === savePromise) {
      state.step6AutoSavePromise = null;
    }
  }
  return false;
}

// ==================== 可见步骤 6 的音频阶段（内部步骤 7） ====================

async function loadStep7Data() {
  const emptyState = document.getElementById('step7-empty-state');
  const confirmButton = document.getElementById('step6-btn-audio-confirm-next');
  const synthButton = document.getElementById('step7-btn-synthesize');
  const step7Status = state.currentProject?.step_status?.['7'] || 'pending';
  const stepAllowsAudio = ['in_progress', 'completed', 'pending_reconfirmation'].includes(step7Status);

  confirmButton.disabled = true;
  synthButton.style.display = stepAllowsAudio ? 'inline-flex' : 'none';
  emptyState.style.display = 'block';
  document.querySelectorAll('.step6-slide-audio').forEach(slot => {
    slot.innerHTML = '';
    slot.classList.remove('has-audio');
  });

  const [res, audioStatus] = await Promise.all([
    API.get(`/api/projects/${state.currentProject.id}/steps/3/images`),
    API.get(`/api/projects/${state.currentProject.id}/steps/7/audio-status`)
  ]);
  const hasExistingAudio = (audioStatus.slides || []).some(item => item?.audio_exists);
  const canLoadAudio = stepAllowsAudio || hasExistingAudio;
  synthButton.style.display = canLoadAudio ? 'inline-flex' : 'none';
  if (!canLoadAudio) {
    emptyState.innerText = '尚未生成音频。确认旁白后，点击“生成音频”。';
    return;
  }
  if (res.success) {
    const audioBySlide = new Map((audioStatus.slides || []).map(item => [item.slide_id, item]));
    res.images.forEach(img => {
      const slot = Array.from(document.querySelectorAll('.step6-slide-audio'))
        .find(item => item.dataset.audioSlideId === img.slide_id);
      if (!slot) return;
      const audio = audioBySlide.get(img.slide_id);
      slot.classList.add('has-audio');
      if (audio?.audio_exists && !audio?.stale) {
        const audioUrl = `/api/projects/${state.currentProject.id}/slides/${img.slide_id}/audio?t=${Date.now()}`;
        slot.innerHTML = `<audio controls preload="metadata" src="${audioUrl}" class="step7-audio-player" aria-label="${escHtml(img.slide_id)} 音频"></audio>`;
      } else {
        const reason = audio?.stale ? '音频已过期，请重新生成' : '音频尚未生成';
        slot.innerHTML = `<div class="step7-audio-missing">${escHtml(reason)}</div>`;
      }
    });

    const allAudioComplete = audioStatus.complete === true;
    const missingSlides = Array.isArray(audioStatus.missing) ? audioStatus.missing : [];
    if (!allAudioComplete) {
      emptyState.style.display = 'block';
      emptyState.innerText = `部分页面音频尚未生成或已过期：${missingSlides.join('、')}。点击“生成音频”会自动跳过已有音频，只补缺失页面。`;
      confirmButton.disabled = true;
    } else if (step7Status === 'pending_reconfirmation') {
      emptyState.style.display = 'block';
      emptyState.innerText = '旁白或上游内容已变更，请重新生成音频后再确认。';
      confirmButton.disabled = true;
    } else {
      emptyState.style.display = 'none';
      confirmButton.disabled = false;
      document.getElementById('step6-audio-confirm-label').innerText = state.currentProject.audio_confirmed
        ? '进入作品输出'
        : '确认并进入作品输出';
    }
  }
}

async function runStep7TTS() {
  const loading = document.getElementById('step7-loading');
  const synthButton = document.getElementById('step7-btn-synthesize');
  const saveAndTtsButton = document.getElementById('step6-btn-save-and-tts');
  const confirmButton = document.getElementById('step6-btn-audio-confirm-next');
  loading.style.display = 'inline-flex';
  synthButton.disabled = true;
  saveAndTtsButton.disabled = true;
  confirmButton.disabled = true;
  showToast('🔊 正在生成音频；已有且未过期的页面会自动跳过，只补缺失页面...');

  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/7/synthesize`);
    if (res.success) {
      const skipped = Array.isArray(res.skipped) ? res.skipped.length : 0;
      const generated = Array.isArray(res.generated) ? res.generated.length : 0;
      const suffix = skipped ? `（新生成 ${generated} 页，跳过已有 ${skipped} 页）` : '';
      showToast(`🎀 音频生成完成${suffix}，请逐页试听并确认。`);
      await refreshCurrentProjectStatus(6);
      await loadStep7Data();
      return true;
    }

    const failed = Array.isArray(res.failed) ? res.failed.map(item => item.slide_id).filter(Boolean) : [];
    const message = res.message || (failed.length ? `音频部分生成失败：${failed.join('、')}` : '音频生成未完成，请稍后重试。');
    showToast(`⚠️ ${message}`, 7000);
    await refreshCurrentProjectStatus(6);
    await loadStep7Data();
    return false;
  } catch (e) {
    showToast(`音频生成失败：${e.message}`, 7000);
    return false;
  } finally {
    loading.style.display = 'none';
    synthButton.disabled = false;
    saveAndTtsButton.disabled = false;
  }
}

async function saveNarrationAndRunTTS() {
  const saved = await flushStep6Autosave();
  if (!saved) return false;
  showToast('旁白已保存，开始生成音频...');
  return runStep7TTS();
}

async function confirmStep7Audio() {
  const confirmButton = document.getElementById('step6-btn-audio-confirm-next');
  confirmButton.disabled = true;
  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/7/confirm`, {});
    if (res.success) {
      showToast('✅ 音频已确认，准备进入作品输出。');
      await refreshCurrentProjectStatus(6);
      return true;
    }
  } catch (e) {
    showToast(`音频确认失败：${e.message}`, 7000);
    return false;
  } finally {
    confirmButton.disabled = false;
  }
  return false;
}

