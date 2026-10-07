// 勾画标注编辑器(可见步骤 6，内部 Step 10):画布框选、属性编辑、撤销/重做、
// 删除/锁定/禁用。状态与渲染入口在 annotations_workspace.js;
// 服务端操作协议见 annotation_routes(PATCH operations)。

const ANNOTATIONS_ED = {
  drawMode: null,
  repair: null,
  regionStart: null,
  regionGhost: null,
  freehandPoints: [],
  freehandGhost: null,
  freehandStrokes: [],
  editorTimer: null,
  calibrationCleanup: null,
  previewFrame: null,
};

// ------------------------------------------------------------ 画布覆盖层

function fallbackStrokeFor(item) {
  // 服务端笔迹缺位时的兜底(仅编辑可见性;导出仍以服务端为准)
  const manualPath = item.target?.path_points;
  if (Array.isArray(manualPath) && manualPath.length >= 2) {
    return [{ kind: 'polyline', points: manualPath }];
  }
  const polygons = item.target?.polygons || [];
  const bounds = AnnotationsCore.polygonBounds(polygons);
  if (!bounds) return [];
  const pad = Number(item.style?.padding || 8);
  const stroke = AnnotationsCore.buildRegionTarget(polygons);
  void stroke;
  if (item.style?.type === 'highlighter') {
    return [{ kind: 'rect', x: bounds.left - pad / 2, y: bounds.top - pad / 2, width: bounds.width + pad, height: bounds.height + pad }];
  }
  const right = bounds.left + bounds.width;
  const bottom = bounds.top + bounds.height;
  if (item.style?.type === 'underline') {
    const y = bottom + pad + Number(item.style?.width || 5) / 2;
    return [{ kind: 'polyline', points: [[bounds.left - pad, y], [(bounds.left + right) / 2, y + 5], [right + pad, y]] }];
  }
  const cx = bounds.left + bounds.width / 2;
  const cy = bounds.top + bounds.height / 2;
  const points = [];
  for (let i = 0; i < 48; i += 1) {
    const angle = (i / 48) * Math.PI * 2;
    points.push([cx + Math.cos(angle) * (bounds.width / 2 + pad), cy + Math.sin(angle) * (bounds.height / 2 + pad)]);
  }
  points.push(points[0]);
  return [{ kind: 'polyline', points }];
}

// 编辑态静态渲染采样点:落在绘制窗口之后的 hold 区间内,保证笔迹呈现
// "绘制完成"的完整形态(此前采样在 0.5,所有笔迹都只显示一半)。
const ANNOTATION_EDIT_SAMPLE_SEC = 1;
const ANNOTATION_EDIT_EVENT_WINDOW = { draw_end_sec: 1, hold_end_sec: 2, exit_end_sec: 3 };

function annotationEffectiveEvent(item, color) {
  return {
    annotation_id: item.annotation_id,
    start_sec: 0,
    ...ANNOTATION_EDIT_EVENT_WINDOW,
    style: { ...item.style, color },
    strokes: item.strokes && item.strokes.length ? item.strokes : fallbackStrokeFor(item),
  };
}

function annotationShapeMarkup(item, shape, extraAttrs = '') {
  const color = item.style?.color || '#F46A38';
  const opacity = Math.max(0, Math.min(1, Number(item.style?.opacity ?? 0.85)));
  const disabled = item.status?.content === 'disabled';
  const owner = ` data-owner="${escHtml(item.annotation_id)}"${disabled ? ' data-disabled="true"' : ''}${extraAttrs}`;
  const effectiveOpacity = disabled ? opacity * 0.3 : opacity;
  if (shape.kind === 'path') {
    return `<path d="${escHtml(shape.d)}" fill="${shape.closed ? escHtml(color) : 'none'}" fill-opacity="${shape.closed ? Math.min(0.12, opacity * 0.14) : 0}" stroke="${escHtml(color)}" stroke-width="2.5" stroke-linejoin="round" opacity="${effectiveOpacity}"${owner} />`;
  }
  if (shape.kind === 'polyline') {
    return `<path d="${escHtml(shape.d)}" fill="none" stroke="${escHtml(color)}" stroke-width="${shape.strokeWidth}" stroke-linecap="round" stroke-linejoin="round" opacity="${effectiveOpacity}"${owner} />`;
  }
  if (shape.kind === 'rect') {
    return `<rect x="${shape.x}" y="${shape.y}" width="${shape.width}" height="${shape.height}" fill="${escHtml(color)}" opacity="${effectiveOpacity}" stroke="none"${owner} />`;
  }
  return '';
}

function renderAnnotationOverlay() {
  cancelAnnotationPreviewLoop();
  const overlay = document.getElementById('annotation-canvas-overlay');
  const image = document.getElementById('annotation-canvas-image');
  if (!overlay || !image) return;
  const geometry = typeof getProjectCanvasGeometry === 'function'
    ? getProjectCanvasGeometry()
    : { width: 1920, height: 1080 };
  overlay.setAttribute('viewBox', `0 0 ${geometry.width} ${geometry.height}`);
  image.src = `/api/projects/${ANNOTATIONS_WS.projectId}/slides/${encodeURIComponent(ANNOTATIONS_WS.page.slide_id)}/image`;
  const items = ANNOTATIONS_WS.page.items || [];
  const shapes = [];
  items.forEach(item => {
    const polygons = item.target?.polygons || [];
    const bounds = AnnotationsCore.polygonBounds(polygons);
    if (!bounds) return;
    const pad = Number(item.style?.padding || 8);
    if (item.annotation_id === ANNOTATIONS_WS.selectedAnnotationId) {
      shapes.push(`<rect class="annotation-select-frame" x="${bounds.left - pad}" y="${bounds.top - pad}" width="${bounds.width + pad * 2}" height="${bounds.height + pad * 2}" fill="none" stroke="#111827" stroke-width="2" stroke-dasharray="10 6" data-owner="${escHtml(item.annotation_id)}" />`);
    }
    // Use the same full-resolution textured ink as the final animation frame.
    const event = annotationEffectiveEvent(item, item.style?.color || '#F46A38');
    AnnotationsPlayback.renderScene([event], ANNOTATION_EDIT_SAMPLE_SEC, 30).forEach((shape, index) => {
      if (event.strokes[index]?.kind === 'path') {
        const base = `/api/projects/${encodeURIComponent(ANNOTATIONS_WS.projectId)}/annotations/slides/${encodeURIComponent(ANNOTATIONS_WS.page.slide_id)}`;
        const url = `${base}/editor-ink/${encodeURIComponent(item.annotation_id)}/${index}?revision=${ANNOTATIONS_WS.page.revision}`;
        const opacity = Math.max(0, Math.min(1, Number(item.style?.opacity ?? 0.85)))
          * (item.status?.content === 'disabled' ? 0.3 : 1);
        shapes.push(`<image href="${escHtml(url)}" x="0" y="0" width="${geometry.width}" height="${geometry.height}" opacity="${opacity}" pointer-events="none" />`);
        // Full-canvas transparent images must not intercept other annotations.
        shapes.push(`<path d="${escHtml(shape.d)}" fill="transparent" data-owner="${escHtml(item.annotation_id)}" />`);
      } else {
        shapes.push(annotationShapeMarkup(item, shape));
      }
    });
  });
  overlay.innerHTML = shapes.join('');
  overlay.querySelectorAll('[data-owner]').forEach(shape => {
    shape.addEventListener('click', () => selectAnnotationItem(shape.dataset.owner));
  });
}

