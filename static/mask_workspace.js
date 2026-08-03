// Step 5 Mask workspace state, loading, slide navigation, semantic/narration mapping, and view rendering.
// Canvas painting, preview rasterization, animation preview, and draft persistence remain in ui_foundation.js / workflow_state.js / api_client.js.


let manifestData = null;
let manifestProjectId = '';
let step5SourceCanvas = null;

let step2Contract = null; // 用于缓存步骤 2 分镜规划数据

function resetStep5ProjectState() {
  if (state.step5AutoSaveTimer) {
    clearTimeout(state.step5AutoSaveTimer);
    state.step5AutoSaveTimer = null;
  }
  state.step5AutoSavePromise = null;
  state.step5AutoSaveInFlight = false;
  manifestData = null;
  manifestProjectId = '';
  step2Contract = null;
  step5SourceCanvas = null;
  state.canvasState.boxes = [];
  state.canvasState.selectedBoxIndex = -1;
}

const MASK_COLORS = [
  '#E84A5F',
  '#1B998B',
  '#F6AE2D',
  '#3D5A80',
  '#7B2CBF',
  '#2F80ED',
  '#D45113',
  '#4C956C',
  '#C9184A',
  '#0077B6'
];
function getMaskColor(idx) {
  return MASK_COLORS[idx % MASK_COLORS.length];
}

function isValidMaskColor(color) {
  return /^#[0-9a-f]{6}$/i.test(String(color || '').trim());
}

function getBoxColor(maskBox, idx) {
  const storedColor = maskBox?.manual_mask?.color || maskBox?.color;
  return isValidMaskColor(storedColor) ? String(storedColor).trim() : getMaskColor(idx);
}

function claimUniqueMaskColor(preferredColor, idx, usedColors) {
  const preferred = isValidMaskColor(preferredColor) ? String(preferredColor).trim() : getMaskColor(idx);
  if (!usedColors.has(preferred.toUpperCase())) {
    usedColors.add(preferred.toUpperCase());
    return preferred;
  }
  for (let offset = 0; offset < MASK_COLORS.length; offset += 1) {
    const candidate = getMaskColor(idx + offset);
    if (!usedColors.has(candidate.toUpperCase())) {
      usedColors.add(candidate.toUpperCase());
      return candidate;
    }
  }
  usedColors.add(preferred.toUpperCase());
  return preferred;
}

