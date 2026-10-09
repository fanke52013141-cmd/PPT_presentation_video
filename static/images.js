// Step 3 image state, grid/preview rendering, upload, generation, ordering, and confirmation.
// Prompt settings and global style management remain separate from this workflow module.


let slidePrompts = [];
let step3BatchPrompt = '';
// 固定分镜槽位；拖拽只改变槽位中的图片，不改变 slide_id 或分镜顺序。
let step3ImageOrder = []; // [{slide_id, exists, url}]
let step3OrderVersion = '';
let step3ImageReassigning = false;
let step3DraggedIndex = -1;
let step3CandidateReady = false;
let step3CandidateSlideId = '';
const step3GeneratingSlides = new Set();
const step3UploadingSlides = new Set();
let step3BatchGenerating = false;
let step3BatchCompleted = 0;
let step3BatchTotal = 0;
let step3CurrentGenerating = null;  // 当前正在生成的 slideId（区别于排队中）
let step3CurrentUploading = null;
let step3VideoBackground = '#FEFDF9';
let step3LoadState = 'idle';
let step3LoadError = '';
let step3BatchStopRequested = false;

function resetStep3ProjectState() {
  step3GeneratingSlides.clear();
  step3UploadingSlides.clear();
  step3BatchGenerating = false;
  step3BatchCompleted = 0;
  step3BatchTotal = 0;
  step3CurrentGenerating = null;
  step3CurrentUploading = null;
  step3ImageOrder = [];
  slidePrompts = [];
  step3BatchPrompt = '';
  step3LoadState = 'idle';
  step3LoadError = '';
  step3BatchStopRequested = false;
}

window.resetStep3ProjectState = resetStep3ProjectState;

function step3GeneratingPreviewHtml(message = '生成中', subtitle = '正在生成图片') {
  const queued = message.includes('排队') || message.includes('等待');
  return `<div class="step3-generating-preview" role="status" aria-live="polite" aria-label="${escHtml(subtitle)}" aria-busy="${!queued}" data-task-state="${queued ? 'queued' : 'running'}">
    ${queued ? `<span class="page-task-waiting">${escHtml(message)}</span>` : '<span class="loading-spinner" aria-hidden="true"></span>'}
  </div>`;
}

// 标题栏排序规则（2026-10-06 用户裁决）：所有按钮从左到右按工作流排列，
// 主 CTA「进入 AI Mask 标注」固定最右；动态插入的视频背景/批量下载/批量删除
// 无论何时创建，统一由这里归位。
function normalizeStep3ToolbarOrder() {
  const toolbar = document.querySelector('#step-panel-3 .workflow-toolbar');
  if (!toolbar) return;
  const order = [
    'step3-btn-prompt-settings',
    'step3-btn-style',
    'step3-btn-ip-character',
    'step3-btn-background-settings',
    'step3-batch-upload-label',
    'step3-btn-copy-prompts',
    'step3-btn-batch-generate',
    'step3-btn-stop-queue',
    'step3-btn-download-all-images',
    'step3-btn-delete-all-images',
    'step3-btn-confirm',
  ];
  const divider = toolbar.querySelector('.workflow-titlebar-divider');
  order.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    toolbar.appendChild(el);
    if (id === 'step3-btn-prompt-settings' && divider) toolbar.appendChild(divider);
  });
}

function updateStep3BatchButton() {
  const button = document.getElementById('step3-btn-batch-generate');
  if (!button) return;
  const stop = document.getElementById('step3-btn-stop-queue');
  if (stop) {
    stop.hidden = !step3BatchGenerating;
    stop.disabled = step3BatchStopRequested;
    stop.textContent = step3BatchStopRequested ? '正在停止…' : '停止后续排队';
  }
  const hasSlides = step3ImageOrder.length > 0;
  const generationInProgress = step3GeneratingSlides.size > 0;
  const uploadInProgress = step3UploadingSlides.size > 0;
  setDisabledReason(button, !hasSlides || step3BatchGenerating || generationInProgress || uploadInProgress);
  button.classList.toggle('is-loading', step3BatchGenerating);
  const uploadLabel = document.getElementById('step3-batch-upload-label');
  const uploadInput = document.getElementById('step3-batch-upload');
  uploadLabel?.classList.toggle('is-disabled', generationInProgress || uploadInProgress);
  if (uploadInput) uploadInput.disabled = generationInProgress || uploadInProgress;
  const deleteAllButton = document.getElementById('step3-btn-delete-all-images');
  if (deleteAllButton) {
    setDisabledReason(deleteAllButton, generationInProgress || uploadInProgress || !step3ImageOrder.some(item => item.exists));
    ensureStep3BatchDownloadButton(deleteAllButton);
  }
  button.innerHTML = step3BatchGenerating
    ? `<span class="step3-button-spinner" aria-hidden="true"></span> 批量生图中 ${step3BatchCompleted}/${step3BatchTotal}`
    : `批量生图`;
  normalizeStep3ToolbarOrder();
}

function setStep3SlideGenerating(slideId, generating) {
  if (generating) {
    step3GeneratingSlides.add(slideId);
  } else {
    step3GeneratingSlides.delete(slideId);
  }
  renderStep3Grid();
}

