const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'static', 'index.html'), 'utf8');
const editor = fs.readFileSync(path.join(root, 'static', 'mask_editor.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'static', 'style.css'), 'utf8');

if (!html.includes('id="step5-zoom-stage"')) {
  throw new Error('Mask zoom stage is missing from the canvas markup');
}
if (!editor.includes("const stage = document.getElementById('step5-zoom-stage')")) {
  throw new Error('Mask zoom must use the shared zoom stage');
}
if (!editor.includes("stage.style.transform = zoom === 1 ? 'none' : `scale(${zoom})`")) {
  throw new Error('Mask zoom stage does not receive the scale transform');
}
if (!editor.includes('const point = getCanvasCoords(e, canvas);')) {
  throw new Error('Mask zoom origin is not derived from the stable canvas coordinates');
}
if (!editor.includes('wrapper.clientLeft + stage.offsetLeft') || !editor.includes('/ zoom + originX')) {
  throw new Error('Mask pointer coordinates do not invert the transformed stage geometry');
}
if (!editor.includes('if (state.canvasState.maskFullscreen)') || !editor.includes('stage.style.transform = zoom === 1 ? \'none\'')) {
  throw new Error('Fullscreen Mask mode must force a 1:1, untransformed canvas');
}
if (!editor.includes('function syncMaskCanvasViewport') || !editor.includes('canvas.style.width = px(width)')) {
  throw new Error('Mask Canvas is not being matched to the image visible rectangle');
}
if (!css.includes('.step5-zoom-stage {')) {
  throw new Error('Mask zoom stage CSS is missing');
}
if (/\[bg, canvas\]\.forEach\(el => \{\s*el\.style\.transform = transform/s.test(editor)) {
  throw new Error('Mask background and canvas are still scaled independently');
}
if (editor.includes('MASK_PREVIEW_OUTLINE_PX') || editor.includes('outlineMaskCtx')) {
  throw new Error('Mask display still adds an artificial outline around painted pixels');
}
if (!/\.step5-tool-cursor\s*\{[^}]*border:\s*0;/s.test(css)) {
  throw new Error('Brush cursor still has an extra visible border');
}
if (!css.includes('body.step5-fullscreen-mode #step5-zoom-stage')) {
  throw new Error('Fullscreen CSS does not guard the Mask stage against nested transforms');
}
if (css.includes('body.step5-fullscreen-mode #canvas-container canvas,body.step5-fullscreen-mode #canvas-container img')) {
  throw new Error('Fullscreen CSS still forces Canvas to fill the wrapper instead of the visible image');
}

console.log('mask zoom coordinate checks passed');
