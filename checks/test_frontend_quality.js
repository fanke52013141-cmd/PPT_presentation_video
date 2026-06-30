const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const app = fs.readFileSync(path.join(root, 'static', 'app.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'static', 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'static', 'style.css'), 'utf8');
const aiMask = fs.readFileSync(path.join(root, 'static', 'ai_mask_extension.js'), 'utf8');
const background = fs.readFileSync(path.join(root, 'static', 'storyboard_background_extension.js'), 'utf8');
const styleManager = fs.readFileSync(path.join(root, 'static', 'style_reference_manager_extension.js'), 'utf8');
const oneClick = fs.readFileSync(path.join(root, 'static', 'one_click_extension.js'), 'utf8');

if (!css.includes('#toast-container')) throw new Error('toast container layout missing');
if (!css.includes('left: 18px')) throw new Error('desktop toasts are not anchored inside the workflow rail');
if (/\.toast\s*\{[^}]*position:\s*fixed/s.test(css)) throw new Error('individual toasts still overlap at a fixed position');
if (!/\.step3-card-header\s*\{[^}]*min-height:\s*64px/s.test(css)) throw new Error('image card header height is not stable');
if (!/\.step3-card-actions\s*\{[^}]*grid-template-columns:\s*48px 36px 36px/s.test(css)) throw new Error('image card action columns are not stable');
if (!/\.step3-card-action[\s\S]*?white-space:\s*nowrap\s*!important/s.test(css)) throw new Error('image card actions can still wrap and jitter');
if (!app.includes('step3-action-placeholder')) throw new Error('image card delete action does not reserve a stable slot');

if (html.includes('config_effectiveness.js')) throw new Error('runtime patch script is still loaded');
for (const requiredStep2Token of [
  'step2-btn-script-prompt',
  'step2-btn-visual-prompt',
  'step2-script-system-prompt',
  'step2-script-output-example',
  'step2-visual-system-prompt',
  'step2-visual-output-example',
  'step2-slide-title-input',
  'step2-slide-subtitle-input',
  'step2-slide-body-input',
  'step2-slide-narration-input',
]) {
  if (!html.includes(requiredStep2Token)) throw new Error(`simplified Step 2 UI missing: ${requiredStep2Token}`);
}
for (const removedStep2Token of [
  'step2-btn-rules',
  'btn-storyboard-rules-save-regenerate',
  'storyboard-template-select',
  'storyboard-profile-input',
  'storyboard-schema-input',
  'storyboard-rules-input',
  'step2-groups-list',
  'storyboardRoleOptions',
  'addVisualGroup',
  'updateGroupField',
  'removeVisualGroup',
  'generateStoryboardRulesAiDraft',
  'storyboard-ai-draft',
]) {
  if (app.includes(removedStep2Token) || html.includes(removedStep2Token) || css.includes(removedStep2Token)) {
    throw new Error(`legacy Step 2 editor still present: ${removedStep2Token}`);
  }
}
if (app.includes("group.id === 'body_group_02'")) {
  throw new Error('legacy hard-coded visual group filtering is still present');
}
if (!html.includes('step3-btn-batch-generate')) throw new Error('step 3 batch image generation action missing');
if (!background.includes('step3-btn-background-settings')) throw new Error('Step 3 final video background entry missing');
if (html.includes('step3-video-background-apply') || background.includes('step3-video-background-apply')) {
  throw new Error('obsolete video background apply button is still present');
}
if (!background.includes('铺满画面') || !background.includes('完整显示')) throw new Error('video background fit modes missing');
for (const backgroundMode of ['data-mode-card="image"', 'data-mode-card="solid"', 'aspect-ratio:16 / 9', '16:9 预览']) {
  if (!background.includes(backgroundMode)) throw new Error(`final background modal contract missing: ${backgroundMode}`);
}
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
for (const removedImageStyleToken of [
  'btn-image-style-ai-draft',
  'image-style-ai-requirement',
  'image-style-ai-draft-preview',
  'image-style-use-advanced',
  'image-style-validation-status',
  'image-style-keywords',
  'image-style-visual-style',
  'image-style-diagram-style',
  'image-style-layout-rules',
  'image-style-avoid',
  'generateImageStyleAiDraft',
  'validateImageStyleYaml',
  'image-style/ai-draft',
  '.ai-draft-preview',
  '.ai-request-panel',
]) {
  if (app.includes(removedImageStyleToken) || html.includes(removedImageStyleToken) || css.includes(removedImageStyleToken)) {
    throw new Error(`legacy image style editor still present: ${removedImageStyleToken}`);
  }
}
if (!app.includes('visual_description') || !css.includes('.mask-visual-card')) {
  throw new Error('Mask semantic visual description display is missing');
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
for (const manualMaskControl of ['step5-brush-size', 'step5-eraser-size', 'step5-btn-new-block', 'step5-btn-clear-current']) {
  if (!html.includes(manualMaskControl)) throw new Error(`manual Mask fallback control missing: ${manualMaskControl}`);
}
if (!html.includes('id="step5-brush-size" type="range" min="100" max="200" value="140"')) {
  throw new Error('brush size contract must be 100-200 with a 140 default');
}
if (!html.includes('id="step5-eraser-size" type="range" min="100" max="200" value="100"')) {
  throw new Error('eraser size contract must be 100-200 with a 100 default');
}
if (!html.includes('step5-tool-cursor') || !app.includes('toolSize * canvasRect.width / 1920')) {
  throw new Error('Mask tool cursor does not track the real canvas pixel diameter');
}
if (!app.includes('const MASK_PREVIEW_OUTLINE_PX = 5') || !app.includes('buildMaskDisplayLayer')) {
  throw new Error('same-color 5px Mask preview outline is missing');
}
for (const manualMaskHandler of ['startMaskPaint', 'startMaskErase', 'deleteMaskBox', 'beginMaskStroke']) {
  if (!app.includes(manualMaskHandler)) throw new Error(`manual Mask fallback handler missing: ${manualMaskHandler}`);
}
if (!aiMask.includes('maybeAutoAnnotate') || !aiMask.includes('multimodal') && !aiMask.includes('AI 正在关联')) {
  throw new Error('automatic AI Mask flow is missing');
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
if (!styleManager.includes('window.refreshStep3Prompts')) {
  throw new Error('image style changes do not refresh prompts');
}
for (const token of ['step1-mode-article', 'step1-mode-topic', 'step1-btn-generate-article', 'step1-btn-system-content']) {
  if (!html.includes(token)) throw new Error(`Step 1 dual-mode UI missing: ${token}`);
}
for (const label of ['文章➡️slides', 'slides➡️可视化']) {
  if (!html.includes(label)) throw new Error(`Step 2 button label missing: ${label}`);
}
if (!app.includes("rle.encoding === 'row_runs_v1'") || !app.includes('exactRuns.forEach')) {
  throw new Error('exact RLE Mask preview support missing');
}
if (html.includes('请在下方粘贴您的 Markdown 格式文章')) throw new Error('obsolete Step 1 top hint is still present');
for (const script of ['project_profile_extension.js', 'storyboard_background_extension.js', 'style_reference_manager_extension.js', 'ai_mask_extension.js', 'one_click_extension.js']) {
  if (!html.includes(script)) throw new Error(`direct frontend script declaration missing: ${script}`);
}
if (!styleManager.includes('style-panel-template-name') || !styleManager.includes('最多只能上传 3 张')) {
  throw new Error('named image-style templates or three-image limit missing');
}
for (const styleMode of ['data-style-tab="template"', 'data-style-tab="manual"', 'data-style-tab="reverse"']) {
  if (!styleManager.includes(styleMode)) throw new Error(`image-style mode missing: ${styleMode}`);
}
if (!styleManager.includes('aspect-ratio:16 / 9') || !styleManager.includes('这 3 张效果预览会作为后续图片生成的实际参考图')) {
  throw new Error('image-style System Content / 16:9 reference output contract missing');
}
if (styleManager.includes('visual-draft-quality') || oneClick.includes('图片质量检查')) {
  throw new Error('removed image quality feature is still user-visible');
}
if (!oneClick.includes('button-spinner')) throw new Error('one-click stage spinner missing');
if (!oneClick.includes('one-click-sidebar-entry') || !oneClick.includes('stepper.appendChild(entry)')) {
  throw new Error('one-click button is not anchored directly below the video step');
}
if (!app.includes("document.body.classList.add('workspace-open')") || !css.includes('body.workspace-open #toast-container')) {
  throw new Error('workspace notifications can still overlap the sidebar action');
}
if (!html.includes('sidebar-flow-title') || !html.includes('step-complete') || !css.includes('.sidebar .step-icon svg')) {
  throw new Error('workflow rail redesign is incomplete');
}
if (!css.includes('#step6-btn-audio-confirm-next:disabled') || !css.includes('#step8-btn-render:disabled')) {
  throw new Error('disabled primary button contrast contract is missing');
}
if (!app.includes('narrationDedupeKey') || !app.includes('uniqueNarrationLines')) {
  throw new Error('frontend narration deduplication guard is missing');
}

console.log('frontend quality checks passed');
