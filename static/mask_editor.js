// Step 5 Canvas painting, mask preview, animation preview, draft persistence, and confirmation.
// Workspace state/render helpers live in mask_workspace.js; shared modal/API utilities live in ui_foundation.js / workflow_state.js / api_client.js.

function maskCanvasGeometry() {
  return typeof getProjectCanvasGeometry === 'function'
    ? getProjectCanvasGeometry()
    : { width: 1920, height: 1080, aspectRatio: '16 / 9' };
}

function syncMaskCanvasDimensions(canvas) {
  if (!canvas) return maskCanvasGeometry();
  const geometry = maskCanvasGeometry();
  if (canvas.width !== geometry.width) canvas.width = geometry.width;
  if (canvas.height !== geometry.height) canvas.height = geometry.height;
  const container = document.getElementById('canvas-container');
  if (container) {
    container.style.aspectRatio = geometry.aspectRatio;
    container.style.setProperty('--project-aspect-ratio', geometry.aspectRatio);
    container.style.setProperty('--project-aspect-ratio-scale', String(geometry.width / geometry.height));
  }
  const animationCanvas = document.getElementById('animation-preview-canvas');
  if (animationCanvas) {
    animationCanvas.width = geometry.width;
    animationCanvas.height = geometry.height;
    animationCanvas.closest('.animation-preview-stage')?.style.setProperty('aspect-ratio', geometry.aspectRatio);
  }
  return geometry;
}

function updateBrushSize(value, shouldRedraw = true) {
  const size = Math.max(100, Math.min(200, Number(value) || 140));
  state.canvasState.brushSize = size;
  const input = document.getElementById('step5-brush-size');
  const label = document.getElementById('step5-brush-size-value');
  if (input) input.value = String(size);
  if (label) label.textContent = String(size);
  refreshMaskToolCursor();
  if (shouldRedraw) redrawCanvas();
}

function updateEraserSize(value, shouldRedraw = true) {
  const size = Math.max(100, Math.min(200, Number(value) || 100));
  state.canvasState.eraserSize = size;
  const input = document.getElementById('step5-eraser-size');
  const label = document.getElementById('step5-eraser-size-value');
  if (input) input.value = String(size);
  if (label) label.textContent = String(size);
  refreshMaskToolCursor();
  if (shouldRedraw) redrawCanvas();
}

function startMaskTool(idx, eraser) {
  const maskBox = state.canvasState.boxes[idx];
  if (!maskBox) return;
  ensureManualMask(maskBox, idx);
  state.canvasState.paintMode = true;
  state.canvasState.eraserMode = !!eraser;
  state.canvasState.paintingBoxIndex = idx;
  state.canvasState.selectedBoxIndex = idx;
  redrawCanvas();
  renderStep5BoxesForm();
  renderStep5NarrationPanel();
  showToast(eraser ? '橡皮已启用，在画面中拖动可擦除当前语块。' : '画笔已启用，在画面中拖动可补充当前语块。');
}

function startMaskPaint(idx) {
  startMaskTool(idx, false);
}

function startMaskErase(idx) {
  startMaskTool(idx, true);
}

function stopMaskPaint() {
  state.canvasState.paintMode = false;
  state.canvasState.eraserMode = false;
  state.canvasState.paintingBoxIndex = -1;
  state.canvasState.isPainting = false;
  state.canvasState.currentStroke = null;
  hideMaskToolCursor();
  redrawCanvas();
  renderStep5BoxesForm();
}

function createCurrentSlideBlock() {
  invalidateStep5ExactPreview();
  const idx = state.canvasState.boxes.length;
  state.canvasState.boxes.push({
    group_id: `manual_group_${Date.now().toString(36)}_${idx + 1}`,
    role: 'content_body',
    text_label: `语块 ${idx + 1}`,
    narration_beat_id: '',
    narration_beat_ids: [],
    narration_fragments: [],
    spoken_text: '',
    manual_mask: { source: 'manual', color: getMaskColor(idx), strokes: [] },
    reveal: normalizeMaskReveal({ type: 'crop_fade_up' }),
    box: (() => {
      const { width, height } = maskCanvasGeometry();
      return [Math.round(width * 0.45), Math.round(height * 0.43), Math.round(width * 0.55), Math.round(height * 0.57)];
    })()
  });
  startMaskPaint(idx);
  scheduleStep5Autosave();
}

function clearCurrentSlideMaskAnnotations() {
  if (!state.canvasState.boxes.length) return;
  showCustomConfirm(
    '清除当前页标注',
    '将清除当前 Slide 的 AI Mask 与手动修正，其他页面不受影响。',
    () => {
      invalidateStep5ExactPreview();
      state.canvasState.boxes = [];
      stopMaskPaint();
      saveStep5CurrentState();
      renderStep5BoxesForm();
      renderStep5NarrationPanel();
      scheduleStep5Autosave();
    }
  );
}

window.deleteMaskBox = function(idx) {
  invalidateStep5ExactPreview();
  state.canvasState.boxes.splice(idx, 1);
  if (state.canvasState.paintingBoxIndex === idx) {
    stopMaskPaint();
  } else if (state.canvasState.paintingBoxIndex > idx) {
    state.canvasState.paintingBoxIndex -= 1;
  }
  state.canvasState.selectedBoxIndex = -1;
  redrawCanvas();
  renderStep5BoxesForm();
  renderStep5NarrationPanel();
  scheduleStep5Autosave();
};