async function loadStep3Data() {
  const projectId = state.currentProject?.id;
  const sessionVersion = workspaceNavigationVersion;
  if (!projectId) return;
  step3LoadState = 'loading';
  step3LoadError = '';
  renderStep3Grid();
  try {
  // 优先加载分镜数据，保证即使无图片也能渲染占位卡
  if (!state.slides || state.slides.length === 0) {
    const contractRes = await API.getOptional(`/api/projects/${projectId}/steps/2/result`);
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
    if (contractRes.success && contractRes.contract) {
      state.slides = contractRes.contract.slides || [];
    }
  }

  if (!state.slides?.length) {
    step3ImageOrder = [];
    slidePrompts = [];
    step3LoadState = 'ready';
    renderStep3Grid();
    return;
  }

  await loadStep3VisualSettings(projectId, sessionVersion);
  if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;

  // 获取每个 slide 拼接的 Prompt
  try {
    const promptRes = await API.getOptional(`/api/projects/${projectId}/steps/3/prompts`);
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
    if (promptRes.success) {
      slidePrompts = promptRes.prompts || [];
      step3BatchPrompt = promptRes.batch_prompt || '';
    }
  } catch(e) { throw e; }
  
  // 获取生成的图片文件状态
  await refreshStep3Images(projectId, sessionVersion);
  } catch (error) {
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
    step3LoadState = 'error';
    step3LoadError = error?.message || '无法加载图片';
  } finally {
    if (isCurrentWorkspaceProject(projectId, sessionVersion)) {
      if (step3LoadState === 'loading') step3LoadState = 'ready';
      renderStep3Grid();
    }
  }
}

function normalizeStep3BackgroundColor(value) {
  const color = String(value || '').trim().toUpperCase();
  return /^#[0-9A-F]{6}$/.test(color) ? color : '';
}

async function loadStep3VisualSettings(
  projectId = state.currentProject?.id,
  sessionVersion = workspaceNavigationVersion,
) {
  if (!projectId) return;
  const res = await API.get(`/api/projects/${projectId}/steps/3/visual-settings`);
  if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
  step3VideoBackground = normalizeStep3BackgroundColor(res.video_background) || '#FEFDF9';
}

async function refreshStep3Images(
  projectId = state.currentProject?.id,
  sessionVersion = workspaceNavigationVersion,
) {
  if (!projectId) return;
  let images = [];
  try {
    const res = await API.get(`/api/projects/${projectId}/steps/3/images`);
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
    if (res.success) {
      images = (res.images || []).map(image => ({...image, generating: (res.active_slide_ids || []).includes(image.slide_id)}));
      step3OrderVersion = String(res.order_version || '');
    }
  } catch(e) { throw e; }

  // 如果后端返回空列表但分镜数据已有，自动生成占位展示
  if (images.length === 0 && state.slides && state.slides.length > 0) {
    images = state.slides.map(s => ({ slide_id: s.slide_id, exists: false, url: '' }));
  }
  if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
  step3ImageOrder = images;
  syncStep3ActiveSlideIndex();
  renderStep3Grid();
  if (step3ImageOrder.length > 0 && step3ImageOrder.every(img => img.exists)) {
    refreshCurrentProjectStatus(3).catch(() => {});
  }
}