// ------------------------------------------------------------ 动画预览

// 同步预览复用正式 Remotion 组件、真实音频和服务端构建的时间轴。
function cancelAnnotationPreviewLoop() {
  window.stopAnnotationSyncPreview?.();
  if (ANNOTATIONS_ED.previewFrame) {
    cancelAnimationFrame(ANNOTATIONS_ED.previewFrame);
    ANNOTATIONS_ED.previewFrame = null;
    setAnnotationPreviewButton(false);
  }
}

function stopAnnotationPreview() {
  cancelAnnotationPreviewLoop();
  renderAnnotationOverlay();
}

function setAnnotationPreviewButton(playing) {
  const button = document.getElementById('annotation-btn-preview');
  if (!button) return;
  button.classList.toggle('active', playing);
  button.textContent = playing ? '停止预览' : '预览动画';
}

function previewAnnotationAnimation() {
  finishAnnotationFreehand(true);
  if (ANNOTATIONS_ED.repair) {showToast('请先完成重画，或点击取消重画。'); return;}
  return window.showAnnotationSyncPreview?.();
}

// ------------------------------------------------------------ 手工绘制

function setAnnotationDrawMode(mode) {
  if (ANNOTATIONS_ED.repair && mode !== ANNOTATIONS_ED.drawMode) cancelAnnotationRepair();
  if (mode !== 'freehand' && ANNOTATIONS_ED.freehandStrokes.length) finishAnnotationFreehand();
  ANNOTATIONS_ED.drawMode = mode === 'region' || mode === 'freehand' ? mode : null;
  const frame = document.getElementById('annotation-canvas-frame');
  const regionButton = document.getElementById('annotation-btn-region');
  const freehandButton = document.getElementById('annotation-btn-freehand');
  if (frame) {
    frame.classList.toggle('region-mode', ANNOTATIONS_ED.drawMode === 'region');
    frame.classList.toggle('freehand-mode', ANNOTATIONS_ED.drawMode === 'freehand');
  }
  if (regionButton) regionButton.classList.toggle('active', ANNOTATIONS_ED.drawMode === 'region');
  if (freehandButton) freehandButton.classList.toggle('active', ANNOTATIONS_ED.drawMode === 'freehand');
  const done = document.getElementById('annotation-btn-finish-freehand');
  if (done) done.hidden = ANNOTATIONS_ED.drawMode !== 'freehand';
}

function cancelAnnotationRepair() {
  if (!ANNOTATIONS_ED.repair) return;
  ANNOTATIONS_ED.repair = null;
  ANNOTATIONS_ED.freehandStrokes = [];
  document.querySelectorAll('[data-pending-stroke]').forEach(node => node.remove());
  handleAnnotationDrawPointerCancel();
  setAnnotationDrawMode(null);
}

function beginAnnotationRepair(mode) {
  const item = annotationSelectedItem();
  if (!item || item.status?.content === 'disabled') return;
  if (String(item.annotation_id).startsWith('local_')) {
    showToast('请先保存新标注，再修改它的范围或笔迹。');
    return;
  }
  if (!ANNOTATIONS_ED.repair && ANNOTATIONS_ED.freehandStrokes.length) {
    showToast('请先完成当前绘制，再修改已有标注。');
    return;
  }
  cancelAnnotationRepair();
  finishAnnotationFreehand();
  setAnnotationDrawMode(mode);
  ANNOTATIONS_ED.repair = {projectId: ANNOTATIONS_WS.projectId,
    slideId: ANNOTATIONS_WS.page.slide_id, annotationId: item.annotation_id};
  renderAnnotationItemEditor();
  document.getElementById('annotation-canvas-frame')?.scrollIntoView?.({block: 'center', behavior: 'auto'});
  showToast(mode === 'region' ? '在画面上重新框选，只修改当前标注的范围。' : '重新画出笔迹，点击完成绘制后替换当前标注；可取消。');
}

function commitAnnotationRepair(target) {
  const repair = ANNOTATIONS_ED.repair;
  if (!repair) return false;
  const item = ANNOTATIONS_WS.page.items.find(entry => entry.annotation_id === repair.annotationId);
  if (repair.projectId !== ANNOTATIONS_WS.projectId || repair.slideId !== ANNOTATIONS_WS.page.slide_id || !item) {
    cancelAnnotationRepair();
    setAnnotationDrawMode(null);
    showToast('当前标注已变化，请重新选择后修改。');
    return true;
  }
  pushAnnotationHistory();
  queueAnnotationItemPatch(item.annotation_id, {target: {...target, mask_group_ids: item.target?.mask_group_ids || []}});
  ANNOTATIONS_ED.repair = null;
  setAnnotationDrawMode(null);
  renderAnnotationItemEditor();
  showToast('已修改当前标注，讲稿关联和起笔时间保留。请保存、同步预览并重新确认本页。');
  return true;
}

async function saveAnnotationEdits() {
  const projectId = ANNOTATIONS_WS.projectId, slideId = ANNOTATIONS_WS.page.slide_id;
  finishAnnotationFreehand(true);
  if (ANNOTATIONS_ED.repair) {showToast('请先完成重画，或点击取消重画保留原标注。'); return;}
  await flushAnnotationsSave();
  if (projectId !== ANNOTATIONS_WS.projectId || slideId !== ANNOTATIONS_WS.page.slide_id) return;
  if (ANNOTATIONS_WS.failedOps.length || ANNOTATIONS_WS.conflict || ANNOTATIONS_WS.pendingOps.length) {
    showToast('修改尚未保存，请点击保存状态提示处理失败或冲突。');
    return;
  }
  showToast('修改已保存。请同步预览，核对后确认本页。');
}

function annotationCanvasPoint(event) {
  const image = document.getElementById('annotation-canvas-image');
  if (!image) return null;
  const geometry = getProjectCanvasGeometry();
  return PPTFlow.mapClientPointToCanvas(
    event.clientX, event.clientY, image.getBoundingClientRect(), geometry.width, geometry.height,
  );
}

function limitAnnotationPathPoints(points, limit = 512) {
  if (points.length <= limit) return points;
  const stride = (points.length - 1) / (limit - 1);
  return Array.from({ length: limit }, (_value, index) => points[Math.round(index * stride)]);
}

function handleAnnotationDrawPointerDown(event) {
  if (!ANNOTATIONS_ED.drawMode || event.button !== 0) return;
  event.preventDefault();
  cancelAnnotationPreviewLoop();
  const frame = document.getElementById('annotation-canvas-frame');
  const image = document.getElementById('annotation-canvas-image');
  if (!frame || !image) return;
  const point = annotationCanvasPoint(event);
  if (!point) return;
  if (ANNOTATIONS_ED.drawMode === 'freehand') {
    ANNOTATIONS_ED.freehandPoints = [[Math.round(point.x), Math.round(point.y)]];
    ANNOTATIONS_ED.freehandGhost = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    ANNOTATIONS_ED.freehandGhost.setAttribute('fill', 'none');
    ANNOTATIONS_ED.freehandGhost.setAttribute('stroke', '#f46a38');
    ANNOTATIONS_ED.freehandGhost.setAttribute('stroke-width', '8');
    ANNOTATIONS_ED.freehandGhost.setAttribute('stroke-linecap', 'round');
    ANNOTATIONS_ED.freehandGhost.setAttribute('stroke-linejoin', 'round');
    ANNOTATIONS_ED.freehandGhost.setAttribute('opacity', '0.9');
    document.getElementById('annotation-canvas-overlay')?.append(ANNOTATIONS_ED.freehandGhost);
  } else {
    ANNOTATIONS_ED.regionStart = point;
  }
  frame.setPointerCapture?.(event.pointerId);
  const ghost = document.getElementById('annotation-region-ghost');
  if (ghost && ANNOTATIONS_ED.drawMode === 'region') {
    ghost.style.display = 'block';
    ghost.style.left = '0px';
    ghost.style.top = '0px';
    ghost.style.width = '0px';
    ghost.style.height = '0px';
  }
  ANNOTATIONS_ED.regionGhost = ANNOTATIONS_ED.drawMode === 'region' ? ghost : null;
}