function updateMaskBoxFromManualMask(idx) {
  const maskBox = state.canvasState.boxes[idx];
  if (!maskBox) return;
  const manualMask = ensureManualMask(maskBox, idx);
  const bounds = maskPixelBounds(maskBox);
  if (!bounds) {
    manualMask.bounds = null;
    return;
  }
  const x1 = bounds.x;
  const y1 = bounds.y;
  const x2 = bounds.x + bounds.w;
  const y2 = bounds.y + bounds.h;
  if (x2 - x1 < 4 || y2 - y1 < 4) return;
  maskBox.box = [x1, y1, x2, y2];
  manualMask.bounds = {
    x: Math.round(x1),
    y: Math.round(y1),
    w: Math.round(x2 - x1),
    h: Math.round(y2 - y1)
  };
}

function getCanvasCoords(event, canvas) {
  const { width, height } = maskCanvasGeometry();
  // Fullscreen is already the enlarged editing surface. Keep it as a literal
  // 1:1 canvas: no focal transform, no inverse transform, and therefore no
  // possibility of a left/right centre drift.
  if (state.canvasState.maskFullscreen) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(width, (event.clientX - rect.left) * width / Math.max(1, rect.width))),
      y: Math.max(0, Math.min(height, (event.clientY - rect.top) * height / Math.max(1, rect.height))),
    };
  }
  const stage = document.getElementById('step5-zoom-stage');
  const wrapper = document.getElementById('canvas-container');
  // getBoundingClientRect() describes the already transformed stage.  Reusing
  // that rectangle for input mapping works at 100%, but it makes the two sides
  // drift toward the centre after a focal-point zoom.  Map through the stage's
  // untransformed layout box and explicitly invert the scale instead.
  if (stage && wrapper && canvas && stage.contains(canvas)) {
    const stageWidth = Math.max(1, stage.offsetWidth);
    const stageHeight = Math.max(1, stage.offsetHeight);
    const canvasWidth = Math.max(1, canvas.offsetWidth);
    const canvasHeight = Math.max(1, canvas.offsetHeight);
    const wrapperRect = wrapper.getBoundingClientRect();
    const zoom = Math.max(1, Math.min(4, Number(state.canvasState.maskZoom || 1)));
    const originX = stageWidth * Math.max(0, Math.min(100, Number(state.canvasState.maskZoomOriginX || 50))) / 100;
    const originY = stageHeight * Math.max(0, Math.min(100, Number(state.canvasState.maskZoomOriginY || 50))) / 100;
    const stageLeft = wrapperRect.left + wrapper.clientLeft + stage.offsetLeft;
    const stageTop = wrapperRect.top + wrapper.clientTop + stage.offsetTop;
    const localStageX = (event.clientX - stageLeft - originX) / zoom + originX;
    const localStageY = (event.clientY - stageTop - originY) / zoom + originY;
    const localCanvasX = localStageX - canvas.offsetLeft;
    const localCanvasY = localStageY - canvas.offsetTop;
    return {
      x: Math.max(0, Math.min(width, localCanvasX * width / canvasWidth)),
      y: Math.max(0, Math.min(height, localCanvasY * height / canvasHeight)),
    };
  }
  const rect = canvas.getBoundingClientRect();
  return window.PPTFlow?.mapClientPointToCanvas
    ? window.PPTFlow.mapClientPointToCanvas(event.clientX, event.clientY, rect, width, height)
    : {
        x: Math.max(0, Math.min(width, (event.clientX - rect.left) * width / Math.max(1, rect.width))),
        y: Math.max(0, Math.min(height, (event.clientY - rect.top) * height / Math.max(1, rect.height))),
      };
}

// The image may be letterboxed by object-fit: contain. The editable Canvas
// must occupy that exact visible project rectangle, never the larger wrapper.
function syncMaskCanvasViewport(canvas = document.getElementById('step5-canvas')) {
  const stage = document.getElementById('step5-zoom-stage');
  const image = document.getElementById('step5-bg-img');
  if (!canvas || !stage || !image) return;
  const stageWidth = Math.max(1, stage.offsetWidth);
  const stageHeight = Math.max(1, stage.offsetHeight);
  const imageRatio = image.naturalWidth > 0 && image.naturalHeight > 0
    ? image.naturalWidth / image.naturalHeight
    : maskCanvasGeometry().width / maskCanvasGeometry().height;
  const stageRatio = stageWidth / stageHeight;
  let width = stageWidth;
  let height = stageHeight;
  let left = 0;
  let top = 0;
  if (stageRatio > imageRatio) {
    width = stageHeight * imageRatio;
    left = (stageWidth - width) / 2;
  } else if (stageRatio < imageRatio) {
    height = stageWidth / imageRatio;
    top = (stageHeight - height) / 2;
  }
  const px = value => `${Math.round(value * 1000) / 1000}px`;
  canvas.style.left = px(left);
  canvas.style.top = px(top);
  canvas.style.width = px(width);
  canvas.style.height = px(height);
}

function hideMaskToolCursor() {
  const cursor = document.getElementById('step5-tool-cursor');
  if (cursor) cursor.classList.remove('visible');
}