function step3PortraitColumnCount(width) {
  return Math.max(1, Math.min(6, Math.floor((width + 16) / 256)));
}
let step3GridResizeObserver;
function updateStep3GridColumns(grid) {
  grid.style.setProperty('--step3-portrait-columns', step3PortraitColumnCount(grid.clientWidth));
}
function renderStep3Grid() {
  const grid = document.getElementById('step3-images-grid');
  if (!grid) return;
  const geometry = getProjectCanvasGeometry();
  grid.dataset.canvasOrientation = geometry.orientation;
  updateStep3GridColumns(grid);
  if (!step3GridResizeObserver && typeof ResizeObserver !== 'undefined') {
    step3GridResizeObserver = new ResizeObserver(() => updateStep3GridColumns(grid));
    step3GridResizeObserver.observe(grid);
  }
  const previousCards = new Map(Array.from(grid.children).map(card => [card.dataset.slideId, card]));
  const retainedCards = new Set();
  let cursor = grid.firstElementChild;

  if (step3LoadState === 'loading' || step3LoadState === 'error' || !step3ImageOrder.length) {
    grid.replaceChildren();
    const empty = document.createElement('div');
    empty.className = 'ws-empty step3-empty';
    empty.setAttribute('role', 'status');
    const message = document.createElement('p');
    message.textContent = step3LoadState === 'loading' ? '正在加载分镜与图片…'
      : step3LoadState === 'error' ? `图片加载失败：${step3LoadError}`
        : '还没有可生成的画面。请先完成第 2 步分镜规划。';
    setUiTaskState(message, step3LoadState === 'loading' ? 'loading' : step3LoadState === 'error' ? 'error' : 'pending', message.textContent);
    empty.appendChild(message);
    if (step3LoadState !== 'loading') {
      const action = document.createElement('button');
      action.type = 'button';
      action.className = 'secondary';
      action.textContent = step3LoadState === 'error' ? '重新加载' : '返回分镜规划';
      action.addEventListener('click', () => step3LoadState === 'error' ? loadStep3Data() : navigateToStep(2));
      empty.appendChild(action);
    }
    grid.appendChild(empty);
  }

  const hasSlides = step3ImageOrder.length > 0;
  const missingCount = step3ImageOrder.filter(img => !img.exists).length;
  const staleProvenanceCount = step3ImageOrder.filter(img => img.exists && img.provenance?.valid !== true).length;
  const allImagesReady = hasSlides && missingCount === 0 && staleProvenanceCount === 0
    && step3GeneratingSlides.size === 0 && step3UploadingSlides.size === 0;
  updateStep3BatchButton();
  const confirmBtn = document.getElementById('step3-btn-confirm');
  if (confirmBtn) {
    confirmBtn.style.display = hasSlides ? 'inline-flex' : 'none';
    setDisabledReason(confirmBtn, !allImagesReady);
  }

  if (step3LoadState === 'loading' || step3LoadState === 'error') return;
  step3ImageOrder.forEach((img, idx) => {
    const card = document.createElement('div');
    card.className = 'card soft-elevation slide-card-draggable step3-image-card';
    card.style.cssText = 'position: relative; margin-bottom: 0;';

    card.addEventListener('dragover', (e) => {
      if (step3DraggedIndex < 0 || step3DraggedIndex === idx) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      card.classList.add('drag-over');
    });

    card.addEventListener('dragleave', (e) => {
      if (!card.contains(e.relatedTarget)) card.classList.remove('drag-over');
    });

    card.addEventListener('drop', async (e) => {
      e.preventDefault();
      card.classList.remove('drag-over');
      const draggedIdx = Number.parseInt(e.dataTransfer.getData('text/plain'), 10);
      step3DraggedIndex = -1;
      if (!Number.isNaN(draggedIdx)) {
        await reorderStep3Images(draggedIdx, idx);
      }
    });

    const promptInfo = slidePrompts.find(item => item.slide_id === img.slide_id);
    const slideInfo = state.slides.find(item => item.slide_id === img.slide_id);
    const slideTitle = promptInfo?.title || slideInfo?.main_title || '未命名 Slide';
    const isGenerating = img.generating || step3GeneratingSlides.has(img.slide_id);
    const isUploading = step3UploadingSlides.has(img.slide_id);
    const isBusy = isGenerating || isUploading;
    const canMoveImage = img.exists
      && !isBusy
      && !step3ImageReassigning
      && step3GeneratingSlides.size === 0;
    const isCurrentGenerating = img.generating || step3CurrentGenerating === img.slide_id;  // 当前正在生成的卡片
    const isQueued = isGenerating && !isCurrentGenerating;  // 排队等待中的卡片
    const isCurrentUploading = step3CurrentUploading === img.slide_id;
    const isUploadQueued = isUploading && !isCurrentUploading;
    if (isCurrentGenerating) {
      card.classList.add('is-current-generating');
    }
    const provenanceReady = img.provenance?.valid === true;
    // 三态（2026-10-06 用户裁决 + Stitch 参考稿）：生成中 / 完成 / 待生成；
    // 排队与上传并入「生成中」，来源过期并入「待生成」，差异只留在 title。
    const statusBusy = img.generating || isGenerating || isUploading;
    const statusDone = !statusBusy && img.exists && provenanceReady;
    const statusClass = statusBusy ? 'is-generating' : (statusDone ? 'is-done' : 'is-pending');
    const imageConfirmed = state.currentProject?.step_status?.['4'] === 'completed';
    const statusLabel = statusBusy ? (isQueued || isUploadQueued ? '排队中' : isUploading ? '上传中' : '生成中') : (statusDone ? imageConfirmed ? '完成' : '已生成' : '待生成');
    const statusTitle = !statusBusy && img.exists && !provenanceReady ? '图片来源已过期，需重新生成或上传' : '';
    const previewHtml = isCurrentUploading
      ? step3GeneratingPreviewHtml('上传中', '正在处理并裁剪这张图片...')
      : isUploadQueued
      ? step3GeneratingPreviewHtml('等待上传', '图片已加入上传队列...')
      : isCurrentGenerating
      ? step3GeneratingPreviewHtml('生成中', 'AI 正在绘制图片，请稍候...')
      : isQueued
      ? step3GeneratingPreviewHtml('排队中', '等待上一张生成完成...')
      : img.exists
      ? `<img src="${escHtml(img.url)}" style="width: 100%; height: 100%; object-fit: contain; display: block;" alt="${escHtml(slideTitle)}">`
      : `<div style="width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 0.3rem; color: #888; background: #fffdf5;">
           <svg class="icon" viewBox="0 0 24 24" style="width: 20px; height: 20px; color: #aaa;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"></path></svg>
           <span style="font-size: 0.75rem; font-weight: 500;">暂无图片，点击上传/生成</span>
         </div>`;

    const previous = previousCards.get(String(img.slide_id));
    const previewKey = JSON.stringify([previewHtml, geometry.aspectRatio]);
    const renderKey = JSON.stringify([state.currentProject?.id, idx, slideTitle, previewKey,
      canMoveImage, isBusy, isGenerating, isUploading, statusClass, statusLabel, statusTitle]);
    if (previous?.dataset.renderKey === renderKey) {
      retainedCards.add(previous);
      if (previous !== cursor) grid.insertBefore(previous, cursor);
      cursor = previous.nextElementSibling;
      return;
    }
    card.dataset.slideId = img.slide_id;
    card.dataset.renderKey = renderKey;
    card.dataset.previewKey = previewKey;
    card.innerHTML = `
      <div class="step3-card-header">
        <div class="step3-card-identity">
          <button class="slide-drag-handle" type="button" draggable="${canMoveImage ? 'true' : 'false'}" ${canMoveImage ? '' : 'disabled'} title="拖动当前图片，调整它与 Slide 标题的对应关系" aria-label="移动第 ${idx + 1} 页当前图片，分镜顺序保持不变">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="9" cy="5" r="1.4"></circle><circle cx="15" cy="5" r="1.4"></circle>
              <circle cx="9" cy="12" r="1.4"></circle><circle cx="15" cy="12" r="1.4"></circle>
              <circle cx="9" cy="19" r="1.4"></circle><circle cx="15" cy="19" r="1.4"></circle>
            </svg>
          </button>
          <span class="step3-card-status ${statusClass} ui-task-state" role="status" aria-live="polite" aria-busy="${statusBusy}" data-task-state="${statusBusy ? isQueued || isUploadQueued ? 'queued' : 'running' : statusDone ? 'done' : 'pending'}"${statusTitle ? ` title="${escHtml(statusTitle)}"` : ''}>${statusLabel}</span>
        </div>
        <div class="step3-card-actions">
          <button class="danger step3-card-action step3-delete-action" data-slide-id="${escHtml(img.slide_id)}" ${isBusy ? 'disabled' : ''}>删除</button>
          <label class="btn secondary step3-card-action step3-upload-action ${isBusy ? 'is-disabled' : ''}">
            ${isUploading ? '上传中' : '上传'}
            <input class="step3-upload-input" data-slide-id="${escHtml(img.slide_id)}" type="file" accept="image/*" ${isBusy ? 'disabled' : ''} style="display: none;">
          </label>
          <button class="success step3-card-action step3-ai-action" data-slide-id="${escHtml(img.slide_id)}" ${isBusy ? 'disabled' : ''}>
            ${isGenerating ? '生成中' : 'AI生成'}
          </button>
        </div>
      </div>
      <div class="step3-card-heading">
        <span class="step3-card-position">第 ${idx + 1} 页</span>
        <strong class="step3-card-title" title="${escHtml(slideTitle)}" data-slide-id="${escHtml(img.slide_id)}">${escHtml(slideTitle)}</strong>
      </div>

      <div class="img-preview-container" style="width: 100%; aspect-ratio: ${(typeof getProjectCanvasGeometry === 'function' ? getProjectCanvasGeometry().aspectRatio : '16 / 9')}; position: relative; border: 2px solid var(--ink-color); border-radius: 6px; overflow: hidden; background: #fffdf5;">
        ${previewHtml}
      </div>
    `;
    if (previous?.dataset.previewKey === previewKey) {
      card.querySelector('.img-preview-container').replaceWith(previous.querySelector('.img-preview-container'));
    }
    const dragHandle = card.querySelector('.slide-drag-handle');
    card.querySelector('.step3-ai-action')?.addEventListener('click', (event) => {
      event.stopPropagation();
      openStep3AI(img.slide_id);
    });
    card.querySelector('.step3-upload-input')?.addEventListener('change', (event) => {
      uploadStep3ImageById(img.slide_id, event.currentTarget);
    });
    card.querySelector('.step3-delete-action')?.addEventListener('click', (event) => {
      event.stopPropagation();
      deleteStep3Image(img.slide_id);
    });
    dragHandle.addEventListener('click', (e) => e.stopPropagation());
    dragHandle.addEventListener('dragstart', (e) => {
      step3DraggedIndex = idx;
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', String(idx));
      card.classList.add('is-dragging');
    });
    dragHandle.addEventListener('dragend', () => {
      step3DraggedIndex = -1;
      document.querySelectorAll('.slide-card-draggable').forEach(item => {
        item.classList.remove('is-dragging', 'drag-over');
      });
    });
    dragHandle.addEventListener('keydown', async (e) => {
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
      e.preventDefault();
      const direction = ['ArrowLeft', 'ArrowUp'].includes(e.key) ? -1 : 1;
      await reorderStep3Images(idx, idx + direction);
    });
    retainedCards.add(card);
    grid.insertBefore(card, cursor);
    cursor = card.nextElementSibling;
  });
  if (step3ImageOrder.length) {
    Array.from(grid.children).forEach(card => { if (!retainedCards.has(card)) card.remove(); });
  }
}