function handleAnnotationDrawPointerMove(event) {
  if (!ANNOTATIONS_ED.drawMode) return;
  const image = document.getElementById('annotation-canvas-image');
  if (!image) return;
  const point = annotationCanvasPoint(event);
  if (!point) return;
  if (ANNOTATIONS_ED.drawMode === 'freehand' && ANNOTATIONS_ED.freehandGhost) {
    const points = ANNOTATIONS_ED.freehandPoints;
    const previous = points[points.length - 1];
    if (!previous || Math.hypot(point.x - previous[0], point.y - previous[1]) >= 4) {
      points.push([Math.round(point.x), Math.round(point.y)]);
      if (points.length > 512) {
        ANNOTATIONS_ED.freehandPoints = limitAnnotationPathPoints(points);
      }
    }
    ANNOTATIONS_ED.freehandGhost.setAttribute('points', ANNOTATIONS_ED.freehandPoints.map(p => p.join(',')).join(' '));
    return;
  }
  const ghost = ANNOTATIONS_ED.regionGhost;
  if (ANNOTATIONS_ED.drawMode !== 'region' || !ANNOTATIONS_ED.regionStart || !ghost) return;
  const geometry = getProjectCanvasGeometry();
  const rect = image.getBoundingClientRect();
  const scaleX = rect.width / geometry.width;
  const scaleY = rect.height / geometry.height;
  const boxLeft = Math.min(ANNOTATIONS_ED.regionStart.x, point.x) * scaleX;
  const boxTop = Math.min(ANNOTATIONS_ED.regionStart.y, point.y) * scaleY;
  ghost.style.left = `${boxLeft}px`;
  ghost.style.top = `${boxTop}px`;
  ghost.style.width = `${Math.abs(point.x - ANNOTATIONS_ED.regionStart.x) * scaleX}px`;
  ghost.style.height = `${Math.abs(point.y - ANNOTATIONS_ED.regionStart.y) * scaleY}px`;
}

function handleAnnotationDrawPointerUp(event) {
  if (!ANNOTATIONS_ED.drawMode) return;
  const image = document.getElementById('annotation-canvas-image');
  if (ANNOTATIONS_ED.drawMode === 'freehand') {
    const ghost = ANNOTATIONS_ED.freehandGhost;
    ANNOTATIONS_ED.freehandGhost = null;
    const points = ANNOTATIONS_ED.freehandPoints;
    ANNOTATIONS_ED.freehandPoints = [];
    const finalPoint = annotationCanvasPoint(event);
    if (finalPoint) points.push([Math.round(finalPoint.x), Math.round(finalPoint.y)]);
    if (points.length < 2 || new Set(points.map(point => point.join(','))).size < 2) {
      ghost?.remove();
      showToast('笔迹太短，请再画一次。');
      return;
    }
    if (ANNOTATIONS_ED.freehandStrokes.length >= 12) {
      ghost?.remove();
      showToast('每条最多 12 笔，请先完成绘制。');
      return;
    }
    ANNOTATIONS_ED.freehandStrokes.push(limitAnnotationPathPoints(points));
    if (ghost) ghost.dataset.pendingStroke = 'true';
    showToast(`已记录第 ${ANNOTATIONS_ED.freehandStrokes.length} 笔，可继续画或点击完成绘制。`);
    return;
  }
  if (!ANNOTATIONS_ED.regionStart) return;
  const ghost = ANNOTATIONS_ED.regionGhost;
  if (ghost) ghost.style.display = 'none';
  ANNOTATIONS_ED.regionGhost = null;
  const start = ANNOTATIONS_ED.regionStart;
  ANNOTATIONS_ED.regionStart = null;
  if (!image) return;
  const geometry = getProjectCanvasGeometry();
  const point = annotationCanvasPoint(event);
  if (!point) return;
  const polygon = AnnotationsCore.rectangleToPolygon(start, point, geometry);
  if (!polygon) {
    showToast('选区太小,请拖出更大的区域。');
    return;
  }
  addAnnotationRegion(polygon);
}

function handleAnnotationDrawPointerCancel() {
  ANNOTATIONS_ED.freehandGhost?.remove();
  ANNOTATIONS_ED.freehandGhost = null;
  ANNOTATIONS_ED.freehandPoints = [];
  ANNOTATIONS_ED.regionStart = null;
  if (ANNOTATIONS_ED.regionGhost) ANNOTATIONS_ED.regionGhost.style.display = 'none';
  ANNOTATIONS_ED.regionGhost = null;
}

function addAnnotationRegion(polygon) {
  if (commitAnnotationRepair(AnnotationsCore.buildRegionTarget(polygon))) return;
  const defaults = ANNOTATIONS_WS.summary?.settings?.defaults || {};
  const item = {
    target: AnnotationsCore.buildRegionTarget(polygon),
    anchor: null,
    style: {
      type: document.getElementById('annotation-new-style')?.value || defaults.type || 'ellipse',
      color: document.getElementById('annotation-new-style')?.value === 'highlighter' ? '#F6CE46' : defaults.color || '#F46A38',
      opacity: document.getElementById('annotation-new-style')?.value === 'highlighter' ? 0.28 : Number(defaults.opacity ?? 0.85),
      width: Number(defaults.width || 5),
      padding: Number(defaults.padding || 8),
      seed: Math.floor(Math.random() * 2147483647),
    },
    timing: {
      trigger_mode: 'manual',
      offset_sec: 0,
      manual_start_sec: 0,
      draw_duration_sec: Number(defaults.draw_duration_sec || 0.6),
      hold_mode: 'slide_end',
      exit_duration_sec: Number(defaults.exit_duration_sec || 0.15),
    },
  };
  pushAnnotationHistory();
  const localId = nextLocalAnnotationId();
  if (ANNOTATIONS_WS.pendingNarrationAnchor) {
    item.anchor = ANNOTATIONS_WS.pendingNarrationAnchor;
    item.timing = {...item.timing, trigger_mode: 'anchor_start', hold_mode: 'beat_end'};
    delete item.timing.manual_start_sec;
  }
  const stored = { ...item, annotation_id: localId };
  ANNOTATIONS_WS.page.items.push(stored);
  // add 操作携带 local id(→ __local_id),保存前合并才能接住后续 update/delete
  queueAnnotationSave(AnnotationsCore.buildAddOperation(stored));
  const lastIndex = ANNOTATIONS_WS.page.items.length - 1;
  renderAnnotationItems();
  renderAnnotationOverlay();
  // 选中新条目(本地临时 id 在保存成功后被服务端 id 替换,此处选最后一项)
  selectAnnotationItem(ANNOTATIONS_WS.page.items[lastIndex].annotation_id);
  setAnnotationDrawMode(null);
  showToast('已添加区域标注，默认从本页开始显示；可在右侧调整样式和出现时间。');
}