function refreshMaskToolCursor() {
  const cursor = document.getElementById('step5-tool-cursor');
  const canvas = document.getElementById('step5-canvas');
  const wrapper = document.getElementById('canvas-container');
  if (!cursor || !canvas || !wrapper || !state.canvasState.paintMode) {
    hideMaskToolCursor();
    return;
  }
  const clientX = Number(cursor.dataset.clientX);
  const clientY = Number(cursor.dataset.clientY);
  if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) return;
  const canvasRect = canvas.getBoundingClientRect();
  const wrapperRect = wrapper.getBoundingClientRect();
  const toolSize = state.canvasState.eraserMode ? state.canvasState.eraserSize : state.canvasState.brushSize;
  const { width, height } = maskCanvasGeometry();
  const displayScale = Math.min(canvasRect.width / width, canvasRect.height / height);
  const displaySize = Math.max(8, toolSize * displayScale);
  cursor.style.width = `${displaySize}px`;
  cursor.style.height = `${displaySize}px`;
  cursor.style.left = `${clientX - wrapperRect.left}px`;
  cursor.style.top = `${clientY - wrapperRect.top}px`;
  cursor.classList.add('visible');
}

function updateMaskToolCursor(event) {
  const cursor = document.getElementById('step5-tool-cursor');
  if (!cursor) return;
  cursor.dataset.clientX = String(event.clientX);
  cursor.dataset.clientY = String(event.clientY);
  refreshMaskToolCursor();
}

function beginMaskStroke(event, canvas) {
  if (!state.canvasState.paintMode || state.canvasState.paintingBoxIndex < 0) return;
  if (event.button !== undefined && event.button !== 0) return;
  event.preventDefault();
  updateMaskToolCursor(event);
  const idx = state.canvasState.paintingBoxIndex;
  const box = state.canvasState.boxes[idx];
  if (!box) return;
  const point = getCanvasCoords(event, canvas);
  const stroke = {
    color: getBoxColor(box, idx),
    size: state.canvasState.eraserMode ? state.canvasState.eraserSize : state.canvasState.brushSize,
    mode: state.canvasState.eraserMode ? 'erase' : 'paint',
    eraser: !!state.canvasState.eraserMode,
    points: [{ x: Math.round(point.x), y: Math.round(point.y) }]
  };
  ensureManualMask(box, idx).strokes.push(stroke);
  state.canvasState.isPainting = true;
  state.canvasState.currentStroke = stroke;
  canvas.setPointerCapture?.(event.pointerId);
  scheduleLiveMaskRedraw();
}

let pendingMaskRedrawFrame = 0;

function scheduleLiveMaskRedraw() {
  if (pendingMaskRedrawFrame) return;
  pendingMaskRedrawFrame = requestAnimationFrame(() => {
    pendingMaskRedrawFrame = 0;
    redrawCanvas({ liveStroke: true, updateDiagnostics: false });
  });
}

function continueMaskStroke(event, canvas) {
  updateMaskToolCursor(event);
  if (!state.canvasState.isPainting || !state.canvasState.currentStroke) return;
  event.preventDefault();
  const points = state.canvasState.currentStroke.points;
  const samples = typeof event.getCoalescedEvents === 'function'
    ? event.getCoalescedEvents()
    : [event];
  let changed = false;
  samples.forEach(sample => {
    const point = getCanvasCoords(sample, canvas);
    const last = points[points.length - 1];
    if (!last || Math.hypot(point.x - last.x, point.y - last.y) >= 2) {
      points.push({ x: Math.round(point.x), y: Math.round(point.y) });
      changed = true;
    }
  });
  if (changed) scheduleLiveMaskRedraw();
}

function finishMaskStroke(event, canvas) {
  if (!state.canvasState.isPainting) return;
  state.canvasState.isPainting = false;
  state.canvasState.currentStroke = null;
  if (pendingMaskRedrawFrame) {
    cancelAnimationFrame(pendingMaskRedrawFrame);
    pendingMaskRedrawFrame = 0;
  }
  invalidateStep5ExactPreview();
  if (canvas.hasPointerCapture?.(event.pointerId)) canvas.releasePointerCapture?.(event.pointerId);
  updateMaskBoxFromManualMask(state.canvasState.paintingBoxIndex);
  redrawCanvas();
  renderStep5BoxesForm();
  scheduleStep5Autosave();
  updateMaskToolCursor(event);
}

// AI provides the base mask; pointer tools add reversible manual corrections.
function initCanvasEvents() {
  const canvas = document.getElementById('step5-canvas');
  const wrapper = document.getElementById('canvas-container');

  const newCanvas = canvas.cloneNode(true);
  canvas.parentNode.replaceChild(newCanvas, canvas);
  newCanvas.addEventListener('pointerdown', (event) => beginMaskStroke(event, newCanvas));
  newCanvas.addEventListener('pointermove', (event) => continueMaskStroke(event, newCanvas));
  newCanvas.addEventListener('pointerup', (event) => finishMaskStroke(event, newCanvas));
  newCanvas.addEventListener('pointercancel', (event) => finishMaskStroke(event, newCanvas));
  newCanvas.addEventListener('pointerenter', updateMaskToolCursor);
  newCanvas.addEventListener('pointerleave', () => {
    if (!state.canvasState.isPainting) hideMaskToolCursor();
  });
  newCanvas.addEventListener('wheel', (e) => handleMaskCanvasWheel(e, newCanvas), { passive: false });
  if (wrapper) {
    wrapper.onwheel = (e) => handleMaskCanvasWheel(e, newCanvas);
  }
  if (!window.__step5CanvasViewportResizeBound) {
    window.__step5CanvasViewportResizeBound = true;
    window.addEventListener('resize', () => {
      const activeCanvas = document.getElementById('step5-canvas');
      syncMaskCanvasViewport(activeCanvas);
      refreshMaskToolCursor();
    });
  }
  syncMaskCanvasViewport(newCanvas);
  applyMaskCanvasZoom(newCanvas);
}

