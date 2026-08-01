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

function step3GeneratingPreviewHtml(message = '生成中', subtitle = 'AI 正在绘制图片，请稍候...') {
  return `
    <div class="step3-generating-preview" role="status" aria-live="polite">
      <span class="loading-spinner" aria-hidden="true"></span>
      <strong>${escHtml(message)}</strong>
      <small>${escHtml(subtitle)}</small>
    </div>
  `;
}

function updateStep3BatchButton() {
  const button = document.getElementById('step3-btn-batch-generate');
  if (!button) return;
  const hasSlides = step3ImageOrder.length > 0;
  const generationInProgress = step3GeneratingSlides.size > 0;
  const uploadInProgress = step3UploadingSlides.size > 0;
  button.disabled = !hasSlides || step3BatchGenerating || generationInProgress || uploadInProgress;
  button.classList.toggle('is-loading', step3BatchGenerating);
  const uploadLabel = document.getElementById('step3-batch-upload-label');
  const uploadInput = document.getElementById('step3-batch-upload');
  uploadLabel?.classList.toggle('is-disabled', generationInProgress || uploadInProgress);
  if (uploadInput) uploadInput.disabled = generationInProgress || uploadInProgress;
  const deleteAllButton = document.getElementById('step3-btn-delete-all-images');
  if (deleteAllButton) {
    deleteAllButton.disabled = generationInProgress || uploadInProgress || !step3ImageOrder.some(item => item.exists);
  }
  button.innerHTML = step3BatchGenerating
    ? `<span class="step3-button-spinner" aria-hidden="true"></span> 批量生成中 ${step3BatchCompleted}/${step3BatchTotal}`
    : `<svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;">
         <rect x="3" y="4" width="18" height="16" rx="2"></rect>
         <circle cx="8.5" cy="9" r="1.5"></circle>
         <path d="m5 17 4.5-4 3.2 2.8 2.3-2.1 4 3.3"></path>
         <path d="M18 2v4M16 4h4"></path>
       </svg> 一键批量生成图片`;
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
  // 优先加载分镜数据，保证即使无图片也能渲染占位卡
  if (!state.slides || state.slides.length === 0) {
    const contractRes = await API.get(`/api/projects/${state.currentProject.id}/steps/2/result`);
    if (contractRes.success && contractRes.contract) {
      state.slides = contractRes.contract.slides || [];
    }
  }

  await loadStep3VisualSettings();

  // 获取每个 slide 拼接的 Prompt
  try {
    const promptRes = await API.get(`/api/projects/${state.currentProject.id}/steps/3/prompts`);
    if (promptRes.success) {
      slidePrompts = promptRes.prompts || [];
      step3BatchPrompt = promptRes.batch_prompt || '';
    }
  } catch(e) {}
  
  // 获取生成的图片文件状态
  await refreshStep3Images();
}

function normalizeStep3BackgroundColor(value) {
  const color = String(value || '').trim().toUpperCase();
  return /^#[0-9A-F]{6}$/.test(color) ? color : '';
}

