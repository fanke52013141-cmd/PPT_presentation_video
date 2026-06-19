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
if (!app.includes('await refreshStep3Images();')) throw new Error('step 3 does not wait for image state');
if (!app.includes('confirmBtn.disabled = !allImagesReady')) throw new Error('step 3 confirmation is not gated');
if (!app.includes('step5AutoSavePromise')) throw new Error('step 5 save serialization missing');
if (!app.includes('refreshStep3Prompts({ updateOpenEditor: state.currentStep === 3 })')) {
  throw new Error('image style changes do not refresh prompts');
}

console.log('frontend quality checks passed');
