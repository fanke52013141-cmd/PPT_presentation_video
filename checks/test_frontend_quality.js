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
if (!html.includes('step3-btn-batch-generate')) throw new Error('step 3 batch image generation action missing');
if (!html.includes('step3-video-background-color') || !html.includes('step3-video-background-text')) {
  throw new Error('project video background color controls missing');
}
if (!html.includes('step3-video-background-apply')) throw new Error('video background apply button missing');
if (!app.includes('saveStep3VideoBackground')) throw new Error('video background color save handler missing');
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
if (!html.includes('id="step5-brush-size"') || !html.includes('value="170"')) {
  throw new Error('brush size control or 170 default missing');
}
if (!html.includes('id="step5-eraser-size"') || !html.includes('value="120"')) {
  throw new Error('separate eraser size control or 120 default missing');
}
if (!app.includes('getActiveMaskToolSize')) throw new Error('brush and eraser sizes are not selected by tool');
if (!app.includes("newCanvas.addEventListener('pointerdown'")) {
  throw new Error('mask editor does not use pointer capture capable input events');
}
if (!app.includes('pointerWithinMaskToolReach')) {
  throw new Error('mask editor has no outside-edge interaction allowance');
}
if (!html.includes('step5-live-coverage')) throw new Error('live mask coverage status missing');
if (!app.includes('rebuildStep5SourceCache')) throw new Error('source foreground cache missing');
if (!app.includes('buildStep5UnionMask')) throw new Error('exact live mask union missing');
if (!app.includes("redWarningCtx.fillStyle = 'rgba(255, 59, 48, 0.04)'")) {
  throw new Error('uncovered foreground does not use a readable light tint');
}
if (!app.includes('createStep5UncoveredPattern')) {
  throw new Error('uncovered foreground hatch pattern missing');
}
if (!app.includes('ctx.drawImage(step5SourceCanvas, 0, 0)')) {
  throw new Error('mask editor does not keep the full source visible');
}
if (!app.includes('红色内容不会进入视频')) throw new Error('mask omission guidance missing');
if (!app.includes('if (!state.canvasState.coverageReady)')) {
  throw new Error('frontend mask coverage confirmation gate missing');
}
if (!app.includes('result.all_can_confirm !== false')) {
  throw new Error('frontend confirmation is not gated by every slide');
}
if (!html.includes('step5-foreground-mask-img')) {
  throw new Error('server-generated foreground mask image missing');
}
if (!app.includes('refreshStep3Prompts({ updateOpenEditor: state.currentStep === 3 })')) {
  throw new Error('image style changes do not refresh prompts');
}

console.log('frontend quality checks passed');