function finishAnnotationFreehand(explicit = false) {
  if (ANNOTATIONS_ED.repair && !explicit) return;
  const strokes = ANNOTATIONS_ED.freehandStrokes;
  if (!strokes.length) return;
  ANNOTATIONS_ED.freehandStrokes = [];
  document.querySelectorAll('[data-pending-stroke]').forEach(node => node.remove());
  addAnnotationFreehand(strokes.flat(), strokes);
}

function addAnnotationFreehand(points, pathStrokes = null) {
  const xs = points.map(point => point[0]);
  const ys = points.map(point => point[1]);
  let left = Math.min(...xs);
  let top = Math.min(...ys);
  let right = Math.max(...xs);
  let bottom = Math.max(...ys);
  if (right - left < 1 && bottom - top < 1) {
    showToast('笔迹范围太小，请画出更明显的轨迹。');
    return;
  }
  const geometry = getProjectCanvasGeometry();
  if (right - left < 1) {
    if (right >= geometry.width) left = right - 1;
    else right = left + 1;
  }
  if (bottom - top < 1) {
    if (bottom >= geometry.height) top = bottom - 1;
    else bottom = top + 1;
  }
  const item = buildManualRegionItem([
    [left, top], [right, top], [right, bottom], [left, bottom],
  ]);
  if (pathStrokes) item.target.path_strokes = pathStrokes;
  else item.target.path_points = limitAnnotationPathPoints(points);
  if (commitAnnotationRepair(item.target)) return;
  pushAnnotationHistory();
  const localId = nextLocalAnnotationId();
  if (ANNOTATIONS_WS.pendingNarrationAnchor) {
    item.anchor = ANNOTATIONS_WS.pendingNarrationAnchor;
    item.timing = {...item.timing, trigger_mode: 'anchor_start', hold_mode: 'beat_end'};
    delete item.timing.manual_start_sec;
  }
  const stored = { ...item, annotation_id: localId };
  ANNOTATIONS_WS.page.items.push(stored);
  queueAnnotationSave(AnnotationsCore.buildAddOperation(stored));
  renderAnnotationItems();
  renderAnnotationOverlay();
  const lastItem = ANNOTATIONS_WS.page.items[ANNOTATIONS_WS.page.items.length - 1];
  selectAnnotationItem(lastItem.annotation_id);
  setAnnotationDrawMode(null);
  showToast(stored.anchor ? '自由笔迹已关联讲稿，请同步预览。' : '自由笔迹已保存，请试听设置起笔点。');
}

function buildManualRegionItem(polygon) {
  const defaults = ANNOTATIONS_WS.summary?.settings?.defaults || {};
  return {
    target: { ...AnnotationsCore.buildRegionTarget(polygon), path_points: [] },
    anchor: null,
    style: {
      type: document.getElementById('annotation-new-style')?.value || defaults.type || 'ellipse',
      color: document.getElementById('annotation-new-style')?.value === 'highlighter' ? '#F6CE46' : defaults.color || '#F46A38',
      opacity: document.getElementById('annotation-new-style')?.value === 'highlighter' ? 0.28 : Number(defaults.opacity ?? 0.85),
      width: Number(defaults.width || 5),
      padding: Number(defaults.padding || 8),
      seed: Math.floor(Math.random() * 2147483647),
    },
    timing: {
      trigger_mode: 'manual',
      offset_sec: 0,
      manual_start_sec: 0,
      draw_duration_sec: Number(defaults.draw_duration_sec || 0.6),
      hold_mode: 'slide_end',
      exit_duration_sec: Number(defaults.exit_duration_sec || 0.15),
    },
  };
}

// ------------------------------------------------------------ 讲稿关联

function annotationNarrationAnchorPicked(anchor) {
  const selectedId = ANNOTATIONS_WS.selectedAnnotationId;
  const item = (ANNOTATIONS_WS.page.items || []).find(entry => entry.annotation_id === selectedId);
  if (!item) {
    showToast('请先在列表或画布中选择要关联的标注,再到讲稿中选词。');
    return;
  }
  if (item.target?.kind === 'text' && !item.target?.token_ids?.length) {
    showToast('文字目标需要通过文字候选生成;区域标注可直接关联。');
    return;
  }
  pushAnnotationHistory();
  const index = ANNOTATIONS_WS.page.items.indexOf(item);
  const timing = { ...item.timing, trigger_mode: 'anchor_start' };
  delete timing.manual_start_sec;
  if (timing.hold_mode === 'slide_end') timing.hold_mode = 'beat_end';
  const stored = { ...item, anchor, timing };
  if (String(item.annotation_id).startsWith('local_') && item.__deferredAdd) {
    // 首次提交:文字目标必须带锚点,直接随 add 落盘
    delete stored.__deferredAdd;
    ANNOTATIONS_WS.page.items[index] = stored;
    queueAnnotationSave(AnnotationsCore.buildAddOperation(stored));
  } else {
    ANNOTATIONS_WS.page.items[index] = stored;
    queueAnnotationSave(AnnotationsCore.buildUpdateOperation(item.annotation_id, { anchor, timing }));
  }
  renderAnnotationItems();
  renderAnnotationNarrationHighlights();
  showToast(`已关联讲稿:"${anchor.quote}"`);
}

// ------------------------------------------------------------ 属性编辑

function annotationSelectedItem() {
  return (ANNOTATIONS_WS.page.items || []).find(
    item => item.annotation_id === ANNOTATIONS_WS.selectedAnnotationId
  );
}