function syncStep3ActiveSlideIndex() {
  const openSlideId = document.getElementById('step3-slide-id-label')?.innerText;
  if (openSlideId && openSlideId !== '--') {
    state.activeSlideIndex = state.slides.findIndex(slide => slide.slide_id === openSlideId);
  }
}

async function reorderStep3Images(draggedIdx, targetIdx) {
  if (
    draggedIdx < 0 ||
    targetIdx < 0 ||
    draggedIdx >= step3ImageOrder.length ||
    targetIdx >= step3ImageOrder.length ||
    draggedIdx === targetIdx ||
    step3ImageReassigning
  ) return;

  if (!step3ImageOrder[draggedIdx]?.exists) {
    showToast('当前位置没有图片，无法移动', 'error');
    return;
  }

  const affected = step3ImageOrder.slice(Math.min(draggedIdx, targetIdx), Math.max(draggedIdx, targetIdx) + 1);
  const changes = [];
  for (const image of affected) {
    const choice = await getStep3ReplacementVersion(image.slide_id);
    if (!choice) return;
    changes.push({ slide_id: image.slide_id, ...choice });
  }

  // slide_id 是固定分镜槽位，只对图片数据做插入式移动。
  step3ImageOrder = moveStep3ImageAssignment(step3ImageOrder, draggedIdx, targetIdx);
  step3ImageReassigning = true;
  renderStep3Grid();

  const projectId = state.currentProject.id;
  try {
    const res = await API.put(`/api/projects/${projectId}/steps/3/image-order`, {
      from_index: draggedIdx,
      to_index: targetIdx,
      order_version: step3OrderVersion,
      changes,
    });
    step3OrderVersion = String(res.order_version || step3OrderVersion);
    await refreshCurrentProjectStatus(3);
  } catch (error) {
    showToast('图片移动失败，已恢复服务器中的最新对应关系', 'error');
  } finally {
    step3ImageReassigning = false;
    if (state.currentProject?.id === projectId) {
      await refreshStep3Images();
    }
  }
}