function applyMaskCanvasZoom(canvas = document.getElementById('step5-canvas')) {
  const bg = document.getElementById('step5-bg-img');
  const stage = document.getElementById('step5-zoom-stage');
  if (!canvas || !bg || !stage) return;
  const fullscreen = !!state.canvasState.maskFullscreen;
  const zoom = fullscreen ? 1 : Math.max(1, Math.min(4, Number(state.canvasState.maskZoom || 1)));
  state.canvasState.maskZoom = zoom;
  const originX = Math.max(0, Math.min(100, Number(state.canvasState.maskZoomOriginX || 50)));
  const originY = Math.max(0, Math.min(100, Number(state.canvasState.maskZoomOriginY || 50)));
  const origin = `${originX}% ${originY}%`;
  // Keep the source image and drawing surface in one transformed layer. Scaling
  // these siblings independently eventually produces different visual and input
  // coordinate spaces after changing focal points or entering full-screen mode.
  syncMaskCanvasViewport(canvas);
  stage.style.transform = zoom === 1 ? 'none' : `scale(${zoom})`;
  stage.style.transformOrigin = origin;
  [bg, canvas].forEach(el => {
    el.style.transform = '';
    el.style.transformOrigin = '';
  });
  const indicator = document.getElementById('step5-zoom-indicator');
  if (indicator) indicator.innerText = `${Math.round(zoom * 100)}%`;
}

function handleMaskCanvasWheel(e, canvas) {
  if (!e.ctrlKey) return;
  e.preventDefault();
  e.stopPropagation();
  // The fullscreen layout itself is the magnifier. Disable nested Ctrl+wheel
  // transforms there so display and drawing never enter different spaces.
  if (state.canvasState.maskFullscreen) return;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  // Derive the focal point in the stable project drawing space rather than
  // in a previously transformed DOM rectangle. This keeps consecutive zooms
  // anchored to the cursor and prevents the annotation layer from drifting.
  const point = getCanvasCoords(e, canvas);
  const { width, height } = maskCanvasGeometry();
  state.canvasState.maskZoomOriginX = (point.x / width) * 100;
  state.canvasState.maskZoomOriginY = (point.y / height) * 100;
  const current = Number(state.canvasState.maskZoom || 1);
  const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
  state.canvasState.maskZoom = Math.max(1, Math.min(4, current * factor));
  applyMaskCanvasZoom(canvas);
}

function handleGlobalMaskWheel(e) {
  if (state.currentStep !== 5 || !e.ctrlKey) return;
  const wrapper = document.getElementById('canvas-container');
  const canvas = document.getElementById('step5-canvas');
  if (!wrapper || !canvas) return;
  const rect = wrapper.getBoundingClientRect();
  if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) {
    return;
  }
  handleMaskCanvasWheel(e, canvas);
}

function createStep5OffscreenCanvas() {
  const canvas = document.createElement('canvas');
  const { width, height } = maskCanvasGeometry();
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

const maskDisplayLayerCache = new WeakMap();

function maskDisplaySignature(item) {
  const runs = item.manual_mask?.rle?.runs || [];
  const firstRun = runs[0] || [];
  const lastRun = runs[runs.length - 1] || [];
  const strokes = item.manual_mask?.strokes || [];
  const strokeSignature = strokes.map(stroke => {
    const points = stroke?.points || [];
    const last = points[points.length - 1] || {};
    return `${stroke?.mode || ''}:${stroke?.eraser ? 1 : 0}:${stroke?.size || 0}:${points.length}:${last.x || 0}:${last.y || 0}`;
  }).join('|');
  return `${runs.length}:${firstRun.join(',')}:${lastRun.join(',')}:${strokeSignature}`;
}

function buildMaskDisplayLayer(item, idx, options = {}) {
  const isSelected = idx === state.canvasState.selectedBoxIndex;
  const color = getBoxColor(item, idx);
  const liveStroke = options.liveStroke === true && isSelected;
  const signature = `${maskDisplaySignature(item)}:${color}:${isSelected ? 1 : 0}:${liveStroke ? 1 : 0}`;
  const cached = maskDisplayLayerCache.get(item);
  if (cached?.signature === signature) return cached.layer;

  const maskLayer = rasterizeManualMask(item);
  const displayLayer = createStep5OffscreenCanvas();
  const displayCtx = displayLayer.getContext('2d');
  displayCtx.fillStyle = hexToRgba(color, isSelected ? 0.68 : 0.55);
  displayCtx.fillRect(0, 0, displayLayer.width, displayLayer.height);
  displayCtx.globalCompositeOperation = 'destination-in';
  displayCtx.drawImage(maskLayer, 0, 0);
  displayCtx.globalCompositeOperation = 'source-over';

  maskDisplayLayerCache.set(item, { signature, layer: displayLayer });
  return displayLayer;
}

function rasterizeManualMask(item) {
  const maskLayer = createStep5OffscreenCanvas();
  const maskCtx = maskLayer.getContext('2d');
  const exactRuns = item.manual_mask?.rle?.runs || [];
  if (exactRuns.length) {
    maskCtx.fillStyle = 'rgba(0,0,0,1)';
    exactRuns.forEach(run => {
      const [y, x1, x2] = run.map(Number);
      if (Number.isFinite(y) && Number.isFinite(x1) && Number.isFinite(x2) && x2 > x1) {
        maskCtx.fillRect(x1, y, x2 - x1, 1);
      }
    });
  }
  const strokes = item.manual_mask?.strokes || [];
  maskCtx.lineCap = 'round';
  maskCtx.lineJoin = 'round';

  strokes.forEach(stroke => {
    const points = stroke.points || [];
    if (!points.length) return;
    const erase = isEraseStroke(stroke);
    const width = Number(stroke.size || (erase ? state.canvasState.eraserSize : state.canvasState.brushSize));
    const radius = Math.max(1, width / 2);

    maskCtx.save();
    maskCtx.globalCompositeOperation = erase ? 'destination-out' : 'source-over';
    maskCtx.strokeStyle = 'rgba(0,0,0,1)';
    maskCtx.fillStyle = 'rgba(0,0,0,1)';
    maskCtx.lineWidth = width;
    maskCtx.beginPath();
    maskCtx.moveTo(points[0].x, points[0].y);
    points.slice(1).forEach(point => maskCtx.lineTo(point.x, point.y));
    if (points.length === 1) {
      const point = points[0];
      maskCtx.arc(point.x, point.y, radius, 0, Math.PI * 2);
      maskCtx.fill();
      maskCtx.restore();
      return;
    }
    maskCtx.stroke();
    points.forEach(point => {
      maskCtx.beginPath();
      maskCtx.arc(point.x, point.y, radius, 0, Math.PI * 2);
      maskCtx.fill();
    });
    maskCtx.restore();
  });
  return maskLayer;
}

function maskPixelBounds(item) {
  const maskLayer = rasterizeManualMask(item);
  const ctx = maskLayer.getContext('2d', { willReadFrequently: true });
  const { data, width, height } = ctx.getImageData(0, 0, maskLayer.width, maskLayer.height);
  let minX = width;
  let minY = height;
  let maxX = -1;
  let maxY = -1;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if (data[(y * width + x) * 4 + 3] === 0) continue;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    }
  }
  if (maxX < minX || maxY < minY) return null;
  const { width: canvasWidth, height: canvasHeight } = maskCanvasGeometry();
  return {
    x: Math.max(0, minX),
    y: Math.max(0, minY),
    w: Math.min(canvasWidth, maxX + 1) - Math.max(0, minX),
    h: Math.min(canvasHeight, maxY + 1) - Math.max(0, minY),
  };
}