function renderAnnotationItemEditor() {
  ANNOTATIONS_ED.calibrationCleanup?.();
  ANNOTATIONS_ED.calibrationCleanup = null;
  const editor = document.getElementById('annotation-item-editor');
  if (!editor) return;
  const item = annotationSelectedItem();
  if (!item) {
    editor.style.display = 'none';
    editor.innerHTML = '';
    return;
  }
  const style = item.style || {};
  const timing = item.timing || {};
  const audioCue = annotationListeningCue(item);
  const opacityPercent = AnnotationsCore.opacityToPercent(style.opacity);
  const isDisabled = item.status?.content === 'disabled';
  editor.style.display = 'block';
  editor.innerHTML = `
    <div class="annotation-editor-title">修改标注 · ${escHtml(item.anchor?.quote || '画面区域')}</div>
    <small>修改会自动保存；保存草稿后仍需同步预览并确认本页。人工修改的条目不会被 AI 重规划覆盖。</small>
    <div class="annotation-actions">
      <button type="button" id="annotation-repair-region" class="secondary compact-action-btn"${isDisabled ? ' disabled' : ''}>重新框选范围</button>
      <button type="button" id="annotation-repair-freehand" class="secondary compact-action-btn"${isDisabled ? ' disabled' : ''}>重画笔迹</button>
      ${ANNOTATIONS_ED.repair ? '<button type="button" id="annotation-cancel-repair" class="secondary compact-action-btn">取消重画</button>' : ''}
    </div>
    <small>框选或重画只修改当前条目，保留讲稿关联和起笔时间。关联错了：在讲稿中选中正确文字，再点击“将所选讲稿关联到当前标注”。</small>
    <div class="annotation-actions">
      <button type="button" id="annotation-save-edits" class="secondary compact-action-btn">保存修改</button>
      <button type="button" id="annotation-preview-edits" class="secondary compact-action-btn">预览修改</button>
    </div>
    <label class="annotation-field">出现方式
      <select id="annotation-edit-trigger-mode">
        <option value="manual"${timing.trigger_mode === 'manual' ? ' selected' : ''}>本页指定时间</option>
        <option value="anchor_start"${timing.trigger_mode === 'anchor_start' ? ' selected' : ''}${item.anchor ? '' : ' disabled'}>跟随讲稿关联</option>
      </select>
    </label>
    <label class="annotation-field annotation-manual-start${timing.trigger_mode === 'manual' ? '' : ' hidden'}">出现时间(${timing.time_reference === 'audio' ? '音频' : '页面'}秒)
      <input type="number" id="annotation-edit-timing-start" min="0" max="3600" step="0.001" value="${Number(timing.manual_start_sec || 0)}">
      ${timing.calibration_stale ? '<small role="alert">音频已变化：此时间仅供定位，请重新试听并记录起笔点。</small>' : ''}
      <small>${timing.time_reference === 'audio' ? '从音频文件起点计时（包含开头静音），系统自动加入播放延迟。' : '从页面出现开始计时，包含音频前的等待时间。'}</small>
    </label>
    <div class="annotation-field">
      <span>试听定位起笔点</span>
      <small>所选短语：${escHtml(item.anchor?.quote || '未关联讲稿')}。请定位第一个字开始发音的位置。</small>
      <small id="annotation-audio-cue" aria-live="polite">${audioCue ? `自动参考 ${audioCue.start.toFixed(3)} 秒（请试听核对）` : '没有可靠的自动参考，可手动试听定位。'}</small>
      <button type="button" id="annotation-listen-phrase" class="secondary compact-action-btn"${audioCue ? '' : ' disabled'}>试听所选短语</button>
      <audio id="annotation-calibration-audio" controls preload="metadata"
        src="/api/projects/${encodeURIComponent(ANNOTATIONS_WS.projectId)}/slides/${encodeURIComponent(ANNOTATIONS_WS.page.slide_id)}/audio"></audio>
      <canvas id="annotation-audio-waveform" width="800" height="64" style="width:100%;height:64px;cursor:crosshair" aria-label="音频波形，点击可定位；也可用播放器和前后帧按钮定位"></canvas>
      <small id="annotation-audio-position" aria-live="polite">正在加载波形…</small>
      <button type="button" id="annotation-use-audio-time" class="secondary compact-action-btn">以当前音频位置起笔</button>
      <div class="annotation-actions">
        <button type="button" data-annotation-audio-frame="-1" class="secondary compact-action-btn">前一帧</button>
        <button type="button" data-annotation-audio-frame="1" class="secondary compact-action-btn">后一帧</button>
        <button type="button" id="annotation-audio-loop" class="secondary compact-action-btn">循环试听前后 1 秒</button>
        <button type="button" id="annotation-restore-auto" class="secondary compact-action-btn"${item.anchor ? '' : ' disabled'}>恢复讲稿定位</button>
      </div>
      <small>听到关联内容时暂停并设置；之后用同步预览检查。</small>
    </div>
    <label class="annotation-field">关联画面内容组
      <select id="annotation-edit-mask-group">
        <option value="">自动按目标区域检查</option>
        ${(ANNOTATIONS_WS.page.mask_groups || []).map(group => `<option value="${escHtml(group.id)}"${item.target?.mask_group_ids?.includes(group.id) ? ' selected' : ''}>${escHtml(group.label)}</option>`).join('')}
      </select>
      <small>手绘线条未接触内容时，可指定对应内容组检查出现时机。</small>
    </label>
    <label class="annotation-field">样式
      <select id="annotation-edit-style-type">
        <option value="ellipse"${style.type === 'ellipse' ? ' selected' : ''}>手写圈</option>
        <option value="underline"${style.type === 'underline' ? ' selected' : ''}>横线</option>
        <option value="highlighter"${style.type === 'highlighter' ? ' selected' : ''}>荧光笔</option>
      </select>
    </label>
    <label class="annotation-field">颜色
      <input type="color" id="annotation-edit-style-color" value="${escHtml(style.color || '#F46A38')}">
    </label>
    <label class="annotation-field">笔迹浓度 <span id="annotation-edit-opacity-value">${opacityPercent}%</span>
      <input type="range" id="annotation-edit-style-opacity" min="0" max="100" step="5" value="${opacityPercent}">
    </label>
    <label class="annotation-field">粗细(px)
      <input type="number" id="annotation-edit-style-width" min="1" max="40" value="${Number(style.width || 5)}">
    </label>
    <label class="annotation-field">留白(px)
      <input type="number" id="annotation-edit-style-padding" min="0" max="80" value="${Number(style.padding || 8)}">
    </label>
    <label class="annotation-field">提前/延后(秒)
      <input type="number" id="annotation-edit-timing-offset" min="-5" max="5" step="0.05" value="${Number(timing.offset_sec || 0)}">
    </label>
    <label class="annotation-field">绘制时长(秒)
      <input type="number" id="annotation-edit-timing-draw" min="0.05" max="10" step="0.05" value="${Number(timing.draw_duration_sec || 0.6)}">
    </label>
    <label class="annotation-field">保留方式
      <select id="annotation-edit-timing-hold">
        <option value="beat_end"${(timing.hold_mode || 'beat_end') === 'beat_end' ? ' selected' : ''}>到语块结束</option>
        <option value="slide_end"${timing.hold_mode === 'slide_end' ? ' selected' : ''}>到页面结束</option>
        <option value="duration"${timing.hold_mode === 'duration' ? ' selected' : ''}>固定时长</option>
      </select>
    </label>
    <label class="annotation-field hold-duration${timing.hold_mode === 'duration' ? '' : ' hidden'}">保留时长(秒)
      <input type="number" id="annotation-edit-timing-hold-duration" min="0.05" max="120" step="0.1" value="${Number(timing.hold_duration_sec || 3)}">
    </label>
    <label class="annotation-field annotation-lock-field">
      <input type="checkbox" id="annotation-edit-locked"${item.protection?.locked ? ' checked' : ''}>
      锁定(防止 AI 重规划改写)
    </label>
    <div class="annotation-editor-actions">
      <button type="button" id="annotation-btn-toggle-disable" class="secondary compact-action-btn">${isDisabled ? '重新启用' : '禁用此条'}</button>
      <button type="button" id="annotation-btn-delete" class="danger compact-action-btn">删除</button>
    </div>
  `;
  bindAnnotationEditorEvents(item.annotation_id);
}

function queueAnnotationItemPatch(annotationId, patchOrCollector) {
  const item = (ANNOTATIONS_WS.page.items || []).find(entry => entry.annotation_id === annotationId);
  if (!item) return;
  // patch 允许是对象或 (item) => patch 的收集函数(依赖编辑时条目现状)
  const patch = typeof patchOrCollector === 'function' ? patchOrCollector(item) : patchOrCollector;
  if (!patch || typeof patch !== 'object' || !Object.keys(patch).length) return;
  const index = ANNOTATIONS_WS.page.items.indexOf(item);
  ANNOTATIONS_WS.page.items[index] = { ...item, ...patch };
  if (String(annotationId).startsWith('local_') && ANNOTATIONS_WS.page.items[index].__deferredAdd) {
    // 延迟提交的本地条目:仅更新本地状态,最终随 add 一并提交
  } else {
    queueAnnotationSave(AnnotationsCore.buildUpdateOperation(annotationId, patch));
  }
  renderAnnotationItems();
  renderAnnotationOverlay();
  renderAnnotationNarrationHighlights();
}