async function loadStep3VisualSettings() {
  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/3/visual-settings`);
  step3VideoBackground = normalizeStep3BackgroundColor(res.video_background) || '#FEFDF9';
}

async function refreshStep3Images() {
  let images = [];
  try {
    const res = await API.get(`/api/projects/${state.currentProject.id}/steps/3/images`);
    if (res.success) {
      images = res.images || [];
      step3OrderVersion = String(res.order_version || '');
    }
  } catch(e) {}

  // 如果后端返回空列表但分镜数据已有，自动生成占位展示
  if (images.length === 0 && state.slides && state.slides.length > 0) {
    images = state.slides.map(s => ({ slide_id: s.slide_id, exists: false, url: '' }));
  }
  step3ImageOrder = images;
  syncStep3ActiveSlideIndex();
  renderStep3Grid();
  if (step3ImageOrder.length > 0 && step3ImageOrder.every(img => img.exists)) {
    refreshCurrentProjectStatus(3).catch(() => {});
  }
}

function renderStep3Grid() {
  const grid = document.getElementById('step3-images-grid');
  if (!grid) return;
  grid.innerHTML = '';

  const hasSlides = step3ImageOrder.length > 0;
  const missingCount = step3ImageOrder.filter(img => !img.exists).length;
  const staleProvenanceCount = step3ImageOrder.filter(img => img.exists && img.provenance?.valid !== true).length;
  const allImagesReady = hasSlides && missingCount === 0 && staleProvenanceCount === 0
    && step3GeneratingSlides.size === 0 && step3UploadingSlides.size === 0;
  updateStep3BatchButton();
  const confirmBtn = document.getElementById('step3-btn-confirm');
  if (confirmBtn) {
    confirmBtn.style.display = hasSlides ? 'inline-flex' : 'none';
    confirmBtn.disabled = !allImagesReady;
    confirmBtn.title = allImagesReady
      ? ''
      : (step3GeneratingSlides.size > 0 || step3UploadingSlides.size > 0
        ? '图片正在生成或上传中'
        : staleProvenanceCount > 0
          ? `${staleProvenanceCount} 张图片来源待更新，请重新生成或上传`
          : `还缺少 ${missingCount} 张图片`);
  }

  step3ImageOrder.forEach((img, idx) => {
    const card = document.createElement('div');
    card.className = 'card soft-elevation slide-card-draggable';
    card.style.cssText = 'padding: 0.5rem 0.8rem 0.8rem; position: relative; background: var(--bg-color); margin-bottom: 0;';

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
    const isGenerating = step3GeneratingSlides.has(img.slide_id);
    const isUploading = step3UploadingSlides.has(img.slide_id);
    const isBusy = isGenerating || isUploading;
    const canMoveImage = img.exists
      && !isBusy
      && !step3ImageReassigning
      && step3GeneratingSlides.size === 0;
    const isCurrentGenerating = step3CurrentGenerating === img.slide_id;  // 当前正在生成的卡片
    const isQueued = isGenerating && !isCurrentGenerating;  // 排队等待中的卡片
    const isCurrentUploading = step3CurrentUploading === img.slide_id;
    const isUploadQueued = isUploading && !isCurrentUploading;
    if (isCurrentGenerating) {
      card.classList.add('is-current-generating');
    }
    const provenanceReady = img.provenance?.valid === true;
    const previewHtml = isCurrentUploading
      ? step3GeneratingPreviewHtml('上传中', '正在处理并裁剪这张图片...')
      : isUploadQueued
      ? step3GeneratingPreviewHtml('等待上传', '图片已加入上传队列...')
      : isCurrentGenerating
      ? step3GeneratingPreviewHtml('生成中', 'AI 正在绘制图片，请稍候...')
      : isQueued
      ? step3GeneratingPreviewHtml('排队中', '等待上一张生成完成...')
      : img.exists
      ? `<img src="${img.url}" style="width: 100%; height: 100%; object-fit: cover;" alt="${escHtml(slideTitle)}">`
      : `<div style="width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 0.3rem; color: #888; background: #fffdf5;">
           <svg class="icon" viewBox="0 0 24 24" style="width: 20px; height: 20px; color: #aaa;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"></path></svg>
           <span style="font-size: 0.75rem; font-weight: 500;">暂无图片，点击上传/生成</span>
         </div>`;

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
          <span class="step3-card-status ${isCurrentGenerating ? 'is-current-generating' : ''} ${isQueued ? 'is-queued' : ''} ${isGenerating ? 'is-generating' : ''}" style="color: ${img.exists || isGenerating ? 'var(--ink-color)' : '#888'}; background: ${isCurrentGenerating ? 'var(--color-primary-base)' : (isQueued ? 'var(--secondary-color)' : (img.exists && provenanceReady ? 'var(--success-color)' : '#f3f4f6'))}; ${isCurrentGenerating ? 'color: #fff;' : ''}">
            ${isCurrentGenerating ? '生成中' : (isQueued ? '排队中' : (img.exists ? (provenanceReady ? '已就绪' : '来源待更新') : '待生成'))}
          </span>
        </div>
        <div class="step3-card-actions">
          <button class="success step3-card-action step3-ai-action" data-slide-id="${escHtml(img.slide_id)}" ${isBusy ? 'disabled' : ''}>
            ${isGenerating ? '生成中' : 'AI生成'}
          </button>
          ${img.exists ? `
            <button class="danger step3-card-action step3-delete-action" data-slide-id="${escHtml(img.slide_id)}" ${isBusy ? 'disabled' : ''}>
              删除
            </button>
          ` : '<button class="step3-card-action step3-action-placeholder" type="button" disabled aria-hidden="true" tabindex="-1">删除</button>'}
          <label class="btn secondary step3-card-action step3-upload-action ${isBusy ? 'is-disabled' : ''}">
            ${isUploading ? '上传中' : '上传'}
            <input class="step3-upload-input" data-slide-id="${escHtml(img.slide_id)}" type="file" accept="image/*" ${isBusy ? 'disabled' : ''} style="display: none;">
          </label>
        </div>
      </div>
      <div class="step3-card-heading">
        <span class="step3-card-position">第 ${idx + 1} 页</span>
        <strong class="step3-card-title" title="${escHtml(slideTitle)}" data-slide-id="${escHtml(img.slide_id)}">${escHtml(slideTitle)}</strong>
      </div>

      <div class="img-preview-container" style="width: 100%; aspect-ratio: 16/9; position: relative; border: 2px solid var(--ink-color); border-radius: 6px; overflow: hidden; background: #fffdf5;">
        ${previewHtml}
      </div>
    `;
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
    grid.appendChild(card);
  });
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
    });
    step3OrderVersion = String(res.order_version || step3OrderVersion);
    showToast('图片与 Slide 标题的对应关系已更新');
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