function maskBoxBounds(item) {
  const { width, height } = maskCanvasGeometry();
  const values = Array.isArray(item?.box) ? item.box.map(Number) : [0, 0, width, height];
  const x1 = Math.max(0, Math.min(values[0] || 0, values[2] || 0));
  const y1 = Math.max(0, Math.min(values[1] || 0, values[3] || 0));
  const x2 = Math.min(width, Math.max(values[0] || 0, values[2] || 0));
  const y2 = Math.min(height, Math.max(values[1] || 0, values[3] || 0));
  return { x: x1, y: y1, w: Math.max(1, x2 - x1), h: Math.max(1, y2 - y1) };
}

function buildMaskAnimationLayers(item) {
  const maskLayer = rasterizeManualMask(item);
  const contentLayer = createStep5OffscreenCanvas();
  const contentCtx = contentLayer.getContext('2d');
  contentCtx.drawImage(step5SourceCanvas, 0, 0);
  contentCtx.globalCompositeOperation = 'destination-in';
  contentCtx.drawImage(maskLayer, 0, 0);

  const coverLayer = createStep5OffscreenCanvas();
  const coverCtx = coverLayer.getContext('2d');
  coverCtx.fillStyle = step3VideoBackground || '#FEFDF9';
  coverCtx.fillRect(0, 0, coverLayer.width, coverLayer.height);
  coverCtx.globalCompositeOperation = 'destination-in';
  coverCtx.drawImage(maskLayer, 0, 0);
  return { contentLayer, coverLayer };
}

function easeOutBack(progress) {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  const value = Math.max(0, Math.min(1, progress)) - 1;
  return 1 + c3 * value * value * value + c1 * value * value;
}

function drawMaskAnimationPreview(ctx, preview) {
  const { item, reveal, progress, contentLayer, coverLayer } = preview;
  const box = maskBoxBounds(item);
  const action = reveal.type;
  const eased = Math.max(0, Math.min(1, progress));

  ctx.drawImage(coverLayer, 0, 0);
  ctx.save();

  if (action === 'wipe_left_to_right') {
    ctx.beginPath();
    ctx.rect(box.x, box.y, box.w * eased, box.h);
    ctx.clip();
    ctx.drawImage(contentLayer, 0, 0);
  } else if (action === 'scratch_reveal' || action === 'brush_wipe_left_to_right') {
    const edgeX = box.x + box.w * eased;
    const roughness = action === 'scratch_reveal' ? 24 : 12;
    ctx.beginPath();
    ctx.moveTo(box.x, box.y);
    for (let y = box.y; y <= box.y + box.h; y += 18) {
      const wave = Math.sin(y * 0.075) * roughness + Math.sin(y * 0.19) * roughness * 0.35;
      ctx.lineTo(Math.min(box.x + box.w, edgeX + wave), y);
    }
    ctx.lineTo(box.x, box.y + box.h);
    ctx.closePath();
    ctx.clip();
    ctx.drawImage(contentLayer, 0, 0);
  } else if (action === 'crop_fade_up') {
    ctx.globalAlpha = eased;
    ctx.drawImage(contentLayer, 0, 0);
  } else {
    const cx = box.x + box.w / 2;
    const cy = box.y + box.h / 2;
    let scale = 1;
    let translateX = 0;
    let translateY = 0;
    let rotation = 0;
    let alpha = eased;
    if (action === 'crop_slide_in_left') {
      translateX = -(1 - eased) * Math.min(90, box.w * 0.25);
    } else if (action === 'crop_soft_zoom_in') {
      scale = 0.82 + eased * 0.18;
    } else if (action === 'sticker_pop') {
      const springProgress = easeOutBack(eased);
      scale = 0.65 + springProgress * 0.35;
      rotation = Number(reveal.rotation ?? -4) * (1 - eased);
    } else if (action === 'stamp_in') {
      const springProgress = easeOutBack(eased);
      scale = 1.55 - springProgress * 0.55;
      rotation = Number(reveal.rotation ?? 2) * (1 - eased);
    } else if (action === 'paper_drop') {
      translateY = -(1 - easeOutBack(eased)) * 80;
      rotation = Number(reveal.rotation ?? -3) * (1 - eased);
    }
    ctx.globalAlpha = alpha;
    ctx.translate(cx + translateX, cy + translateY);
    ctx.rotate(rotation * Math.PI / 180);
    ctx.scale(scale, scale);
    ctx.translate(-cx, -cy);
    ctx.drawImage(contentLayer, 0, 0);
  }
  ctx.restore();
}