function flushAnnotationEditorEdits() {
  clearTimeout(ANNOTATIONS_ED.editorTimer);
  ANNOTATIONS_ED.editorTimer = null;
  const pending = ANNOTATIONS_ED.pendingEdit;
  ANNOTATIONS_ED.pendingEdit = null;
  if (!pending || pending.projectId !== ANNOTATIONS_WS.projectId
      || pending.slideId !== ANNOTATIONS_WS.page.slide_id) return;
  pushAnnotationHistory();
  queueAnnotationItemPatch(pending.annotationId, pending.patch);
}

function scheduleAnnotationStyleCommit(annotationId, collect) {
  const pending = ANNOTATIONS_ED.pendingEdit;
  if (pending && pending.annotationId !== annotationId) flushAnnotationEditorEdits();
  const item = ANNOTATIONS_WS.page.items.find(entry => entry.annotation_id === annotationId);
  if (!item) return;
  const previous = ANNOTATIONS_ED.pendingEdit;
  const patch = collect({...item, ...(previous?.patch || {})});
  ANNOTATIONS_ED.pendingEdit = {
    projectId: ANNOTATIONS_WS.projectId, slideId: ANNOTATIONS_WS.page.slide_id,
    annotationId, patch: {...(previous?.patch || {}), ...patch},
  };
  clearTimeout(ANNOTATIONS_ED.editorTimer);
  ANNOTATIONS_ED.editorTimer = setTimeout(flushAnnotationEditorEdits, 350);
}
window.flushAnnotationEditorEdits = flushAnnotationEditorEdits;

function annotationListeningCue(item) {
  const cue = ANNOTATIONS_WS.page.audio_locator?.[item?.annotation_id];
  const anchor = item?.anchor;
  return cue && anchor && cue.beat_id === anchor.beat_id && cue.quote === anchor.quote
    && cue.range?.[0] === anchor.range?.[0] && cue.range?.[1] === anchor.range?.[1]
    && Number.isFinite(cue.start) && Number.isFinite(cue.end) ? cue : null;
}