function hexToRgba(hex, alpha) {
  const clean = String(hex || '#111111').replace('#', '');
  const full = clean.length === 3 ? clean.split('').map(ch => ch + ch).join('') : clean;
  const num = parseInt(full, 16);
  if (Number.isNaN(num)) return `rgba(17, 17, 17, ${alpha})`;
  const r = (num >> 16) & 255;
  const g = (num >> 8) & 255;
  const b = num & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function cloneManualMask(mask) {
  if (!mask || typeof mask !== 'object') return { strokes: [] };
  return {
    source: mask.source || '',
    color: mask.color || '',
    bounds: mask.bounds ? { ...mask.bounds } : null,
    rle: mask.rle && mask.rle.encoding === 'row_runs_v1'
      ? {
          encoding: 'row_runs_v1',
          width: Number(mask.rle.width || 1920),
          height: Number(mask.rle.height || 1080),
          runs: Array.isArray(mask.rle.runs)
            ? mask.rle.runs.map(run => [Number(run[0]), Number(run[1]), Number(run[2])])
            : []
        }
      : null,
    strokes: Array.isArray(mask.strokes)
      ? mask.strokes.map(stroke => ({
          color: stroke.color || '',
          size: Number(stroke.size || 42),
          mode: stroke.mode || (stroke.eraser ? 'erase' : 'paint'),
          eraser: !!stroke.eraser,
          points: Array.isArray(stroke.points)
            ? stroke.points.map(point => ({
                x: Number(point.x || 0),
                y: Number(point.y || 0)
              }))
            : []
        }))
      : []
  };
}

function ensureManualMask(maskBox, idx = 0) {
  if (!maskBox.manual_mask || typeof maskBox.manual_mask !== 'object') {
    maskBox.manual_mask = { color: getMaskColor(idx), strokes: [] };
  }
  if (!Array.isArray(maskBox.manual_mask.strokes)) {
    maskBox.manual_mask.strokes = [];
  }
  if (!isValidMaskColor(maskBox.manual_mask.color)) {
    maskBox.manual_mask.color = getMaskColor(idx);
  }
  return maskBox.manual_mask;
}

function getCurrentManifestSlide() {
  return manifestData?.slides?.[state.activeSlideIndex] || null;
}

function getStep2SlideForManifestSlide(manifestSlide = getCurrentManifestSlide()) {
  if (!manifestSlide || !step2Contract?.slides) return null;
  return step2Contract.slides.find(s => s.slide_id === manifestSlide.slide_id) || null;
}

function splitNarrationText(text) {
  const value = String(text || '').trim();
  if (!value) return [];
  const delimiters = new Set(['，', ',', '。', '.', '!', '！', '；', ';', '？', '?']);
  const quotePairs = {
    '“': '”',
    '‘': '’',
    '「': '」',
    '『': '』',
    '《': '》',
    '（': '）',
    '(': ')',
    '[': ']',
    '【': '】',
    '{': '}'
  };
  const inlineQuoteMarks = new Set(['`', '"']);
  const parts = [];
  const stack = [];
  let start = 0;

  for (let i = 0; i < value.length; i += 1) {
    const ch = value[i];
    if (inlineQuoteMarks.has(ch)) {
      if (stack.length && stack[stack.length - 1] === ch) {
        stack.pop();
      } else {
        stack.push(ch);
      }
    } else if (quotePairs[ch]) {
      stack.push(quotePairs[ch]);
    } else if (stack.length && ch === stack[stack.length - 1]) {
      stack.pop();
    }

    const isDecimalPoint = ch === '.' && /\d/.test(value[i - 1] || '') && /\d/.test(value[i + 1] || '');
    const shouldSplit = ch === '\n' || (delimiters.has(ch) && stack.length === 0 && !isDecimalPoint);
    if (shouldSplit) {
      parts.push(value.slice(start, i + 1).trim());
      start = i + 1;
    }
  }

  if (start < value.length) {
    parts.push(value.slice(start).trim());
  }
  return parts.filter(Boolean);
}

function getNarrationFragments(step2Slide = getStep2SlideForManifestSlide()) {
  const beats = step2Slide?.narration_beats || [];
  const fragments = [];
  beats.forEach((beat, beatIdx) => {
    splitNarrationText(beat.spoken_text || '').forEach((text, fragIdx) => {
      fragments.push({
        id: `${beat.id || `beat_${beatIdx + 1}`}::${fragIdx + 1}`,
        beat_id: beat.id || '',
        group_id: beat.group_id || '',
        beat_index: beatIdx,
        fragment_index: fragIdx,
        order: fragments.length + 1,
        text
      });
    });
  });
  return fragments;
}

function getSelectedFragmentIds(maskBox) {
  if (!maskBox) return [];
  if (Array.isArray(maskBox.narration_fragments) && maskBox.narration_fragments.length > 0) {
    return maskBox.narration_fragments.map(fragment => fragment.id).filter(Boolean);
  }
  return [];
}

function getSelectedFragmentText(maskBox, step2Slide = getStep2SlideForManifestSlide()) {
  if (!maskBox) return '';
  if (Array.isArray(maskBox.narration_fragments) && maskBox.narration_fragments.length > 0) {
    return maskBox.narration_fragments.map(fragment => fragment.text).filter(Boolean).join('');
  }
  const beat = getNarrationBeatForBox(maskBox, step2Slide);
  return maskBox.spoken_text || beat?.spoken_text || '';
}

function normalizeMaskBoxNarrationFragments(maskBox, step2Slide) {
  if (!maskBox || !step2Slide) return;
  const fragments = getNarrationFragments(step2Slide);
  if (!fragments.length) return;

  const beatIds = Array.isArray(maskBox.narration_beat_ids)
    ? maskBox.narration_beat_ids.filter(Boolean)
    : [];
  if (maskBox.narration_beat_id && !beatIds.includes(maskBox.narration_beat_id)) {
    beatIds.push(maskBox.narration_beat_id);
  }

  let selected = [];
  if (beatIds.length) {
    selected = fragments.filter(fragment => beatIds.includes(fragment.beat_id));
  } else if (maskBox.narration_group_id) {
    selected = fragments.filter(fragment => fragment.group_id === maskBox.narration_group_id);
  } else if (maskBox.visual_group_id) {
    selected = fragments.filter(fragment => fragment.group_id === maskBox.visual_group_id);
  }

  if (!selected.length) return;
  const normalized = selected.map(fragment => ({
    id: fragment.id,
    beat_id: fragment.beat_id,
    group_id: fragment.group_id,
    text: fragment.text
  }));
  maskBox.narration_fragments = normalized;
  maskBox.narration_beat_ids = [...new Set(normalized.map(item => item.beat_id).filter(Boolean))];
  maskBox.narration_beat_id = maskBox.narration_beat_ids[0] || '';
  const groupIds = [...new Set(normalized.map(item => item.group_id).filter(Boolean))];
  maskBox.narration_group_id = groupIds[0] || maskBox.narration_group_id || maskBox.visual_group_id || '';
  maskBox.spoken_text = normalized.map(item => item.text).join('');
}

function normalizeManifestNarrationFragments() {
  if (!manifestData?.slides || !step2Contract?.slides) return;
  manifestData.slides.forEach(slide => {
    const step2Slide = getStep2SlideForManifestSlide(slide);
    if (!step2Slide) return;
    ['semantic_blocks', 'groups'].forEach(field => {
      if (!Array.isArray(slide[field])) return;
      slide[field].forEach(box => normalizeMaskBoxNarrationFragments(box, step2Slide));
    });
  });
}

function getNarrationBeatForBox(maskBox, step2Slide = getStep2SlideForManifestSlide()) {
  const beats = step2Slide?.narration_beats || [];
  if (!beats.length || !maskBox) return null;
  if (Array.isArray(maskBox.narration_beat_ids) && maskBox.narration_beat_ids.length > 0) {
    const byFirstId = beats.find(beat => beat.id === maskBox.narration_beat_ids[0]);
    if (byFirstId) return byFirstId;
  }
  if (maskBox.narration_beat_id) {
    const byId = beats.find(beat => beat.id === maskBox.narration_beat_id);
    if (byId) return byId;
  }
  if (maskBox.narration_group_id) {
    const byLinkedGroup = beats.find(beat => beat.group_id === maskBox.narration_group_id);
    if (byLinkedGroup) return byLinkedGroup;
  }
  return beats.find(beat => beat.group_id === maskBox.group_id) || null;
}

function isEraseStroke(stroke) {
  return !!stroke?.eraser || String(stroke?.mode || '').toLowerCase() === 'erase';
}

function hasPaintStroke(maskBox) {
  const exactRuns = maskBox?.manual_mask?.rle?.runs;
  if (Array.isArray(exactRuns) && exactRuns.length > 0) return true;
  return (maskBox?.manual_mask?.strokes || []).some(stroke => !isEraseStroke(stroke) && (stroke.points || []).length > 0);
}

function hasVisibleMaskPixels(maskBox) {
  if (!hasPaintStroke(maskBox)) return false;
  return !!maskPixelBounds(maskBox);
}

function isManualEmptyBox(maskBox) {
  return String(maskBox?.group_id || '').startsWith('manual_group_') && !hasVisibleMaskPixels(maskBox);
}

function isSemanticDraftBox(maskBox) {
  return String(maskBox?.source || '') === 'ai_semantic' && !hasVisibleMaskPixels(maskBox);
}

function isDraftMaskBox(maskBox) {
  return isManualEmptyBox(maskBox) || isSemanticDraftBox(maskBox);
}

function copySemanticFields(target, source) {
  if (!target || !source) return target;
  [
    'source',
    'visual_group_id',
    'element_id',
    'visual_type',
    'semantic_element_type',
    'visual_description',
    'semantic_note',
    'semantic_confidence'
  ].forEach(field => {
    if (source[field] !== undefined && source[field] !== null && source[field] !== '') {
      target[field] = source[field];
    }
  });
  return target;
}

function groupToMaskBox(group) {
  const box = group.box || {};
  const x = Number(box.x || 0);
  const y = Number(box.y || 0);
  const w = Number(box.w || 1);
  const h = Number(box.h || 1);
  return copySemanticFields({
    group_id: group.id || group.group_id || '',
    role: group.role || 'content_body',
    text_label: group.visible_text || group.text_label || '',
    visual_anchor: group.visual_anchor || '',
    narration_beat_id: group.narration_beat_id || group.linked_segment_id || '',
    narration_beat_ids: Array.isArray(group.narration_beat_ids) ? [...group.narration_beat_ids] : [],
    narration_group_id: group.narration_group_id || '',
    narration_fragments: Array.isArray(group.narration_fragments) ? JSON.parse(JSON.stringify(group.narration_fragments)) : [],
    spoken_text: group.spoken_text || '',
    reveal: normalizeMaskReveal(group.reveal),
    manual_mask: cloneManualMask(group.manual_mask),
    box: [x, y, x + w, y + h]
  }, group);
}

function normalizeRevealBox(box, idx) {
  return copySemanticFields({
    ...box,
    visual_anchor: box.visual_anchor || '',
    narration_beat_id: box.narration_beat_id || '',
    narration_beat_ids: Array.isArray(box.narration_beat_ids) ? [...box.narration_beat_ids] : [],
    narration_group_id: box.narration_group_id || '',
    narration_fragments: Array.isArray(box.narration_fragments) ? JSON.parse(JSON.stringify(box.narration_fragments)) : [],
    reveal: normalizeMaskReveal(box.reveal),
    manual_mask: cloneManualMask(box.manual_mask || { color: getMaskColor(idx), strokes: [] })
  }, box);
}

function semanticBlockToMaskBox(box, idx) {
  return normalizeRevealBox({
    role: "content_body",
    text_label: `语块 ${idx + 1}`,
    visual_anchor: "",
    spoken_text: "",
    reveal: normalizeMaskReveal(box.reveal),
    box: [860, 460, 1060, 620],
    ...box,
    source: "ai_semantic",
    manual_mask: cloneManualMask(box.manual_mask || { color: getMaskColor(idx), strokes: [] })
  }, idx);
}

function isManualUserMaskBox(box) {
  return String(box?.group_id || box?.id || '').startsWith('manual_group_');
}

function hasLinkedNarration(box) {
  if (String(box?.spoken_text || '').trim()) return true;
  if (String(box?.narration_beat_id || '').trim()) return true;
  if (Array.isArray(box?.narration_beat_ids) && box.narration_beat_ids.some(Boolean)) return true;
  return Array.isArray(box?.narration_fragments)
    && box.narration_fragments.some(fragment => String(fragment?.text || fragment?.id || '').trim());
}

function isDisplayableMaskBox(box) {
  return isManualUserMaskBox(box) || hasLinkedNarration(box);
}

function clearMaskBoxNarration(maskBox) {
  maskBox.narration_fragments = [];
  maskBox.narration_beat_ids = [];
  maskBox.narration_beat_id = '';
  maskBox.narration_group_id = '';
  maskBox.spoken_text = '';
}

function setMaskBoxNarrationFragments(maskBox, fragments) {
  const normalized = Array.isArray(fragments) ? fragments : [];
  maskBox.narration_fragments = normalized;
  maskBox.narration_beat_ids = [...new Set(normalized.map(item => item.beat_id).filter(Boolean))];
  maskBox.narration_beat_id = maskBox.narration_beat_ids[0] || '';
  const groupIds = [...new Set(normalized.map(item => item.group_id).filter(Boolean))];
  maskBox.narration_group_id = groupIds[0] || '';
  maskBox.spoken_text = normalized.map(item => item.text).filter(Boolean).join('');
}

function dedupeMaskBoxNarrationAssignments(boxes) {
  const usedFragmentIds = new Set();
  return boxes.map(box => {
    if (!Array.isArray(box?.narration_fragments) || box.narration_fragments.length === 0) {
      return box;
    }
    const kept = [];
    box.narration_fragments.forEach(fragment => {
      const fragmentId = String(fragment?.id || '').trim();
      if (fragmentId && usedFragmentIds.has(fragmentId)) return;
      kept.push(fragment);
      if (fragmentId) usedFragmentIds.add(fragmentId);
    });
    if (kept.length === box.narration_fragments.length) return box;
    if (kept.length === 0) {
      clearMaskBoxNarration(box);
      return box;
    }
    setMaskBoxNarrationFragments(box, kept);
    return box;
  }).filter(isDisplayableMaskBox);
}

function getSlideMaskBoxes(slide) {
  if (!slide) return [];
  const semanticBoxes = Array.isArray(slide.semantic_blocks)
    ? slide.semantic_blocks.map(semanticBlockToMaskBox)
    : [];
  const semanticIds = new Set(semanticBoxes.map(box => box.group_id).filter(Boolean));

  let baseBoxes = [];
  if (Array.isArray(slide.groups) && slide.groups.length > 0) {
    baseBoxes = slide.groups.map(groupToMaskBox);
  }

  const baseById = new Map(baseBoxes.map(box => [box.group_id, box]));
  const merged = semanticBoxes.map((semanticBox, idx) => {
    const existing = baseById.get(semanticBox.group_id);
    if (!existing) return semanticBlockToMaskBox(semanticBox, idx);
    return {
      ...semanticBox,
      ...existing,
      source: existing.source || semanticBox.source,
      visual_group_id: existing.visual_group_id || semanticBox.visual_group_id,
      semantic_element_type: existing.semantic_element_type || semanticBox.semantic_element_type,
      visual_description: existing.visual_description || semanticBox.visual_description,
      semantic_note: existing.semantic_note || semanticBox.semantic_note,
      semantic_confidence: existing.semantic_confidence || semanticBox.semantic_confidence,
      manual_mask: cloneManualMask(existing.manual_mask || semanticBox.manual_mask)
    };
  });
  baseBoxes.forEach(box => {
    if (!semanticIds.has(box.group_id)) merged.push(box);
  });
  const usedColors = new Set();
  return dedupeMaskBoxNarrationAssignments(merged.filter(isDisplayableMaskBox))
    .map((box, idx) => {
      const manualMask = cloneManualMask(box.manual_mask || { strokes: [] });
      const color = claimUniqueMaskColor(getBoxColor(box, idx), idx, usedColors);
      return {
        ...box,
        manual_mask: {
          ...manualMask,
          color
        }
      };
    });
}

function syncMaskBoxesToSlide(slide, boxes) {
  if (!slide) return;
  boxes = Array.isArray(boxes) ? boxes : [];
  boxes.forEach((maskBox, idx) => {
    if (maskBox?.manual_mask?.strokes?.length || maskBox?.manual_mask?.rle?.runs?.length) {
      updateMaskBoxFromManualMask(idx);
    }
  });
  const readyBoxes = boxes.filter(maskBox => !isDraftMaskBox(maskBox));
  const semanticBoxes = boxes
    .filter(maskBox => String(maskBox?.source || '') === 'ai_semantic')
    .filter(hasLinkedNarration)
    .map((maskBox, idx) => ({
      ...maskBox,
      manual_mask: {
        ...cloneManualMask(maskBox.manual_mask || { strokes: [] }),
        color: getMaskColor(idx)
      }
    }));
  slide.semantic_blocks = JSON.parse(JSON.stringify(semanticBoxes));

  if (!Array.isArray(slide.groups)) {
    slide.groups = [];
  }
  const visibleGroupIds = new Set(readyBoxes.map(maskBox => maskBox.group_id).filter(Boolean));
  slide.groups = slide.groups.filter(group => (
    group?.is_static === true
    || group?.is_static_header === true
    || String(group?.source || '') === 'ai_static_header'
    || visibleGroupIds.has(group.id || group.group_id)
  ));
  readyBoxes.forEach((maskBox, idx) => {
    ensureManualMask(maskBox, idx);
    const [rawX1, rawY1, rawX2, rawY2] = maskBox.box || [0, 0, 1, 1];
    const x1 = Math.max(0, Math.round(Math.min(rawX1, rawX2)));
    const y1 = Math.max(0, Math.round(Math.min(rawY1, rawY2)));
    const x2 = Math.min(1920, Math.round(Math.max(rawX1, rawX2)));
    const y2 = Math.min(1080, Math.round(Math.max(rawY1, rawY2)));
    let group = slide.groups.find(g => g.id === maskBox.group_id);
    if (!group) {
      group = {
        id: maskBox.group_id || `custom_group_${idx + 1}`,
        role: maskBox.role || 'content_body',
        visible_text: maskBox.text_label || '',
        reveal: normalizeMaskReveal(maskBox.reveal),
        padding_px: 32,
        z_index: 40 + idx
      };
      slide.groups.push(group);
    }
    group.reveal = normalizeMaskReveal(maskBox.reveal || group.reveal);
    group.role = maskBox.role || group.role || 'content_body';
    group.source = maskBox.source || group.source || '';
    if (maskBox.text_label) group.visible_text = maskBox.text_label;
    if (maskBox.visual_anchor) group.visual_anchor = maskBox.visual_anchor;
    if (maskBox.visual_group_id) group.visual_group_id = maskBox.visual_group_id;
    if (maskBox.element_id) group.element_id = maskBox.element_id;
    if (maskBox.visual_type) group.visual_type = maskBox.visual_type;
    if (maskBox.semantic_element_type) group.semantic_element_type = maskBox.semantic_element_type;
    if (maskBox.visual_description) group.visual_description = maskBox.visual_description;
    if (maskBox.semantic_note) group.semantic_note = maskBox.semantic_note;
    if (maskBox.semantic_confidence) group.semantic_confidence = maskBox.semantic_confidence;
    if (maskBox.narration_beat_id) group.narration_beat_id = maskBox.narration_beat_id;
    group.narration_beat_ids = Array.isArray(maskBox.narration_beat_ids) ? [...maskBox.narration_beat_ids] : [];
    if (maskBox.narration_group_id) group.narration_group_id = maskBox.narration_group_id;
    group.narration_fragments = Array.isArray(maskBox.narration_fragments) ? JSON.parse(JSON.stringify(maskBox.narration_fragments)) : [];
    if (maskBox.spoken_text) group.spoken_text = maskBox.spoken_text;
    group.manual_mask = cloneManualMask(maskBox.manual_mask || { strokes: [] });
    group.manual_mask.color = getBoxColor(maskBox, idx);
    if (group.manual_mask.strokes.length > 0) {
      group.review_status = "manual_painted";
    }
    group.box = {
      x: x1,
      y: y1,
      w: Math.max(1, x2 - x1),
      h: Math.max(1, y2 - y1)
    };
  });
}

async function loadStep5Data() {
  const projectId = state.currentProject?.id;
  if (!projectId) return;
  await loadStep3VisualSettings();
  try {
    const contractRes = await API.get(`/api/projects/${projectId}/steps/2/result`);
    if (state.currentProject?.id !== projectId) return;
    if (contractRes.success && contractRes.contract) {
      step2Contract = contractRes.contract;
    }
  } catch (e) {}

  const res = await API.get(`/api/projects/${projectId}/steps/5/result`);
  if (state.currentProject?.id !== projectId) return;
  if (res.success && res.manifest) {
    manifestData = res.manifest;
    manifestProjectId = projectId;
    // 智能初始化每一页 slide 的状态并向下兼容
    manifestData.slides.forEach(s => {
      if (!s.status) {
        // 如果存在标注块尚未审核完成，则设为 pending，否则设为 completed
        const needsAdjustment = (s.groups || []).some(g => 
          g.review_status === "needs_manual_adjustment_after_image_gen" || 
          g.review_status === "auto_fitted_needs_review"
        );
        s.status = needsAdjustment ? "pending" : "completed";
      }
    });
    ensureGlobalMaskRevealDefault();
    normalizeManifestNarrationFragments();
    renderStep5Workspace();
    void offerArtifactRepair(res, 'Mask 数据', loadStep5Data);
  }
}

function renderStep5Workspace() {
  updateStep5SemanticButton();
  updateStep5ConfirmButton();
  document.body.classList.toggle('step5-fullscreen-mode', !!state.canvasState.maskFullscreen);
  const fullscreenLabel = document.getElementById('step5-fullscreen-label');
  if (fullscreenLabel) fullscreenLabel.textContent = state.canvasState.maskFullscreen ? '退出全屏' : '放大标注';
  const thumbsContainer = document.getElementById('step5-thumbs');
  thumbsContainer.className = 'step5-slides-grid'; // 改用平铺换行类名
  thumbsContainer.innerHTML = '';
  
  manifestData.slides.forEach((slide, idx) => {
    const btn = document.createElement('div');
    const isCurrent = idx === state.activeSlideIndex;
    btn.className = `step5-slide-btn${isCurrent ? ' active' : ''}`;
    btn.innerHTML = `
      <div style="font-size: 0.85rem; font-weight: bold; color: var(--ink-color);">${slide.slide_id}</div>
    `;
    
    btn.addEventListener('click', () => {
      stopMaskAnimationPreview();
      saveStep5CurrentState();
      state.activeSlideIndex = idx;
      renderStep5Workspace();
    });
    thumbsContainer.appendChild(btn);
  });
  
  // 加载当前 Slide 详情
  const slide = manifestData.slides[state.activeSlideIndex];
  if (slide) {
    // 设置 Canvas 背景图
    const imgUrl = `/api/projects/${state.currentProject.id}/slides/${slide.slide_id}/image?t=${uuid()}`;
    const backgroundImage = document.getElementById('step5-bg-img');
    step5SourceCanvas = null;
    backgroundImage.onload = () => {
      rebuildStep5SourceCache(backgroundImage);
      redrawCanvas();
    };
    backgroundImage.onerror = () => {
      showToast('当前页原图加载失败，请刷新页面后重试。', 5000);
    };
    backgroundImage.src = imgUrl;
    
    // 初始化 canvas 标注框数据并重绘
    state.canvasState.boxes = getSlideMaskBoxes(slide);
    state.canvasState.selectedBoxIndex = -1;
    state.canvasState.draggedBoxIndex = -1;
    state.canvasState.draggedHandle = null;
    state.canvasState.paintMode = false;
    state.canvasState.eraserMode = false;
    state.canvasState.paintingBoxIndex = -1;
    state.canvasState.isPainting = false;
    state.canvasState.currentStroke = null;
    updateBrushSize(state.canvasState.brushSize, false);
    updateEraserSize(state.canvasState.eraserSize, false);
    initCanvasEvents();
    redrawCanvas();
    
    // 渲染右侧属性列表
    renderStep5BoxesForm();
    renderStep5NarrationPanel();
  }
}

function switchStep5Slide(direction) {
  if (!manifestData?.slides?.length) return;
  stopMaskAnimationPreview();
  saveStep5CurrentState();
  const total = manifestData.slides.length;
  state.activeSlideIndex = (state.activeSlideIndex + direction + total) % total;
  invalidateStep5ExactPreview();
  renderStep5Workspace();
  scheduleStep5Autosave();
}

function toggleStep5Fullscreen(force) {
  state.canvasState.maskFullscreen = typeof force === 'boolean'
    ? force
    : !state.canvasState.maskFullscreen;
  document.body.classList.toggle('step5-fullscreen-mode', !!state.canvasState.maskFullscreen);
  const fullscreenLabel = document.getElementById('step5-fullscreen-label');
  if (fullscreenLabel) fullscreenLabel.textContent = state.canvasState.maskFullscreen ? '退出全屏' : '放大标注';
  const canvas = document.getElementById('step5-canvas');
  setTimeout(() => {
    applyMaskCanvasZoom(canvas);
    redrawCanvas({ updateDiagnostics: false });
  }, 0);
}

function uuid() {
  return Math.random().toString(36).substring(2, 6);
}

function aiMaskIssuesForBox(box, slideId) {
  const issues = Array.isArray(window.__aiMaskReviewIssues) ? window.__aiMaskReviewIssues : [];
  const identifiers = new Set([
    box?.id,
    box?.group_id,
    box?.visual_group_id,
    box?.element_id,
  ].map(value => String(value || '')).filter(Boolean));
  return issues.filter(issue => (
    String(issue?.slide_id || '') === String(slideId || '')
    && identifiers.has(String(issue?.group_id || ''))
  ));
}

// 渲染右侧的 box 编辑表单列表
function renderStep5BoxesForm() {
  const container = document.getElementById('step5-boxes-list');
  container.innerHTML = '';
  const currentSlide = getCurrentManifestSlide();
  const step2Slide = getStep2SlideForManifestSlide(currentSlide);
  
  if (!state.canvasState.boxes.length) {
    container.innerHTML = `
      <div class="soft-outline mask-empty-state">
        当前页还没有 Mask 语块。可运行 AI 标注，或点击“添加语块”后直接涂抹。
      </div>
    `;
    return;
  }

  state.canvasState.boxes.forEach((box, idx) => {
    const isSelected = idx === state.canvasState.selectedBoxIndex;
    const isPaintTarget = state.canvasState.paintMode && !state.canvasState.eraserMode && idx === state.canvasState.paintingBoxIndex;
    const isEraseTarget = state.canvasState.paintMode && state.canvasState.eraserMode && idx === state.canvasState.paintingBoxIndex;
    const item = document.createElement('div');
    const reviewIssues = aiMaskIssuesForBox(box, currentSlide?.slide_id);
    const hasBlockingIssue = reviewIssues.some(issue => issue?.severity === 'blocking');
    item.className = `mask-block-card soft-outline${isSelected ? ' highlight-glow' : ''}${isPaintTarget ? ' paint-active' : ''}${isEraseTarget ? ' erase-active' : ''}${reviewIssues.length ? ' ai-review-needed' : ''}${hasBlockingIssue ? ' ai-review-blocking' : ''}`;
    const maskColor = getBoxColor(box, idx);
    item.style.setProperty('--mask-color', maskColor);

    const spokenText = getSelectedFragmentText(box, step2Slide);
    const slidePrefix = currentSlide?.slide_id ? `${currentSlide.slide_id}_` : '';
    const elementId = box.element_id || (
      slidePrefix && String(box.visual_group_id || '').startsWith(slidePrefix)
        ? String(box.visual_group_id).slice(slidePrefix.length)
        : (box.visual_group_id || box.group_id || `el_${String(idx + 1).padStart(3, '0')}`)
    );
    const visualType = box.visual_type || (box.text_label ? 'text' : 'illustration');
    const visualDescription = box.visual_description || box.visual_anchor || box.text_label || '请根据当前图像补充这个语义块的画面描述';
    box.reveal = normalizeMaskReveal(box.reveal);
    item.innerHTML = `
      <div class="mask-block-head">
        <span class="mask-block-number">${idx + 1}</span>
        <span class="mask-block-caption">语块 ${idx + 1}</span>
        ${reviewIssues.length ? `<span class="ai-mask-card-issue-badge" title="${escHtml(reviewIssues.map(issue => issue.message || issue.type).join('\n'))}">${hasBlockingIssue ? '需修正' : '待检查'} · ${reviewIssues.length}</span>` : ''}
        <div class="mask-block-actions">
          <button class="mask-icon-btn${isPaintTarget ? ' active' : ''}" type="button" data-action="paint" title="画笔补充当前语块" aria-label="画笔补充">
            <svg class="icon" viewBox="0 0 24 24"><path d="M12 20h9"></path><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"></path></svg>
          </button>
          <button class="mask-icon-btn${isEraseTarget ? ' active' : ''}" type="button" data-action="erase" title="橡皮擦除当前语块" aria-label="橡皮擦除">
            <svg class="icon" viewBox="0 0 24 24"><path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21"></path><path d="M22 21H7"></path></svg>
          </button>
          <button class="mask-icon-btn mask-delete-btn" type="button" data-action="delete" title="删除语块" aria-label="删除语块">
            <svg class="icon" viewBox="0 0 24 24"><path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="M19 6l-1 14H6L5 6"></path></svg>
          </button>
        </div>
      </div>
      <div class="mask-visual-card">
        <span class="mask-visual-label">画面描述 · ${escHtml(elementId)} · ${escHtml(box.role || 'content_body')} · ${escHtml(visualType)}</span>
        <span class="mask-visual-desc">${escHtml(visualDescription)}</span>
      </div>
      <div class="mask-narration-card">
        <span class="mask-narration-label">关联旁白</span>
        <span class="mask-narration-text">${spokenText ? escHtml(spokenText) : '请在下方旁白中选择片段'}</span>
      </div>
    `;
    
    item.addEventListener('click', () => {
      selectStep5MaskBox(idx);
    });

    item.querySelector('[data-action="paint"]')?.addEventListener('click', (event) => {
      event.stopPropagation();
      startMaskPaint(idx);
    });
    item.querySelector('[data-action="erase"]')?.addEventListener('click', (event) => {
      event.stopPropagation();
      startMaskErase(idx);
    });
    item.querySelector('[data-action="delete"]')?.addEventListener('click', (event) => {
      event.stopPropagation();
      deleteMaskBox(idx);
    });

    container.appendChild(item);
    
  });
}

function renderStep5NarrationPanel() {
  const panel = document.getElementById('step5-narration-panel');
  if (!panel) return;
  const fragments = getNarrationFragments();
  if (!fragments.length) {
    panel.innerHTML = '<div class="step5-narration-empty">当前页暂无演讲旁白。</div>';
    return;
  }
  const selectedByFragment = new Map();
  state.canvasState.boxes.forEach((box, idx) => {
    getSelectedFragmentIds(box).forEach(fragmentId => {
      if (!selectedByFragment.has(fragmentId)) {
        selectedByFragment.set(fragmentId, idx);
      }
    });
  });
  const currentBoxIdx = state.canvasState.selectedBoxIndex;
  const hasCurrentBox = currentBoxIdx >= 0 && currentBoxIdx < state.canvasState.boxes.length;
  panel.innerHTML = `
    <div class="step5-narration-fragments">
      ${fragments.map(fragment => {
        const ownerIdx = selectedByFragment.get(fragment.id);
        const owned = ownerIdx !== undefined;
        const current = owned && ownerIdx === currentBoxIdx;
        const color = owned ? getBoxColor(state.canvasState.boxes[ownerIdx], ownerIdx) : '#777777';
        const title = owned
          ? (current ? '点击取消当前语块与该旁白片段的关联' : `该片段已关联到语块 ${ownerIdx + 1}，点击切换到当前语块`)
          : (hasCurrentBox ? '点击将此旁白片段关联到当前语块' : '请先选中或新建一个语块，再点击关联');
        return `
          <button class="step5-narration-fragment${owned ? ' linked' : ''}${current ? ' current' : ''}${!hasCurrentBox ? ' no-target' : ''}" type="button" data-fragment-id="${escHtml(fragment.id)}" style="--fragment-color:${color};" title="${escHtml(title)}">
            <span class="step5-narration-fragment-index">${fragment.order}</span>
            ${escHtml(fragment.text)}
          </button>
        `;
      }).join('')}
    </div>
  `;
  panel.querySelectorAll('.step5-narration-fragment').forEach(btn => {
    btn.addEventListener('click', () => {
      const fragmentId = btn.getAttribute('data-fragment-id');
      if (fragmentId) toggleStep5FragmentLink(fragmentId);
    });
  });
}

// 手动关联/取消关联/切换关联：演讲稿片段 <-> 当前选中语块
// 一个片段同一时间只能被一个语块关联；点击已关联到当前语块的片段则取消关联
function toggleStep5FragmentLink(fragmentId) {
  if (!fragmentId) return;
  const boxes = state.canvasState.boxes;
  const currentIdx = state.canvasState.selectedBoxIndex;
  if (currentIdx < 0 || currentIdx >= boxes.length) {
    showToast('请先在右侧选中一个语块，或点击"添加语块"新建后再关联旁白。');
    return;
  }
  const currentBox = boxes[currentIdx];
  const fragments = getNarrationFragments();
  const fragment = fragments.find(item => item.id === fragmentId);
  if (!fragment) return;

  invalidateStep5ExactPreview();

  // 找到当前片段的归属
  const ownerIdx = boxes.findIndex(box =>
    Array.isArray(box.narration_fragments) && box.narration_fragments.some(item => item.id === fragmentId)
  );

  // 情况 1：片段已关联到当前语块 → 取消关联
  if (ownerIdx === currentIdx) {
    currentBox.narration_fragments = (currentBox.narration_fragments || []).filter(item => item.id !== fragmentId);
    recomputeMaskBoxNarrationLinks(currentBox);
    renderStep5BoxesForm();
    renderStep5NarrationPanel();
    scheduleStep5Autosave();
    return;
  }

  // 情况 2：片段已关联到其他语块 → 从原语块移除
  if (ownerIdx >= 0) {
    const ownerBox = boxes[ownerIdx];
    ownerBox.narration_fragments = (ownerBox.narration_fragments || []).filter(item => item.id !== fragmentId);
    recomputeMaskBoxNarrationLinks(ownerBox);
  }

  // 情况 3：添加到当前语块（无论之前是否被关联）
  if (!Array.isArray(currentBox.narration_fragments)) currentBox.narration_fragments = [];
  if (!currentBox.narration_fragments.some(item => item.id === fragmentId)) {
    currentBox.narration_fragments.push({
      id: fragment.id,
      beat_id: fragment.beat_id,
      group_id: fragment.group_id,
      text: fragment.text
    });
  }
  recomputeMaskBoxNarrationLinks(currentBox);
  renderStep5BoxesForm();
  renderStep5NarrationPanel();
  scheduleStep5Autosave();
}

// 根据 narration_fragments 重算 box 的 narration_beat_ids / narration_beat_id /
// narration_group_id / spoken_text，保持字段一致性
function recomputeMaskBoxNarrationLinks(maskBox) {
  if (!maskBox) return;
  const frags = Array.isArray(maskBox.narration_fragments) ? maskBox.narration_fragments : [];
  const beatIds = [...new Set(frags.map(item => item.beat_id).filter(Boolean))];
  const groupIds = [...new Set(frags.map(item => item.group_id).filter(Boolean))];
  maskBox.narration_beat_ids = beatIds;
  maskBox.narration_beat_id = beatIds[0] || '';
  maskBox.narration_group_id = groupIds[0] || maskBox.narration_group_id || maskBox.visual_group_id || '';
  maskBox.spoken_text = frags.map(item => item.text).join('');
}

function updateStep5SemanticButton() {
  const btn = document.getElementById('step5-btn-semantic-blocks');
  if (!btn) return;
  btn.disabled = !!state.canvasState.semanticLoading || !!state.canvasState.confirmingMasks;
  btn.classList.toggle('loading', !!state.canvasState.semanticLoading);
  btn.innerHTML = state.canvasState.semanticLoading
    ? `<span class="button-spinner"></span><span class="btn-label">AI 分块中...</span>`
    : `<svg class="icon" viewBox="0 0 24 24"><path d="M4 5h16"></path><path d="M4 12h10"></path><path d="M4 19h16"></path><circle cx="18" cy="12" r="2"></circle></svg><span class="btn-label">AI 语义分块</span>`;
}

function updateStep5ConfirmButton(message = '') {
  const btn = document.getElementById('step5-btn-confirm-next');
  const status = document.getElementById('step5-confirm-status');
  if (!btn) return;

  const confirming = !!state.canvasState.confirmingMasks;
  const aiBusy = !!state.canvasState.semanticLoading;

  btn.classList.toggle('loading', confirming);
  btn.disabled = confirming || aiBusy;

  if (confirming) {
    btn.innerHTML = `<span class="button-spinner"></span><span class="btn-label">正在确认并构建切层...</span>`;
    btn.title = '正在保存标注并构建后续视频所需的 Mask 切层，请稍候';
    if (status) {
      status.style.display = 'flex';
      status.classList.remove('error');
      status.innerHTML = `<span class="button-spinner"></span><span>${message || '处理中：正在保存标注并构建切层，请不要重复点击。'}</span>`;
    }
    return;
  }

  btn.innerHTML = `确认标注，进入下一步 <svg class="icon" viewBox="0 0 24 24" style="width:14px; height:14px; stroke-width:2.5;"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>`;
  btn.title = aiBusy
    ? 'AI 标注相关任务正在处理中，请稍候'
    : '确认全部 Mask 标注并构建切层';

  if (status) {
    const isMessageError = !!message && /失败|不能确认|漏标/.test(message);
    status.style.display = message ? 'flex' : 'none';
    status.classList.toggle('error', isMessageError);
    status.textContent = message || '';
  }
}

function selectStep5MaskBox(idx, shouldScroll = true) {
  state.canvasState.selectedBoxIndex = idx;
  redrawCanvas();
  renderStep5NarrationPanel();
  document.querySelectorAll('#step5-boxes-list > div').forEach((el, elIdx) => {
    const isSelected = elIdx === idx;
    el.classList.toggle('highlight-glow', isSelected);
    if (isSelected && shouldScroll) {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  });
}

function focusAiMaskIssue(issue) {
  if (!issue || !manifestData?.slides?.length) return false;
  const slideIndex = manifestData.slides.findIndex(slide => (
    String(slide?.slide_id || '') === String(issue.slide_id || '')
  ));
  if (slideIndex < 0) return false;
  state.activeSlideIndex = slideIndex;
  renderStep5Workspace();
  const groupId = String(issue.group_id || '');
  if (!groupId) return true;
  setTimeout(() => {
    const boxIndex = state.canvasState.boxes.findIndex(box => [
      box?.id,
      box?.group_id,
      box?.visual_group_id,
      box?.element_id,
    ].some(value => String(value || '') === groupId));
    if (boxIndex >= 0) {
      selectStep5MaskBox(boxIndex, true);
    }
  }, 80);
  return true;
}

window.loadStep5Data = loadStep5Data;
window.renderStep5Workspace = renderStep5Workspace;
window.focusAiMaskIssue = focusAiMaskIssue;
window.getCurrentStep5SlideId = () => String(getCurrentManifestSlide()?.slide_id || '');