function stopMaskAnimationPreview() {
  const preview = state.canvasState.animationPreview;
  if (preview?.rafId) {
    cancelAnimationFrame(preview.rafId);
    clearTimeout(preview.rafId);
  }
  state.canvasState.animationPreview = null;
}

function readGlobalAnimationSettingsForm() {
  const type = document.getElementById('animation-setting-type').value || 'wipe_left_to_right';
  return normalizeMaskReveal({
    ...revealPreset(type),
    duration: Math.max(
      0.2,
      Math.min(3, Number(document.getElementById('animation-setting-duration').value) || DEFAULT_REVEAL_DURATION_SEC),
    ),
  });
}

function populateGlobalAnimationSettingsForm(reveal) {
  const normalized = normalizeMaskReveal(reveal);
  document.getElementById('animation-setting-type').value = normalized.type;
  document.getElementById('animation-setting-duration').value = String(normalized.duration);
  document.getElementById('animation-setting-duration-value').textContent = Number(normalized.duration).toFixed(2);
}

function stopAnimationModalPreview() {
  if (state.canvasState.animationModalPreviewRaf) {
    cancelAnimationFrame(state.canvasState.animationModalPreviewRaf);
    clearTimeout(state.canvasState.animationModalPreviewRaf);
  }
  state.canvasState.animationModalPreviewRaf = null;
}

function drawAnimationModalBase() {
  const canvas = document.getElementById('animation-preview-canvas');
  const empty = document.getElementById('animation-preview-empty');
  if (!canvas) return false;
  syncMaskCanvasDimensions(document.getElementById('step5-canvas'));
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = step3VideoBackground || '#FEFDF9';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (!step5SourceCanvas) {
    if (empty) empty.style.display = 'flex';
    return false;
  }
  ctx.drawImage(step5SourceCanvas, 0, 0);
  const hasMasks = state.canvasState.boxes.some(hasPaintStroke);
  if (empty) empty.style.display = hasMasks ? 'none' : 'flex';
  return hasMasks;
}

function openAnimationSettingsModal() {
  if (!manifestData?.slides?.length) return;
  const select = document.getElementById('animation-setting-type');
  select.innerHTML = MASK_ANIMATION_PRESETS.map(preset =>
    `<option value="${preset.value}">${preset.label}</option>`
  ).join('');
  const reveal = manifestData.animation_defaults?.reveal
    || state.canvasState.boxes.find(Boolean)?.reveal
    || revealPreset('crop_fade_up');
  populateGlobalAnimationSettingsForm(reveal);
  document.getElementById('modal-animation-settings').style.display = 'flex';
  requestAnimationFrame(() => drawAnimationModalBase());
}

function closeAnimationSettingsModal() {
  stopAnimationModalPreview();
  document.getElementById('modal-animation-settings').style.display = 'none';
}

function previewGlobalAnimationSettings() {
  const canvas = document.getElementById('animation-preview-canvas');
  if (!canvas || !drawAnimationModalBase()) {
    showToast('请先在当前页为至少一个语块涂抹 Mask。');
    return;
  }
  stopAnimationModalPreview();
  const ctx = canvas.getContext('2d');
  const reveal = readGlobalAnimationSettingsForm();
  const items = state.canvasState.boxes.filter(hasPaintStroke);
  const previews = items.map(item => ({
    item,
    reveal,
    ...buildMaskAnimationLayers(item),
  }));
  const startedAt = performance.now();
  const staggerMs = Math.min(280, Math.max(110, reveal.duration * 240));
  const durationMs = Math.max(400, reveal.duration * 1000);
  const totalMs = durationMs + staggerMs * Math.max(0, previews.length - 1);
  const tick = now => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = step3VideoBackground || '#FEFDF9';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(step5SourceCanvas, 0, 0);
    previews.forEach((preview, index) => {
      const localElapsed = now - startedAt - index * staggerMs;
      preview.progress = Math.max(0, Math.min(1, localElapsed / durationMs));
      drawMaskAnimationPreview(ctx, preview);
    });
    if (now - startedAt < totalMs) {
      state.canvasState.animationModalPreviewRaf = requestAnimationFrame(tick);
    } else {
      state.canvasState.animationModalPreviewRaf = setTimeout(() => drawAnimationModalBase(), 650);
    }
  };
  state.canvasState.animationModalPreviewRaf = requestAnimationFrame(tick);
}