function bindAnnotationEditorEvents(annotationId) {
  const editor = document.getElementById('annotation-item-editor');
  if (!editor) return;
  editor.querySelector('#annotation-repair-region')?.addEventListener('click', () => beginAnnotationRepair('region'));
  editor.querySelector('#annotation-repair-freehand')?.addEventListener('click', () => beginAnnotationRepair('freehand'));
  editor.querySelector('#annotation-cancel-repair')?.addEventListener('click', () => {
    cancelAnnotationRepair(); setAnnotationDrawMode(null); renderAnnotationItemEditor();
    showToast('已取消重画，原标注保留。');
  });
  editor.querySelector('#annotation-save-edits')?.addEventListener('click', () => saveAnnotationEdits().catch(error => showToast(error.message)));
  editor.querySelector('#annotation-preview-edits')?.addEventListener('click', () => {
    previewAnnotationAnimation();
  });

  const calibration = editor.querySelector('#annotation-calibration-audio');
  let loopRange = null;
  const waveform = editor.querySelector('#annotation-audio-waveform');
  const selected = annotationSelectedItem(), cue = annotationListeningCue(selected);
  const manual = selected?.timing?.trigger_mode === 'manual' && Number.isFinite(selected.timing.manual_start_sec)
    ? Math.max(0, selected.timing.manual_start_sec - (selected.timing.time_reference === 'audio' ? 0 : (ANNOTATIONS_WS.page.audio_start_sec || 0))) : null;
  const initialTime = Number.isFinite(manual) ? manual : (cue?.start || 0);
  const markers = cue ? [{start: cue.start, end: cue.end, color: '#777'}] : [];
  if (Number.isFinite(manual)) markers.push({start: manual, color: '#f46a38'});
  if (calibration && waveform && window.AnnotationAudioCalibration) ANNOTATIONS_ED.calibrationCleanup =
    window.AnnotationAudioCalibration.attach({audio: calibration, canvas: waveform, status: editor.querySelector('#annotation-audio-position'), initialTime, markers});
  const stopLoop = () => {loopRange = null; const button = editor.querySelector('#annotation-audio-loop'); if (button) button.textContent = '循环试听前后 1 秒';};
  waveform?.addEventListener('click', stopLoop);
  editor.querySelector('#annotation-listen-phrase')?.addEventListener('click', () => {
    if (!cue || !calibration || !Number.isFinite(calibration.duration)) return;
    stopLoop();
    loopRange = [Math.max(0, cue.start - .6), Math.min(calibration.duration, cue.end + .3)];
    calibration.currentTime = loopRange[0];
    editor.querySelector('#annotation-audio-loop').textContent = '停止循环试听';
    calibration.play().catch(error => showToast(error.message));
  });
  calibration?.addEventListener('timeupdate', () => {
    const char = cue?.characters?.find(char => calibration.currentTime >= char.start && calibration.currentTime < char.end);
    const label = editor.querySelector('#annotation-audio-cue');
    if (label && cue) label.textContent = char ? `自动参考正在讲：${char.text}（请听音核对）` : `自动参考 ${cue.start.toFixed(3)} 秒（请试听核对）`;
    if (loopRange && calibration.currentTime >= loopRange[1]) calibration.currentTime = loopRange[0];
  });
  editor.querySelectorAll('[data-annotation-audio-frame]').forEach(button => button.addEventListener('click', () => {
    if (!calibration || !Number.isFinite(calibration.duration)) return;
    calibration.pause(); stopLoop();
    const fps = ANNOTATION_PREVIEW?.prepared?.result?.timeline?.fps || 30;
    calibration.currentTime = Math.min(calibration.duration, Math.max(0,
      calibration.currentTime + Number(button.dataset.annotationAudioFrame) / fps));
  }));
  editor.querySelector('#annotation-audio-loop')?.addEventListener('click', event => {
    if (!calibration || !Number.isFinite(calibration.duration)) return;
    if (loopRange) {loopRange = null; calibration.pause(); event.target.textContent = '循环试听前后 1 秒'; return;}
    loopRange = [Math.max(0, calibration.currentTime - 1), Math.min(calibration.duration, calibration.currentTime + 1)];
    calibration.currentTime = loopRange[0]; event.target.textContent = '停止循环试听';
    calibration.play().catch(error => showToast(error.message));
  });
  editor.querySelector('#annotation-restore-auto')?.addEventListener('click', () => {
    const item = annotationSelectedItem();
    if (!item?.anchor) return;
    calibration?.pause(); loopRange = null;
    const timing = {...item.timing, trigger_mode: 'anchor_start', offset_sec: 0};
    delete timing.manual_start_sec; delete timing.time_reference;
    pushAnnotationHistory(); queueAnnotationItemPatch(annotationId, {timing});
    renderAnnotationItemEditor();
  });

  editor.querySelector('#annotation-edit-mask-group')?.addEventListener('change', event => {
    pushAnnotationHistory();
    const item = annotationSelectedItem();
    if (item) queueAnnotationItemPatch(annotationId, {target: {...item.target, mask_group_ids: event.target.value ? [event.target.value] : []}});
  });
  editor.querySelector('#annotation-use-audio-time')?.addEventListener('click', () => {
    const audio = editor.querySelector('#annotation-calibration-audio');
    const item = annotationSelectedItem();
    if (!audio || !item || !Number.isFinite(audio.duration) || audio.readyState < 1) {
      showToast('请先加载并试听本页音频。');
      return;
    }
    audio.pause(); stopLoop();
    if (audio.currentTime >= audio.duration) {showToast('请定位到音频结束之前的发音起点。'); return;}
    pushAnnotationHistory();
    queueAnnotationItemPatch(annotationId, {timing: {...item.timing,
      trigger_mode: 'manual', manual_start_sec: audio.currentTime, time_reference: 'audio', offset_sec: 0,
      calibration_stale: false}});
    renderAnnotationItemEditor();
    showToast(`已设置音频 ${audio.currentTime.toFixed(3)} 秒起笔，请预览确认。`);
  });
  const styleType = editor.querySelector('#annotation-edit-style-type');
  styleType?.addEventListener('change', () => {
    pushAnnotationHistory();
    queueAnnotationItemPatch(annotationId, item => ({ style: { ...item.style, type: styleType.value } }));
  });

  const color = editor.querySelector('#annotation-edit-style-color');
  color?.addEventListener('change', () => {
    scheduleAnnotationStyleCommit(annotationId, item => ({ style: { ...item.style, color: color.value.toUpperCase() } }));
  });

  const opacity = editor.querySelector('#annotation-edit-style-opacity');
  const opacityValue = editor.querySelector('#annotation-edit-opacity-value');
  opacity?.addEventListener('input', () => {
    if (opacityValue) opacityValue.textContent = `${opacity.value}%`;
  });
  opacity?.addEventListener('change', () => {
    pushAnnotationHistory();
    queueAnnotationItemPatch(annotationId, item => ({
      style: { ...item.style, opacity: AnnotationsCore.percentToOpacity(Number(opacity.value)) },
    }));
  });

  const numberFields = [
    ['#annotation-edit-style-width', 'width'],
    ['#annotation-edit-style-padding', 'padding'],
  ];
  numberFields.forEach(([selector, key]) => {
    const input = editor.querySelector(selector);
    input?.addEventListener('change', () => {
      scheduleAnnotationStyleCommit(annotationId, item => ({
        style: { ...item.style, [key]: Math.max(0, Math.round(Number(input.value) || 0)) },
      }));
    });
  });

  const timingFields = [
    ['#annotation-edit-timing-offset', 'offset_sec', true],
    ['#annotation-edit-timing-draw', 'draw_duration_sec', true],
    ['#annotation-edit-timing-hold-duration', 'hold_duration_sec', true],
  ];
  timingFields.forEach(([selector, key, isFloat]) => {
    const input = editor.querySelector(selector);
    input?.addEventListener('change', () => {
      scheduleAnnotationStyleCommit(annotationId, item => {
        const timing = { ...item.timing };
        timing[key] = isFloat ? Number(input.value) : Math.round(Number(input.value) || 0);
        return { timing };
      });
    });
  });

  const triggerMode = editor.querySelector('#annotation-edit-trigger-mode');
  triggerMode?.addEventListener('change', () => {
    const item = annotationSelectedItem();
    if (!item) return;
    if (triggerMode.value === 'anchor_start' && !item.anchor) {
      showToast('请先在“讲稿关联”中选中要关联的短语。');
      triggerMode.value = 'manual';
      return;
    }
    pushAnnotationHistory();
    const timing = { ...item.timing, trigger_mode: triggerMode.value };
    if (triggerMode.value === 'manual') {
      timing.manual_start_sec = Number(item.timing.manual_start_sec || 0);
      timing.time_reference = 'slide';
      if (!item.anchor && timing.hold_mode === 'beat_end') timing.hold_mode = 'slide_end';
    } else {
      delete timing.manual_start_sec;
      if (timing.hold_mode === 'slide_end') timing.hold_mode = 'beat_end';
    }
    queueAnnotationItemPatch(annotationId, { timing });
    renderAnnotationItemEditor();
  });
  editor.querySelector('#annotation-edit-timing-start')?.addEventListener('change', event => {
    scheduleAnnotationStyleCommit(annotationId, item => ({
      timing: { ...item.timing, manual_start_sec: Math.max(0, Number(event.target.value) || 0), calibration_stale: false },
    }));
  });

  const hold = editor.querySelector('#annotation-edit-timing-hold');
  hold?.addEventListener('change', () => {
    const holdDurationField = editor.querySelector('.hold-duration');
    if (holdDurationField) holdDurationField.classList.toggle('hidden', hold.value !== 'duration');
    scheduleAnnotationStyleCommit(annotationId, item => {
      const timing = { ...item.timing, hold_mode: hold.value };
      if (hold.value !== 'duration') delete timing.hold_duration_sec;
      else timing.hold_duration_sec = Number(editor.querySelector('#annotation-edit-timing-hold-duration')?.value || 3);
      return { timing };
    });
  });

  const locked = editor.querySelector('#annotation-edit-locked');
  locked?.addEventListener('change', () => {
    pushAnnotationHistory();
    queueAnnotationItemPatch(annotationId, item => ({
      protection: { locked: locked.checked },
    }));
  });

  editor.querySelector('#annotation-btn-toggle-disable')?.addEventListener('click', () => {
    const item = annotationSelectedItem();
    if (!item) return;
    const next = item.status?.content === 'disabled' ? 'draft' : 'disabled';
    pushAnnotationHistory();
    queueAnnotationItemPatch(annotationId, item2 => ({ status: { content: next } }));
  });

  editor.querySelector('#annotation-btn-delete')?.addEventListener('click', () => {
    const item = annotationSelectedItem();
    if (!item) return;
    showCustomConfirm('删除标注', `确定删除 ${item.annotation_id} 吗?可用撤销恢复。`, () => {
      pushAnnotationHistory();
      ANNOTATIONS_WS.page.items = ANNOTATIONS_WS.page.items.filter(entry => entry.annotation_id !== annotationId);
      ANNOTATIONS_WS.selectedAnnotationId = null;
      queueAnnotationSave(AnnotationsCore.buildDeleteOperation(annotationId));
      renderAnnotationItems();
      renderAnnotationOverlay();
      renderAnnotationNarrationHighlights();
      renderAnnotationItemEditor();
    });
  });
}

// ------------------------------------------------------------ 撤销/重做

function setAnnotationVideoStart(annotationId, audioTime) {
  const item = ANNOTATIONS_WS.page.items.find(item => item.annotation_id === annotationId);
  if (!item || !Number.isFinite(audioTime) || audioTime < 0) return false;
  pushAnnotationHistory();
  queueAnnotationItemPatch(annotationId, {timing: {...item.timing,
    trigger_mode: 'manual', manual_start_sec: audioTime, time_reference: 'audio',
    offset_sec: 0, calibration_stale: false}});
  renderAnnotationItemEditor();
  return true;
}
window.setAnnotationVideoStart = setAnnotationVideoStart;

function pushAnnotationHistory() {
  const slideId = ANNOTATIONS_WS.page.slide_id;
  if (!slideId) return;
  if (!ANNOTATIONS_WS.histories[slideId]) {
    ANNOTATIONS_WS.histories[slideId] = AnnotationsCore.createPageHistory();
  }
  // 快照只保留服务端已认可的结构字段;本地临时 id 的条目原样保留
  ANNOTATIONS_WS.histories[slideId].push(ANNOTATIONS_WS.page.items);
}

