const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const app = fs.readFileSync(path.join(root, 'static', 'app.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'static', 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'static', 'style.css'), 'utf8');

if (!css.includes('#toast-container')) throw new Error('toast container layout missing');
if (!css.includes('left: 0.85rem')) throw new Error('toasts are not anchored in the left navigation area');
if (/\.toast\s*\{[^}]*position:\s*fixed/s.test(css)) throw new Error('individual toasts still overlap at a fixed position');
if (!/\.step3-card-title\s*\{[^}]*min-height:\s*0/s.test(css)) throw new Error('image title still reserves fixed vertical space');

if (html.includes('config_effectiveness.js')) throw new Error('runtime patch script is still loaded');
if (!html.includes('btn-storyboard-rules-save-regenerate')) throw new Error('storyboard regenerate action missing');
if (!html.includes('storyboard-profile-input') || !html.includes('storyboard-schema-input')) {
  throw new Error('storyboard role profile or JSON Schema editor is missing');
}
if (!app.includes('storyboardRoleOptions') || !app.includes('addVisualGroup')) {
  throw new Error('storyboard visual role editing is missing');
}
if (app.includes("group.id === 'body_group_02'")) {
  throw new Error('legacy hard-coded visual group filtering is still present');
}
if (!html.includes('step3-btn-batch-generate')) throw new Error('step 3 batch image generation action missing');
if (!html.includes('step3-video-background-color') || !html.includes('step3-video-background-text')) {
  throw new Error('project video background color controls missing');
}
if (!html.includes('step3-video-background-apply')) throw new Error('video background apply button missing');
if (!app.includes('saveStep3VideoBackground')) throw new Error('video background color save handler missing');
if (!app.includes('hexToRgba(color, isSelected ? 0.46 : 0.34)')) {
  throw new Error('mask overlay colors are too faint');
}
if (!app.includes('generateAllStep3Images')) throw new Error('step 3 batch generation handler missing');
if (!app.includes('step3GeneratingSlides')) throw new Error('step 3 per-slide generation state missing');
if (!app.includes('tasks.forEach(task => step3GeneratingSlides.add(task.slideId))')) {
  throw new Error('batch generation does not switch all cards to loading immediately');
}
if (!app.includes("document.getElementById('step3-preview-box').innerHTML = step3GeneratingPreviewHtml()")) {
  throw new Error('single image generation does not show loading in the preview pane');
}
if (!css.includes('.step3-generating-preview')) throw new Error('step 3 loading preview style missing');
if (!app.includes('await refreshStep3Images();')) throw new Error('step 3 does not wait for image state');
if (!app.includes('confirmBtn.disabled = !allImagesReady')) throw new Error('step 3 confirmation is not gated');
if (!app.includes('step5AutoSavePromise')) throw new Error('step 5 save serialization missing');
if (!app.includes("raw.type || raw.value || 'wipe_left_to_right'")) {
  throw new Error('mask animation preset values are not normalized correctly');
}
if (!app.includes('applyGlobalMaskReveal') || !app.includes('previewGlobalAnimationSettings')) {
  throw new Error('global Mask animation sync or preview is missing');
}
for (const animation of ['wipe_left_to_right', 'scratch_reveal', 'sticker_pop', 'stamp_in', 'paper_drop']) {
  if (!app.includes(`value: '${animation}'`)) {
    throw new Error(`mask animation preset missing: ${animation}`);
  }
}
if (!html.includes('step5-btn-subtitle-settings') || !html.includes('modal-subtitle-settings')) {
  throw new Error('subtitle settings entry or modal is missing');
}
for (const removedNarrationPolicyToken of [
  'updateGroupSpeakPolicy',
  'groupSpeakPolicy',
  'step2-speak-policy-select',
  'storyboard-role-required',
  'storyboard-role-speak-policy',
  '仅画面展示',
  '旁白策略',
]) {
  if (app.includes(removedNarrationPolicyToken) || html.includes(removedNarrationPolicyToken)) {
    throw new Error(`legacy narration policy UI still present: ${removedNarrationPolicyToken}`);
  }
}
if (!html.includes('id="step5-brush-size"') || !html.includes('value="170"')) {
  throw new Error('brush size control or 170 default missing');
}
if (!html.includes('id="step5-eraser-size"') || !html.includes('value="120"')) {
  throw new Error('separate eraser size control or 120 default missing');
}
if (!app.includes('getActiveMaskToolSize')) throw new Error('brush and eraser sizes are not selected by tool');
if (!css.includes('box-sizing: border-box') || !css.includes('.step5-brush-cursor')) {
  throw new Error('mask cursor outer diameter is not aligned to the stroke diameter');
}
if (!app.includes('clientX - wrapperRect.left - borderLeft')) {
  throw new Error('mask cursor position does not compensate for the canvas wrapper border');
}
if (!app.includes("newCanvas.addEventListener('pointerdown'")) {
  throw new Error('mask editor does not use pointer capture capable input events');
}
if (!app.includes('pointerWithinMaskToolReach')) {
  throw new Error('mask editor has no outside-edge interaction allowance');
}
if (!app.includes('rebuildStep5SourceCache')) throw new Error('source image cache missing');
if (!app.includes('ctx.drawImage(step5SourceCanvas, 0, 0)')) {
  throw new Error('mask editor does not keep the full source visible');
}
for (const removedToken of [
  'step5-live-coverage',
  'step5-btn-preview',
  'modal-mask-preview',
  'step5-foreground-mask-img',
  'createStep5UncoveredPattern',
  'scheduleStep5CoverageCheck',
  '/steps/5/preview',
  'selection_ratio',
  'reveal_boxes',
  'modal-narration-picker',
  'autoMaskLoading',
  'runStep5AutoMask',
]) {
  if (html.includes(removedToken) || app.includes(removedToken) || css.includes(removedToken)) {
    throw new Error(`legacy Mask diagnostics still present: ${removedToken}`);
  }
}
if (!app.includes('refreshStep3Prompts({ updateOpenEditor: state.currentStep === 3 })')) {
  throw new Error('image style changes do not refresh prompts');
}

console.log('frontend quality checks passed');