function resetGlobalAnimationSettings() {
  populateGlobalAnimationSettingsForm(revealPreset('crop_fade_up'));
  previewGlobalAnimationSettings();
}

async function saveGlobalAnimationSettings() {
  const reveal = applyGlobalMaskReveal(readGlobalAnimationSettingsForm(), { save: false });
  saveStep5CurrentState();
  await saveStep5Draft();
  closeAnimationSettingsModal();
  showToast(`已将“${revealPreset(reveal.type).label}”应用到全部 Slide 的全部语块。`);
}

function rebuildStep5SourceCache(image) {
  const source = createStep5OffscreenCanvas();
  const sourceCtx = source.getContext('2d');
  sourceCtx.drawImage(image, 0, 0, source.width, source.height);
  step5SourceCanvas = source;

}

function invalidateStep5ExactPreview() {
  state.canvasState.exactPreviewImage = null;
  state.canvasState.exactPreviewSlideId = '';
  if (state.canvasState.maskPreviewMode === 'final') {
    state.canvasState.maskPreviewMode = 'mask';
  }
  window.dispatchEvent(new CustomEvent('step5-mask-preview-invalidated'));
}

function setStep5MaskPreviewMode(mode, previewUrl = '', slideId = '') {
  const normalized = ['source', 'mask', 'final'].includes(mode) ? mode : 'mask';
  if (normalized !== 'final') {
    state.canvasState.maskPreviewMode = normalized;
    redrawCanvas();
    window.dispatchEvent(new CustomEvent('step5-mask-preview-mode', { detail: { mode: normalized } }));
    return Promise.resolve(true);
  }
  if (!previewUrl) return Promise.resolve(false);
  return new Promise(resolve => {
    const image = new Image();
    image.onload = () => {
      state.canvasState.exactPreviewImage = image;
      state.canvasState.exactPreviewSlideId = String(slideId || '');
      state.canvasState.maskPreviewMode = 'final';
      redrawCanvas();
      window.dispatchEvent(new CustomEvent('step5-mask-preview-mode', { detail: { mode: 'final' } }));
      resolve(true);
    };
    image.onerror = () => {
      showToast('精确 Mask 预览图片加载失败，请重试。', 5000);
      resolve(false);
    };
    image.src = previewUrl;
  });
}

function drawManualMaskStrokes(ctx, item, idx, options = {}) {
  const strokes = item.manual_mask?.strokes || [];
  const exactRuns = item.manual_mask?.rle?.runs || [];
  if (!strokes.length && !exactRuns.length) return;
  ctx.drawImage(buildMaskDisplayLayer(item, idx, options), 0, 0);
}

function redrawCanvas(options = {}) {
  const canvas = document.getElementById('step5-canvas');
  syncMaskCanvasDimensions(canvas);
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = step3VideoBackground;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  canvas.classList.toggle('painting', state.canvasState.paintMode && !state.canvasState.eraserMode);
  canvas.classList.toggle('erasing', state.canvasState.paintMode && state.canvasState.eraserMode);

  if (!step5SourceCanvas) {
    return;
  }

  const currentSlideId = String(getCurrentManifestSlide()?.slide_id || '');
  if (
    state.canvasState.maskPreviewMode === 'final'
    && state.canvasState.exactPreviewImage
    && state.canvasState.exactPreviewSlideId === currentSlideId
  ) {
    ctx.drawImage(state.canvasState.exactPreviewImage, 0, 0, canvas.width, canvas.height);
    return;
  }
  ctx.drawImage(step5SourceCanvas, 0, 0);
  if (state.canvasState.maskPreviewMode === 'source') {
    return;
  }
  const preview = options.animationPreview || state.canvasState.animationPreview;
  if (preview) {
    drawMaskAnimationPreview(ctx, preview);
  } else {
    state.canvasState.boxes.forEach((item, idx) => {
      drawManualMaskStrokes(ctx, item, idx, options);
    });
  }

}

function saveStep5CurrentState() {
  const slide = manifestData.slides[state.activeSlideIndex];
  syncMaskBoxesToSlide(slide, state.canvasState.boxes);
}

function boxHasAiPaint(box) {
  const manualMask = box?.manual_mask;
  const strokes = Array.isArray(manualMask?.strokes) ? manualMask.strokes : [];
  const hasExactMask = Array.isArray(manualMask?.rle?.runs) && manualMask.rle.runs.length > 0;
  if (!hasExactMask && !strokes.some(stroke => stroke && !stroke.eraser && stroke.mode !== 'erase' && Array.isArray(stroke.points) && stroke.points.length)) return false;
  return String(manualMask?.source || '').startsWith('ai_auto_mask')
    || ['ai_matched_needs_review', 'ai_review_required'].includes(String(box?.review_status || ''))
    || !!box?.auto_mask
    || !!box?.ai_match;
}

function focusFirstAiMaskResult() {
  if (!manifestData?.slides?.length) return false;
  for (let slideIndex = 0; slideIndex < manifestData.slides.length; slideIndex += 1) {
    const boxes = getSlideMaskBoxes(manifestData.slides[slideIndex]);
    const boxIndex = boxes.findIndex(boxHasAiPaint);
    if (boxIndex < 0) continue;
    state.activeSlideIndex = slideIndex;
    renderStep5Workspace();
    setTimeout(() => {
      state.canvasState.selectedBoxIndex = boxIndex;
      selectStep5MaskBox(boxIndex, false);
      redrawCanvas({ updateDiagnostics: false });
    }, 80);
    return true;
  }
  redrawCanvas({ updateDiagnostics: false });
  return false;
}