// 撤销未保存条目时撤下其排队/隔离中的 add 操作。返回是否确实撤下了排队项;
// false 表示 add 不在队列里(可能在飞或已保存),调用方应改为排队 delete。
function cancelPendingLocalAnnotationAdd(localId) {
  const pendingBefore = ANNOTATIONS_WS.pendingOps.length;
  const failedBefore = ANNOTATIONS_WS.failedOps.length;
  ANNOTATIONS_WS.pendingOps = ANNOTATIONS_WS.pendingOps.filter(
    op => !(op && op.op === 'add' && op.__local_id === localId)
  );
  ANNOTATIONS_WS.failedOps = ANNOTATIONS_WS.failedOps.filter(
    op => !(op && op.op === 'add' && op.__local_id === localId)
  );
  const removed = ANNOTATIONS_WS.pendingOps.length !== pendingBefore
    || ANNOTATIONS_WS.failedOps.length !== failedBefore;
  if (removed
    && !ANNOTATIONS_WS.pendingOps.length
    && !ANNOTATIONS_WS.failedOps.length
    && !ANNOTATIONS_WS.saveInFlight
    && !ANNOTATIONS_WS.conflict) {
    clearTimeout(ANNOTATIONS_WS.saveTimer);
    ANNOTATIONS_WS.saveTimer = null;
    renderAnnotationSaveStatus('idle');
  }
  return ANNOTATIONS_WS.pendingOps.length !== pendingBefore;
}

function queueSyncAnnotationItems(currentItems, targetItems) {
  const current = currentItems || [];
  const currentIds = new Set(current.map(item => item.annotation_id));
  const targetIds = new Set(targetItems.map(item => item.annotation_id));
  const operations = [];
  targetItems.forEach(item => {
    if (currentIds.has(item.annotation_id)) return;
    if (String(item.annotation_id).startsWith('local_')) {
      // 撤销/重做找回的未保存条目:重入队 add(__local_id 让保存前合并继续生效);
      // 入队即视为待保存,清除延迟标记,让后续撤销走"撤下 add"路径
      item.__deferredAdd = false;
      operations.push(AnnotationsCore.buildAddOperation(item));
    } else {
      const { annotation_id, ...rest } = item;
      void annotation_id;
      operations.push(AnnotationsCore.buildAddOperation(rest));
    }
  });
  current.forEach(item => {
    if (targetIds.has(item.annotation_id)) return;
    if (String(item.annotation_id).startsWith('local_')) {
      // 延迟提交的本地条目(尚无 add 操作):仅从本地删除,不产生服务端操作
      if (item.__deferredAdd) return;
      // 该条目尚未保存:直接撤下排队/隔离中的 add;若 add 已在飞,
      // 落一个 delete 由 flush 成功后的 local id 重映射改写为服务端 id
      if (!cancelPendingLocalAnnotationAdd(item.annotation_id)) {
        operations.push(AnnotationsCore.buildDeleteOperation(item.annotation_id));
      }
    } else {
      operations.push(AnnotationsCore.buildDeleteOperation(item.annotation_id));
    }
  });
  targetItems.forEach(item => {
    if (currentIds.has(item.annotation_id)) {
      // 延迟提交的本地条目:状态只留在本地,最终随 add 一并提交
      if (String(item.annotation_id).startsWith('local_') && item.__deferredAdd) return;
      const before = current.find(entry => entry.annotation_id === item.annotation_id);
      const patch = {};
      if (JSON.stringify(before?.target) !== JSON.stringify(item.target)) patch.target = item.target;
      if (JSON.stringify(before?.anchor) !== JSON.stringify(item.anchor)) patch.anchor = item.anchor;
      if (JSON.stringify(before?.style) !== JSON.stringify(item.style)) patch.style = item.style;
      if (JSON.stringify(before?.timing) !== JSON.stringify(item.timing)) patch.timing = item.timing;
      if (before?.protection?.locked !== item?.protection?.locked) patch.protection = { locked: item.protection?.locked === true };
      const beforeContent = before?.status?.content === 'disabled' ? 'disabled' : 'draft';
      const afterContent = item?.status?.content === 'disabled' ? 'disabled' : 'draft';
      if (beforeContent !== afterContent) patch.status = { content: afterContent };
      if (Object.keys(patch).length) operations.push(AnnotationsCore.buildUpdateOperation(item.annotation_id, patch));
    }
  });
  if (operations.length) queueAnnotationSave(operations);
}

function undoAnnotationEdit() {
  cancelAnnotationRepair();
  const slideId = ANNOTATIONS_WS.page.slide_id;
  const history = slideId && ANNOTATIONS_WS.histories[slideId];
  if (!history?.canUndo()) return;
  const restored = history.undo(ANNOTATIONS_WS.page.items);
  if (!restored) return;
  // 先以变更前的条目作为 diff 基准再替换,否则队列会把数组与自身比较,
  // 永远算出 0 个操作(撤销只改屏幕,下一次自动保存会静默回滚)。
  const before = ANNOTATIONS_WS.page.items;
  ANNOTATIONS_WS.page.items = restored;
  queueSyncAnnotationItems(before, restored);
  renderAnnotationItems();
  renderAnnotationOverlay();
  renderAnnotationNarrationHighlights();
  renderAnnotationItemEditor();
}

function redoAnnotationEdit() {
  cancelAnnotationRepair();
  const slideId = ANNOTATIONS_WS.page.slide_id;
  const history = slideId && ANNOTATIONS_WS.histories[slideId];
  if (!history?.canRedo()) return;
  const restored = history.redo(ANNOTATIONS_WS.page.items);
  if (!restored) return;
  const before = ANNOTATIONS_WS.page.items;
  ANNOTATIONS_WS.page.items = restored;
  queueSyncAnnotationItems(before, restored);
  renderAnnotationItems();
  renderAnnotationOverlay();
  renderAnnotationNarrationHighlights();
  renderAnnotationItemEditor();
}

function annotationEditorKeyboardHandler(event) {
  if (!(event.ctrlKey || event.metaKey) || event.key !== 'z') return;
  const target = event.target;
  if (target instanceof HTMLElement && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable)) {
    return; // 输入控件内保留原生撤销
  }
  const panel = document.getElementById('step-panel-10');
  if (!panel || panel.style.display === 'none') return;
  event.preventDefault();
  if (event.shiftKey) redoAnnotationEdit();
  else undoAnnotationEdit();
}

// ------------------------------------------------------------ 桥接

window.renderAnnotationOverlay = renderAnnotationOverlay;
window.renderAnnotationItemEditor = renderAnnotationItemEditor;
window.setAnnotationDrawMode = setAnnotationDrawMode;
window.setAnnotationRegionMode = enabled => setAnnotationDrawMode(enabled ? 'region' : null);
window.annotationNarrationAnchorPicked = annotationNarrationAnchorPicked;
window.undoAnnotationEdit = undoAnnotationEdit;
window.redoAnnotationEdit = redoAnnotationEdit;
window.annotationEditorKeyboardHandler = annotationEditorKeyboardHandler;
window.addAnnotationRegion = addAnnotationRegion;
window.previewAnnotationAnimation = previewAnnotationAnimation;
window.finishAnnotationFreehand = finishAnnotationFreehand;
window.cancelAnnotationRepair = cancelAnnotationRepair;
window.annotationRepairPending = () => Boolean(ANNOTATIONS_ED.repair);
window.cancelAnnotationPreviewLoop = cancelAnnotationPreviewLoop;
window.handleAnnotationDrawPointerDown = handleAnnotationDrawPointerDown;
window.handleAnnotationDrawPointerMove = handleAnnotationDrawPointerMove;
window.handleAnnotationDrawPointerUp = handleAnnotationDrawPointerUp;