function openStep3AI(slideId) {
  state.activeSlideIndex = step3ImageOrder.findIndex(img => img.slide_id === slideId);
  step3CandidateReady = false;
  step3CandidateSlideId = '';
  // 隐藏 span 承载 slide_id（syncStep3ActiveSlideIndex/generateStep3Image 读取），
  // 标题展示改用「第 N 页 · 页面标题」，不把内部 ID 暴露给用户。
  document.getElementById('step3-slide-id-label').innerText = slideId;
  const pInfo = slidePrompts.find(p => p.slide_id === slideId);
  const slideInfo = state.slides.find(item => item.slide_id === slideId);
  const slideTitle = pInfo?.title || slideInfo?.main_title || '';
  const slideDisplay = `第 ${state.activeSlideIndex + 1} 页${slideTitle ? ` · ${slideTitle}` : ''}`;
  document.getElementById('step3-slide-display-label').innerText = slideDisplay;
  document.getElementById('step3-prompt-input').value = pInfo ? pInfo.prompt : '';
  const imgInfo = step3ImageOrder.find(img => img.slide_id === slideId);
  const prevEl = document.getElementById('step3-preview-box');
  document.getElementById('step3-preview-label').innerText = '当前图片预览';
  document.getElementById('step3-candidate-status').style.display = 'none';
  document.getElementById('step3-btn-apply-candidate').style.display = 'none';
  if (imgInfo && imgInfo.exists) {
    prevEl.innerHTML = `<img src="${imgInfo.url}" alt="${slideId} 当前图片">`;
  } else {
    prevEl.innerHTML = '<span>暂无图片</span>';
  }
  document.getElementById('modal-step3-ai').style.display = 'flex';
  document.getElementById('step3-prompt-input').focus();
}

window.openStep3AI = openStep3AI;

function closeStep3AIModal() {
  document.getElementById('modal-step3-ai').style.display = 'none';
  step3CandidateReady = false;
  step3CandidateSlideId = '';
}

window.closeStep3AIModal = closeStep3AIModal;

async function getStep3ReplacementVersion(slideId) {
  const preview = await API.get(
    `/api/projects/${state.currentProject.id}/steps/3/images/${encodeURIComponent(slideId)}/change-preview`
  );
  // Keep recoverable source assets; the version still prevents a stale write.
  return { disposition: 'keep', expected_version: preview.version || '' };
}