async function moveStep3Image(idx, direction) {
  await reorderStep3Images(idx, idx + direction);
}

window.moveStep3Image = moveStep3Image;

function openStep3AI(slideId) {
  state.activeSlideIndex = step3ImageOrder.findIndex(img => img.slide_id === slideId);
  step3CandidateReady = false;
  step3CandidateSlideId = '';
  document.getElementById('step3-slide-id-label').innerText = slideId;
  const pInfo = slidePrompts.find(p => p.slide_id === slideId);
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

async function uploadStep3ImageById(slideId, input) {
  const file = input.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('slide_id', slideId);
  formData.append('file', file);
  step3UploadingSlides.add(slideId);
  step3CurrentUploading = slideId;
  renderStep3Grid();
  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/3/upload`, formData);
    if (res.success) {
      showToast('图片上传成功！');
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

function deleteStep3Image(slideId) {
  showCustomConfirm(
    '删除图片',
    `确定删除 ${slideId} 的本地图片吗？该页已有的全部 Mask 和切层素材也会一起清除。`,
    async () => {
      const res = await API.delete(`/api/projects/${state.currentProject.id}/steps/3/images/${encodeURIComponent(slideId)}`);
      if (res.success) {
        await refreshStep3Images();
        await refreshCurrentProjectStatus(3);
        showToast('图片及该页 Mask 已删除。');
      }
    }
  );
}

window.deleteStep3Image = deleteStep3Image;

function deleteAllStep3Images() {
  if (step3UploadingSlides.size > 0 || step3GeneratingSlides.size > 0) {
    showToast('请等待当前图片生成或上传完成后再批量删除。');
    return;
  }
  const imageCount = step3ImageOrder.filter(item => item.exists).length;
  if (imageCount === 0) {
    showToast('当前没有可删除的图片。');
    return;
  }
  showCustomConfirm(
    '批量删除图片',
    `确定删除全部 ${imageCount} 张图片吗？所有相关 Mask、切层和下游素材也会一起清除。此操作不可撤销。`,
    async () => {
      const res = await API.delete(`/api/projects/${state.currentProject.id}/steps/3/images`);
      if (res.success) {
        await refreshStep3Images();
        await refreshCurrentProjectStatus(3);
        showToast(`已删除 ${res.deleted_count || imageCount} 张图片及相关素材。`);
      }
    }
  );
}

window.deleteAllStep3Images = deleteAllStep3Images;

// 批量上传处理
async function handleStep3BatchUpload(e) {
  const files = Array.from(e.target.files);
  if (files.length === 0) return;
  
  // 按分镜顺序逐一匹配上传
  const slideIds = step3ImageOrder.map(img => img.slide_id);
  const queuedSlideIds = slideIds.slice(0, files.length);
  queuedSlideIds.forEach(slideId => step3UploadingSlides.add(slideId));
  renderStep3Grid();
  
  for (let i = 0; i < files.length; i++) {
    const slideId = slideIds[i];
    if (!slideId) break;
    step3CurrentUploading = slideId;
    renderStep3Grid();
    const formData = new FormData();
    formData.append('slide_id', slideId);
    formData.append('file', files[i]);
    try {
      await API.post(`/api/projects/${state.currentProject.id}/steps/3/upload`, formData);
    } catch(err) {
      showToast(`⚠️ 第 ${i+1} 张上传失败`);
    } finally {
      step3UploadingSlides.delete(slideId);
      step3CurrentUploading = null;
      renderStep3Grid();
    }
  }
  queuedSlideIds.forEach(slideId => step3UploadingSlides.delete(slideId));
  step3CurrentUploading = null;
  showToast('批量上传完成！');
  await refreshStep3Images();
  await refreshCurrentProjectStatus(3);
  e.target.value = '';
}

async function generateAllStep3Images() {
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
    showToast(`❌ ${missingPrompt.slideId} 缺少生图提示词，请先重新进入本步骤。`);
    return;
  }

  step3BatchGenerating = true;
  step3BatchCompleted = 0;
  step3BatchTotal = tasks.length;
  tasks.forEach(task => step3GeneratingSlides.add(task.slideId));
  renderStep3Grid();
  showToast(`🎨 已开始批量生成 ${tasks.length} 张图片。`);

  let successCount = 0;
  const failedSlides = [];
  try {
    for (const task of tasks) {
      step3CurrentGenerating = task.slideId;  // 标记当前正在生成的卡片
      renderStep3Grid();
      try {
        const formData = new FormData();
        formData.append('slide_id', task.slideId);
        formData.append('prompt', task.prompt);
        formData.append('preview', 'false');
        const res = await API.post(
          `/api/projects/${state.currentProject.id}/steps/3/generate`,
          formData
        );
        if (res.success) {
          successCount += 1;
          const image = step3ImageOrder.find(item => item.slide_id === task.slideId);
          if (image) {
            image.exists = true;
            image.url = res.image_url;
          }
        }
      } catch (error) {
        failedSlides.push(task.slideId);
      } finally {
        step3GeneratingSlides.delete(task.slideId);
        step3CurrentGenerating = null;  // 清除当前生成标记
        step3BatchCompleted += 1;
        renderStep3Grid();
      }
    }
  } finally {
    step3BatchGenerating = false;
    step3BatchCompleted = 0;
    step3BatchTotal = 0;
    step3GeneratingSlides.clear();
    step3CurrentGenerating = null;
    await refreshStep3Images();
    await refreshCurrentProjectStatus(3);
  }

  if (failedSlides.length > 0) {
    showToast(`⚠️ 已生成 ${successCount} 张，失败：${failedSlides.join('、')}`, 5000);
  } else {
    showToast(`✅ ${successCount} 张图片已全部生成完成！`);
  }
}


// AI 生成单张候选图片，确认后才替换当前图片。
async function generateStep3Image() {
  const slideId = document.getElementById('step3-slide-id-label').innerText;
  const prompt = document.getElementById('step3-prompt-input').value.trim();
  
  if (!prompt) {
    showToast('⚠️ 提示词不能为空');
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
  const imageModel = state.settings?.image_model || 'gpt-image-1';
  const imageSize = state.settings?.image_size || '1024x1024';
  showToast(`🎨 正在调用 ${imageModel} 合成 ${imageSize} 候选图...`);

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
      showToast('候选图片已生成。确认画面后点击“替换原图”。');
    }
  } catch(e) {
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
  const applyButton = document.getElementById('step3-btn-apply-candidate');
  applyButton.disabled = true;
  try {
    const res = await API.post(
      `/api/projects/${state.currentProject.id}/steps/3/apply-candidate`,
      { slide_id: slideId }
    );
    if (res.success) {
      await refreshStep3Images();
      await refreshCurrentProjectStatus(3);
      closeStep3AIModal();
      showToast('候选图片已替换原图，该页旧 Mask 已清除。');
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
    showToast('🔒 所有图片已确认并锁定！进入标注阶段。');
    navigateToStep(5);
  }
}