function updateStep5DraftStatus(text) {
  const el = document.getElementById('step5-draft-status');
  if (el) el.innerText = text || '';
}

function scheduleStep5Autosave() {
  if (!manifestData?.slides?.length || state.canvasState.semanticLoading) return;
  updateStep5DraftStatus('自动保存中...');
  clearTimeout(state.step5AutoSaveTimer);
  state.step5AutoSaveTimer = setTimeout(() => {
    saveStep5Draft();
  }, 700);
}

async function saveStep5Draft() {
  const projectId = state.currentProject?.id;
  if (!projectId || manifestProjectId !== projectId || !manifestData?.slides?.length) {
    return { success: false, reason: 'stale_or_empty_step5_manifest' };
  }
  saveStep5CurrentState();
  if (state.step5AutoSavePromise) {
    try {
      await state.step5AutoSavePromise;
    } catch (error) {
      // The save below retries with the latest manifest state.
    }
    saveStep5CurrentState();
  }
  const payload = JSON.parse(JSON.stringify(manifestData));
  state.step5AutoSaveInFlight = true;
  const savePromise = API.put(`/api/projects/${projectId}/steps/5/draft`, payload);
  state.step5AutoSavePromise = savePromise;
  try {
    const res = await savePromise;
    if (res.success) {
      updateStep5DraftStatus('已自动保存');
      setTimeout(() => updateStep5DraftStatus(''), 1200);
    }
    return res;
  } finally {
    state.step5AutoSaveInFlight = false;
    if (state.step5AutoSavePromise === savePromise) {
      state.step5AutoSavePromise = null;
    }
  }
}

async function flushStep5Draft() {
  if (state.step5AutoSaveTimer) {
    clearTimeout(state.step5AutoSaveTimer);
    state.step5AutoSaveTimer = null;
  }
  if (state.step5AutoSavePromise) {
    try {
      await state.step5AutoSavePromise;
    } catch (error) {
      // Save the newest editor state below.
    }
  }
  if (!manifestData?.slides?.length) return { success: false, reason: 'no_step5_manifest' };
  saveStep5CurrentState();
  return saveStep5Draft();
}

async function runStep5SemanticBlocks() {
  if (state.canvasState.semanticLoading) return;
  if (!manifestData?.slides?.length) return;
  saveStep5CurrentState();
  const currentSlide = getCurrentManifestSlide();
  if (!currentSlide?.slide_id) return;
  state.canvasState.semanticLoading = true;
  updateStep5SemanticButton();
  renderStep5Workspace();
  showToast(`🤖 正在为 ${currentSlide.slide_id} 预识别语义块、旁白和画面内容，不会自动绘制 Mask...`);

  try {
    await API.put(`/api/projects/${state.currentProject.id}/steps/5/draft`, manifestData);
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/5/semantic-blocks`, { slide_id: currentSlide.slide_id });
    if (res.success) {
      showToast(`✅ ${res.message || '已用分镜合约生成语义分块'}`);
      await loadStep5Data();
    }
  } finally {
    state.canvasState.semanticLoading = false;
    updateStep5SemanticButton();
    renderStep5Workspace();
  }
}

async function saveStep5Masks() {
  if (state.canvasState.confirmingMasks) {
    return false;
  }
  if (state.canvasState.semanticLoading) {
    showToast('AI 标注相关任务仍在处理中，请稍候再确认。', 3000);
    updateStep5ConfirmButton('AI 标注相关任务仍在处理中，请稍候。');
    return false;
  }
  state.canvasState.confirmingMasks = true;
  updateStep5ConfirmButton('处理中：正在保存当前标注草稿...');
  updateStep5SemanticButton();

  const previousStatuses = (manifestData?.slides || []).map(slide => slide.status);
  let failureMessage = '';

  if (state.step5AutoSaveTimer) {
    clearTimeout(state.step5AutoSaveTimer);
    state.step5AutoSaveTimer = null;
  }
  try {
    await saveStep5Draft();
    saveStep5CurrentState();

    // 点击下一步时统一确认全部 Slide，并一次性构建所有切层。
    manifestData.slides.forEach(slide => {
      slide.status = "completed";
    });

    updateStep5ConfirmButton('处理中：正在确认全部标注并构建切层...');
    showToast('正在确认全部标注并构建切层...');
    const res = await API.put(`/api/projects/${state.currentProject.id}/steps/5/result`, manifestData);
    if (res.success) {
      showToast('全部标注已确认，切层构建完成');
      renderStep5Workspace(); // 重新绘制切换栏以更新已标注绿色状态
      refreshCurrentProjectStatus(5).catch(() => {});
      return true;
    }
  } catch (e) {
    manifestData.slides.forEach((slide, index) => {
      slide.status = previousStatuses[index] || 'pending';
    });
    failureMessage = `确认失败：${e.message || '请检查 Mask 数据后重试'}`;
    showToast(failureMessage, 7000);
    renderStep5Workspace();
  } finally {
    state.canvasState.confirmingMasks = false;
    updateStep5SemanticButton();
    updateStep5ConfirmButton(failureMessage);
  }
  return false;
}

window.saveStep5Draft = saveStep5Draft;
window.saveStep5CurrentState = saveStep5CurrentState;
window.focusFirstAiMaskResult = focusFirstAiMaskResult;
window.setStep5MaskPreviewMode = setStep5MaskPreviewMode;
window.PPTStudio = Object.assign(window.PPTStudio || {}, {
  getCurrentProject: () => state.currentProject,
  flushStep5Draft,
});