async function uploadStep3ImageById(slideId, input) {
  const file = input.files[0];
  if (!file) return;
  // 与后端 MAX_IMAGE_UPLOAD_BYTES=20MB 保持一致，避免上传后才报错
  const MAX_IMAGE_UPLOAD_BYTES = 20 * 1024 * 1024;
  if (file.size > MAX_IMAGE_UPLOAD_BYTES) {
    showInlineNotice('图片超过 20MB 限制，请压缩后重试');
    input.value = '';
    return;
  }
  const impactChoice = await getStep3ReplacementVersion(slideId);
  if (!impactChoice) {
    input.value = '';
    return;
  }
  const formData = new FormData();
  formData.append('slide_id', slideId);
  formData.append('file', file);
  formData.append('disposition', impactChoice.disposition);
  formData.append('expected_version', impactChoice.expected_version);
  step3UploadingSlides.add(slideId);
  step3CurrentUploading = slideId;
  renderStep3Grid();
  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/3/upload`, formData);
    if (res.success) {
      await refreshStep3Images();
      await refreshCurrentProjectStatus(3);
    }
  } finally {
    step3UploadingSlides.delete(slideId);
    if (step3CurrentUploading === slideId) step3CurrentUploading = null;
    input.value = '';
    renderStep3Grid();
  }
}

window.uploadStep3ImageById = uploadStep3ImageById;

function step3SlideLabel(slideId) {
  const index = state.slides.findIndex(slide => slide.slide_id === slideId);
  const slide = state.slides[index];
  return index >= 0 ? `第 ${index + 1} 页《${slide.main_title || slide.slide_title || '未命名'}》` : '当前页';
}

function stopStep3GenerationQueue() {
  step3BatchStopRequested = true;
  updateStep3BatchButton();
}

async function deleteStep3Image(slideId) {
  if (!await confirmAction('移除图片', `确定移除${step3SlideLabel(slideId)}的图片吗？旧图片和 Mask 将保存在归档中，可通过恢复归档重新使用。`)) return;
  const impactChoice = await getStep3ReplacementVersion(slideId);
  if (!impactChoice) return;
  const params = new URLSearchParams(impactChoice);
  const res = await API.delete(
    `/api/projects/${state.currentProject.id}/steps/3/images/${encodeURIComponent(slideId)}?${params}`
  );
  if (res.success) {
    await refreshStep3Images();
    await refreshCurrentProjectStatus(3);
  }
}

window.deleteStep3Image = deleteStep3Image;

async function deleteAllStep3Images() {
  // 按钮在生成/上传期间与无图可删时均为禁用态，这里只保留静默守卫。
  if (step3UploadingSlides.size > 0 || step3GeneratingSlides.size > 0) return;
  const imageCount = step3ImageOrder.filter(item => item.exists).length;
  if (imageCount === 0) return;
  if (!await confirmAction('批量移除图片', `确定移除当前项目的 ${imageCount} 张图片吗？旧图片和 Mask 将保存在归档中，可通过恢复归档重新使用。`)) return;
  const changes = [];
  for (const image of step3ImageOrder.filter(item => item.exists)) {
    const choice = await getStep3ReplacementVersion(image.slide_id);
    if (!choice) return;
    changes.push({ slide_id: image.slide_id, ...choice });
  }
  const res = await API.delete(`/api/projects/${state.currentProject.id}/steps/3/images`, { changes });
  if (res.success) {
    await refreshStep3Images();
    await refreshCurrentProjectStatus(3);
  }
}

window.deleteAllStep3Images = deleteAllStep3Images;

function ensureStep3BatchDownloadButton(deleteAllButton) {
  const disabled = step3GeneratingSlides.size > 0
    || step3UploadingSlides.size > 0
    || !step3ImageOrder.some(item => item.exists);
  if (deleteAllButton) deleteAllButton.disabled = disabled;
  let button = document.getElementById('step3-btn-download-all-images');
  if (!button) {
    button = document.createElement('button');
    button.id = 'step3-btn-download-all-images';
    button.type = 'button';
    button.className = 'secondary step3-download-all-images';
    button.innerHTML = `<svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 3v12"></path></svg> 批量下载`;
    button.addEventListener('click', downloadAllStep3Images);
    document.querySelector('#step-panel-3 .workflow-toolbar')?.appendChild(button);
  }
  button.disabled = disabled;
  normalizeStep3ToolbarOrder();
}

window.normalizeStep3ToolbarOrder = normalizeStep3ToolbarOrder;

async function downloadAllStep3Images() {
  const projectId = state.currentProject?.id;
  const imageCount = step3ImageOrder.filter(item => item.exists).length;
  if (!projectId || imageCount === 0) return;

  const button = document.getElementById('step3-btn-download-all-images');
  const originalHtml = button?.innerHTML;
  if (button) {
    button.disabled = true;
    button.innerHTML = '<span class="button-spinner" aria-hidden="true"></span> 正在打包…';
  }
  try {
    const blob = await API.getBinary(`/api/projects/${encodeURIComponent(projectId)}/steps/3/images/download`);
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    const projectName = String(state.currentProject?.name || '项目')
      .replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_')
      .replace(/[ .]+$/g, '')
      .slice(0, 120)
      .replace(/[ .]+$/g, '') || '项目';
    anchor.download = `${projectName}.zip`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
  } finally {
    if (button) {
      button.innerHTML = originalHtml;
      updateStep3BatchButton();
    }
  }
}

window.downloadAllStep3Images = downloadAllStep3Images;

function installStep3BatchDownloadButton() {
  const toolbar = document.querySelector('#step-panel-3 .step3-toolbar-row');
  if (!toolbar) return;
  const placeButton = () => {
    const deleteAllButton = document.getElementById('step3-btn-delete-all-images');
    if (!deleteAllButton) return false;
    ensureStep3BatchDownloadButton(deleteAllButton);
    return true;
  };
  if (placeButton()) return;

  const observer = new MutationObserver(() => {
    if (placeButton()) observer.disconnect();
  });
  observer.observe(toolbar, { childList: true });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', installStep3BatchDownloadButton);
} else {
  installStep3BatchDownloadButton();
}

