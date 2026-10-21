// Real Chromium regression checks. API calls are mocked; no live projects or providers are touched.
// Run with playwright available on NODE_PATH (the Codex bundled runtime supplies it).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..', 'static');

async function main() {
  const server = http.createServer((req, res) => {
    const relative = decodeURIComponent(new URL(req.url, 'http://localhost').pathname).replace(/^\/+/, '') || 'index.html';
    const target = path.resolve(root, relative);
    if (!target.startsWith(root + path.sep) || !fs.existsSync(target) || !fs.statSync(target).isFile()) {
      res.writeHead(404).end(); return;
    }
    const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png' };
    res.setHeader('Content-Type', types[path.extname(target)] || 'application/octet-stream');
    res.end(fs.readFileSync(target));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.PPT_STUDIO_TEST_BROWSER || chromium.executablePath() });
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.hostname !== '127.0.0.1') return route.abort();
      if (!url.pathname.startsWith('/api/')) return route.continue();
      const response = { success: true, projects: [], accounts: [], packages: [], configs: [], models: [], settings: {}, active: false };
      await route.fulfill({ json: response });
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/index.html`);
    await page.evaluate(() => {
      document.body.classList.add('workspace-open');
      document.getElementById('page-home').style.display = 'none';
      document.getElementById('page-workspace').style.display = 'flex';
      state.currentProject = { id: 'fixture-project', ai_mode: 'manual', current_step: 3, step_status: {} };
      applyProjectAiMode('manual');
      document.querySelectorAll('.step-panel').forEach(node => { node.style.display = 'none'; });
      document.getElementById('step-panel-3').style.display = 'block';
      state.slides = [];
      resetStep3ProjectState();
      renderStep3Grid();
    });
    for (const id of ['step3-btn-background-settings', 'step3-btn-delete-all-images', 'step3-btn-image-style-panel']) {
      assert.equal(await page.locator(`#${id}`).count(), 1);
      assert.equal(await page.locator(`#${id}`).evaluate(node => node.parentElement.classList.contains('workflow-toolbar')), true);
    }
    // Saving an A modal after switching to B must issue no background writes.
    await page.evaluate(() => {
      window.backgroundWrites = [];
      window.backgroundOriginalPut = API.put;
      API.put = async (url, body) => {
        window.backgroundWrites.push({ url, body });
        return { background: {} };
      };
      state.currentProject = { id: 'project-A' };
    });
    await page.locator('#step3-btn-background-settings').click();
    await page.waitForFunction(() => document.getElementById('modal-storyboard-background')?.dataset.projectId === 'project-A');
    await page.evaluate(() => { state.currentProject = { id: 'project-B' }; });
    await page.locator('#btn-storyboard-bg-save').click();
    assert.equal(await page.evaluate(() => window.backgroundWrites.length), 0);
    await page.locator('#step3-btn-background-settings').click();
    await page.waitForFunction(() => document.getElementById('modal-storyboard-background')?.dataset.projectId === 'project-B');
    await page.locator('#btn-storyboard-bg-save').click();
    await page.waitForFunction(() => window.backgroundWrites.length === 2);
    assert.equal(await page.evaluate(() => window.backgroundWrites.every(call => call.url.includes('/project-B/'))), true);
    await page.evaluate(() => {
      API.put = window.backgroundOriginalPut;
      state.currentProject = { id: 'fixture-project', ai_mode: 'manual', current_step: 3, step_status: {} };
    });
    assert.match(await page.locator('#step3-images-grid').innerText(), /请先完成第 2 步/);
    await page.evaluate(async () => {
      const original = API.getOptional;
      API.getOptional = async () => ({ success: false });
      await loadStep3Data();
      API.getOptional = original;
    });
    assert.match(await page.locator('#step3-images-grid').innerText(), /返回分镜规划/);
    await page.evaluate(async () => {
      state.slides = [{ slide_id: 's1', main_title: '标题' }];
      const original = API.get;
      API.get = async () => { throw new Error('测试网络中断'); };
      await loadStep3Data();
      API.get = original;
    });
    assert.match(await page.locator('#step3-images-grid').innerText(), /测试网络中断/);
    assert.equal(await page.getByRole('button', { name: '重新加载', exact: true }).count(), 1);

    await page.evaluate(() => {
      window.navigationCalls = [];
      navigateToStepForReview = step => window.navigationCalls.push(step);
    });
    const firstStep = page.locator('.step-item').first();
    await firstStep.focus();
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    assert.deepEqual(await page.evaluate(() => window.navigationCalls), [2]);

    await page.evaluate(() => {
      document.getElementById('step-panel-3').style.display = 'none';
      document.getElementById('step-panel-2').style.display = 'block';
      state.slides = [{ slide_id: 's1', main_title: '', narration_text: '' }];
      state.activeSlideIndex = 0;
      renderStep2Workspace();
      showStep2ValidationError('第 1 页标题不能为空', 0, 'title');
    });
    assert.equal(await page.locator('#step2-slide-title-input').getAttribute('aria-invalid'), 'true');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'step2-slide-title-input');
    await page.locator('#step2-slide-title-input').fill('修正后的标题');
    assert.equal(await page.locator('#step2-slide-title-input').getAttribute('aria-invalid'), null);

    const opener = page.locator('#step2-btn-add-slide');
    await opener.focus();
    await page.evaluate(() => { window.decision = confirmAction('测试确认', '删除需要确认'); });
    await page.waitForFunction(() => document.activeElement.id === 'btn-confirm-no');
    await page.keyboard.press('Shift+Tab');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'btn-confirm-yes');
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'btn-confirm-no');
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => window.decision), false);
    await page.waitForFunction(() => document.activeElement.id === 'step2-btn-add-slide');
    assert.equal(await page.locator('#page-workspace').evaluate(node => node.inert), false);

    await page.evaluate(() => {
      window.decisions = [confirmAction('第一项', '第一项'), confirmAction('第二项', '第二项')];
    });
    await page.waitForFunction(() => document.getElementById('confirm-title').textContent === '第一项');
    await page.locator('#btn-confirm-yes').click();
    await page.waitForFunction(() => document.getElementById('confirm-title').textContent === '第二项');
    assert.equal(await page.locator('#btn-confirm-yes').isEnabled(), true);
    await page.keyboard.press('Escape');
    assert.deepEqual(await page.evaluate(() => Promise.all(window.decisions)), [true, false]);

    await page.evaluate(() => { window.nameInput = requestTextInput('模板名称', '名称', ''); });
    await page.getByRole('button', { name: '保存', exact: true }).last().click();
    assert.match(await page.locator('.modal-overlay:visible').innerText(), /名称不能为空/);
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => window.nameInput), null);
    assert.equal(errors.filter(message => /insertBefore|NotFoundError/.test(message)).length, 0);
    // Actual multi-character controls reuse OCR IDs and preserve an unbound
    // draft. Job cancellation remains pending until a terminal server state.
    await page.evaluate(() => {
      document.querySelectorAll('.step-panel').forEach(node => { node.style.display = 'none'; });
      document.getElementById('step-panel-10').style.display = 'block';
      state.currentProject = {id: 'fixture-project', step_status: {}};
      state.currentStep = 10;
      ANNOTATIONS_WS.projectId = 'fixture-project';
      ANNOTATIONS_WS.page = {slide_id: 's1', revision: 0, items: [], imageHash: 'fixture-image', narration: {beats: [{beat_id: 'b1', spoken_text: '重点词'}]}};
      renderAnnotationMissingState();
      ANNOTATIONS_WS.candidates = ['重', '点', '词'].map((text, i) => ({
        text, token_id: `t${i}`, line_id: 'l', granularity: 'char',
        polygon: [[100 + i * 30, 100], [125 + i * 30, 100], [125 + i * 30, 140], [100 + i * 30, 140]],
      }));
      renderAnnotationCandidates();
    });
    await page.locator('#annotation-candidate-multi').click();
    await page.locator('[data-token-id="t0"]').click();
    await page.locator('[data-token-id="t2"]').click({modifiers: ['Shift']});
    assert.match(await page.locator('#annotation-candidate-add').innerText(), /3/);
    await page.locator('#annotation-candidate-add').click();
    assert.deepEqual(await page.evaluate(() => ANNOTATIONS_WS.page.items[0].target.token_ids), ['t0', 't1', 't2']);
    await page.evaluate(() => {
      ANNOTATIONS_WS.activeJob = {projectId: 'fixture-project', jobId: 'job-ui', operation: 'plan', startedAt: Date.now() - 5000};
      window.cancelWrites = [];
      API.post = async url => { window.cancelWrites.push(url); return {cancelled: true}; };
      renderAnnotationJobProgress('plan', 'job-ui', 'running', 5);
    });
    assert.match(await page.locator('#annotation-job-status').innerText(), /已用时/);
    await page.locator('#annotation-btn-cancel-job').click();
    assert.match(await page.locator('#annotation-job-status').innerText(), /正在取消/);
    assert.equal(await page.evaluate(() => window.cancelWrites[0]), '/api/projects/fixture-project/annotations/jobs/job-ui/cancel');
    await page.evaluate(() => { ANNOTATIONS_WS.activeJob = null; renderAnnotationJobProgress('plan', 'job-ui', 'cancelled', 5); });
    assert.equal(await page.locator('#annotation-btn-cancel-job').isVisible(), false);
    if (errors.length) throw new Error(`Browser errors: ${errors.join('\n')}`);
    console.log('workspace UX Chromium checks passed');
  } finally {
    await browser?.close();
    await new Promise(resolve => server.close(resolve));
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