// 批量上传处理
async function handleStep3BatchUpload(e) {
  const projectId = state.currentProject?.id;
  const sessionVersion = workspaceNavigationVersion;
  if (!projectId) return;
  const files = Array.from(e.target.files).sort((a, b) => a.lastModified - b.lastModified);
  if (files.length === 0) return;

  // 按分镜顺序逐一匹配上传（文件按最后修改时间升序：最早创建的排最前）
  const slideIds = step3ImageOrder.map(img => img.slide_id);
  const queuedSlideIds = slideIds.slice(0, files.length);
  queuedSlideIds.forEach(slideId => step3UploadingSlides.add(slideId));
  renderStep3Grid();

  for (let i = 0; i < files.length; i++) {
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) break;
    const slideId = slideIds[i];
    if (!slideId) break;
    step3CurrentUploading = slideId;
    renderStep3Grid();
    const formData = new FormData();
    formData.append('slide_id', slideId);
    formData.append('file', files[i]);
    try {
      const impactChoice = await getStep3ReplacementVersion(slideId);
      if (!impactChoice) continue;
      formData.append('disposition', impactChoice.disposition);
      formData.append('expected_version', impactChoice.expected_version);
      const res = await API.post(`/api/projects/${projectId}/steps/3/upload`, formData);
      if (!isCurrentWorkspaceProject(projectId, sessionVersion)) break;
      if (res && res.success) {
        // 上传成功：立即更新内存中的图片状态，图片随下方重绘马上显示，无需等全部传完
        const target = step3ImageOrder.find(item => item.slide_id === slideId);
        if (target) {
          target.exists = true;
          target.url = res.image_url || `/api/projects/${projectId}/slides/${encodeURIComponent(slideId)}/image?t=${Date.now()}`;
          target.provenance = { valid: true };
        }
      }
    } catch(err) {
      showToast(`第 ${i + 1} 张图片上传失败`, 6000);
    } finally {
      if (isCurrentWorkspaceProject(projectId, sessionVersion)) {
        step3UploadingSlides.delete(slideId);
        if (step3CurrentUploading === slideId) step3CurrentUploading = null;
        renderStep3Grid();
      }
    }
  }
  if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
  queuedSlideIds.forEach(slideId => step3UploadingSlides.delete(slideId));
  step3CurrentUploading = null;
  // 全部完成后拉取一次服务端权威列表，补齐 provenance 等完整信息，保证与后端一致
  await refreshStep3Images(projectId, sessionVersion);
  await refreshCurrentProjectStatus(3);
  e.target.value = '';
}

async function generateAllStep3Images() {
  const projectId = state.currentProject?.id;
  const sessionVersion = workspaceNavigationVersion;
  if (!projectId) return;
  if (step3BatchGenerating || step3ImageOrder.length === 0) return;

  const tasks = step3ImageOrder.map(image => {
    const promptInfo = slidePrompts.find(item => item.slide_id === image.slide_id);
    return {
      slideId: image.slide_id,
      prompt: String(promptInfo?.prompt || '').trim()
    };
  });
  const missingPrompt = tasks.find(task => !task.prompt);
  if (missingPrompt) {
    showInlineNotice(`${step3SlideLabel(missingPrompt.slideId)}缺少生图提示词，请重新加载本步骤。`);
    return;
  }

  step3BatchGenerating = true;
  step3BatchStopRequested = false;
  step3BatchCompleted = 0;
  step3BatchTotal = tasks.length;
  tasks.forEach(task => step3GeneratingSlides.add(task.slideId));
  renderStep3Grid();

  const failedSlides = [];
  const busySlides = [];
  const skippedSlides = [];
  try {
    for (const task of tasks) {
      if (!isCurrentWorkspaceProject(projectId, sessionVersion) || step3BatchStopRequested) break;
      step3CurrentGenerating = task.slideId;  // 标记当前正在生成的卡片
      renderStep3Grid();
      try {
        const impactChoice = await getStep3ReplacementVersion(task.slideId);
        if (!impactChoice) {
          skippedSlides.push(task.slideId);
          continue;
        }
        const formData = new FormData();
        formData.append('slide_id', task.slideId);
        formData.append('prompt', task.prompt);
        formData.append('preview', 'false');
        formData.append('disposition', impactChoice.disposition);
        formData.append('expected_version', impactChoice.expected_version);
        const res = await API.post(
          `/api/projects/${projectId}/steps/3/generate`,
          formData
        );
        if (!isCurrentWorkspaceProject(projectId, sessionVersion)) break;
        if (res.success) {
          const image = step3ImageOrder.find(item => item.slide_id === task.slideId);
          if (image) {
            image.exists = true;
            image.url = res.image_url;
          }
        }
      } catch (error) {
        // 后端 409：该页已有生成任务在跑（如单张候选图窗口），跳过而不是算失败。
        if (String(error?.message || '').includes('正在生成图片')) {
          busySlides.push(task.slideId);
        } else {
          failedSlides.push(task.slideId);
        }
      } finally {
        step3GeneratingSlides.delete(task.slideId);
        step3CurrentGenerating = null;  // 清除当前生成标记
        step3BatchCompleted += 1;
        renderStep3Grid();
      }
    }
  } finally {
    if (state.currentProject?.id !== projectId) return;
    step3BatchGenerating = false;
    step3BatchCompleted = 0;
    step3BatchTotal = 0;
    step3GeneratingSlides.clear();
    step3CurrentGenerating = null;
    await refreshStep3Images(projectId, workspaceNavigationVersion);
    await refreshCurrentProjectStatus(3);
  }

  // 批量结果只通过卡片状态呈现；失败属于真实错误，走 Toast（error-only 策略）。
  if (failedSlides.length > 0) {
    showToast(`图片生成失败：${failedSlides.map(slideId => step3SlideLabel(slideId)).join('、')}`, 6000);
  } else if (busySlides.length > 0 || skippedSlides.length > 0) {
    showToast(`已跳过正在生成的页面：${[...busySlides, ...skippedSlides].map(slideId => step3SlideLabel(slideId)).join('、')}`, 5000);
  }
}


// AI 生成单张候选图片，确认后才替换当前图片。
async function generateStep3Image() {
  const slideId = document.getElementById('step3-slide-id-label').innerText;
  const prompt = document.getElementById('step3-prompt-input').value.trim();
  
  if (!prompt) {
    showFieldError(document.getElementById('step3-prompt-input'), '提示词不能为空');
    return;
  }

  step3CandidateReady = false;
  step3CandidateSlideId = '';
  setStep3SlideGenerating(slideId, true);
  document.getElementById('step3-loading').style.display = 'none';
  document.getElementById('step3-btn-generate').disabled = true;
  document.getElementById('step3-preview-label').innerText = 'AI 图片生成中';
  document.getElementById('step3-candidate-status').style.display = 'none';
  document.getElementById('step3-btn-apply-candidate').style.display = 'none';
  document.getElementById('step3-preview-box').innerHTML = step3GeneratingPreviewHtml();

  let generated = false;
  try {
    const formData = new FormData();
    formData.append('slide_id', slideId);
    formData.append('prompt', prompt);
    formData.append('preview', 'true');
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/3/generate`, formData);
    if (res.success) {
      const activeSlideId = document.getElementById('step3-slide-id-label').innerText;
      const modalOpen = document.getElementById('modal-step3-ai').style.display === 'flex';
      if (!modalOpen || activeSlideId !== slideId) return;
      step3CandidateReady = true;
      step3CandidateSlideId = slideId;
      generated = true;
      document.getElementById('step3-preview-label').innerText = 'AI 候选图片预览';
      document.getElementById('step3-candidate-status').style.display = 'inline-flex';
      document.getElementById('step3-preview-box').innerHTML =
        `<img src="${res.candidate_url}" alt="${slideId} AI 候选图片">`;
      document.getElementById('step3-btn-apply-candidate').style.display = 'inline-flex';
    }
  } catch(e) {
    const busy = String(e?.message || '').includes('正在生成图片');
    showToast(busy ? `${slideId} 正在生成图片，请等待当前任务完成` : `${slideId} 图片生成失败`, 'error');
  } finally {
    document.getElementById('step3-loading').style.display = 'none';
    document.getElementById('step3-btn-generate').disabled = false;
    setStep3SlideGenerating(slideId, false);
    const activeSlideId = document.getElementById('step3-slide-id-label').innerText;
    const modalOpen = document.getElementById('modal-step3-ai').style.display === 'flex';
    if (!generated && modalOpen && activeSlideId === slideId) {
      const image = step3ImageOrder.find(item => item.slide_id === slideId);
      document.getElementById('step3-preview-label').innerText = '当前图片预览';
      document.getElementById('step3-preview-box').innerHTML = image?.exists
        ? `<img src="${image.url}" alt="${slideId} 当前图片">`
        : '<span>暂无图片</span>';
    }
  }
}

async function applyStep3Candidate() {
  const slideId = document.getElementById('step3-slide-id-label').innerText;
  if (!step3CandidateReady || step3CandidateSlideId !== slideId) {
    showToast('请先生成一张候选图片。');
    return;
  }
  const impactChoice = await getStep3ReplacementVersion(slideId);
  if (!impactChoice) return;
  const applyButton = document.getElementById('step3-btn-apply-candidate');
  applyButton.disabled = true;
  try {
    const res = await API.post(
      `/api/projects/${state.currentProject.id}/steps/3/apply-candidate`,
      { slide_id: slideId, ...impactChoice }
    );
    if (res.success) {
      await refreshStep3Images();
      await refreshCurrentProjectStatus(3);
      closeStep3AIModal();
    }
  } finally {
    applyButton.disabled = false;
  }
}

window.applyStep3Candidate = applyStep3Candidate;

async function confirmStep3Images() {
  const res = await API.post(`/api/projects/${state.currentProject.id}/steps/3/confirm`);
  if (res.success) {
    await refreshCurrentProjectStatus(5);
    navigateToStep(5);
  }
}
