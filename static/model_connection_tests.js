// Saved-model output tests. Results are kept per configuration for this page session.
(function () {
  'use strict';
  const results = new Map();
  const running = new Set();
  let activeKey = null;
  let dialog = null;
  const inputs = { text: '两个字回复我', image: '生成一只猫咪', tts: '你好' };
  const keyFor = connection => `${connection.id}:${connection.updated_at}:${JSON.stringify(connection.revision)}`;

  function ensureDialog() {
    if (dialog) return dialog;
    dialog = document.createElement('div');
    dialog.id = 'modal-model-output-test';
    dialog.className = 'modal-overlay';
    dialog.style.display = 'none';
    dialog.innerHTML = '<div class="modal-content model-test-panel" role="dialog" aria-modal="true" aria-labelledby="model-test-title">'
      + '<div class="modal-header-row"><h3 id="model-test-title">模型返回测试</h3>'
      + '<button id="model-test-close" class="icon-button" type="button" data-modal-close aria-label="关闭">×</button></div>'
      + '<p class="model-test-input"></p><div class="model-test-output" aria-live="polite"></div>'
      + '<p class="config-editor-note">每次测试都会重新请求模型。结果反映本次请求的状态。</p></div>';
    const close = () => {
      dialog.querySelector('audio')?.pause();
      dialog.style.display = 'none';
    };
    dialog.querySelector('[data-modal-close]').addEventListener('click', close);
    dialog.addEventListener('click', event => { if (event.target === dialog) close(); });
    document.body.append(dialog);
    return dialog;
  }

  function renderResult(connection) {
    const key = keyFor(connection);
    if (activeKey !== key) return;
    ensureDialog();
    dialog.querySelector('#model-test-title').textContent = `模型返回测试 · ${connection.name}`;
    dialog.querySelector('.model-test-input').textContent = `测试输入：${inputs[connection.kind]}`;
    const output = dialog.querySelector('.model-test-output');
    output.replaceChildren();
    output.setAttribute('aria-busy', String(running.has(key)));
    const status = document.createElement('p');
    const result = results.get(key);
    if (running.has(key)) {
      status.textContent = '正在等待模型返回… 图片和语音生成可能需要几分钟，可以关闭弹窗，稍后查看结果。';
      output.append(status);
      return;
    }
    status.className = result?.success ? 'model-test-success' : 'model-test-error';
    status.textContent = result?.message || '未取得测试结果';
    output.append(status);
    if (!result?.success) return;
    if (result.kind === 'text') {
      const text = document.createElement('pre');
      text.textContent = result.text;
      output.append(text);
    } else if (result.kind === 'image' && result.media_data_url?.startsWith('data:image/png;base64,')) {
      const image = document.createElement('img');
      image.src = result.media_data_url;
      image.alt = '模型根据“生成一只猫咪”返回的图片';
      output.append(image);
    } else if (result.kind === 'tts' && /^data:audio\/(mpeg|wav|ogg);base64,/.test(result.media_data_url || '')) {
      const audio = document.createElement('audio');
      audio.controls = true;
      audio.src = result.media_data_url;
      audio.setAttribute('aria-label', '模型合成的“你好”语音');
      output.append(audio);
    }
    const timing = document.createElement('p');
    timing.className = 'config-editor-note';
    timing.textContent = `本次耗时 ${result.elapsed_sec} 秒`;
    output.append(timing);
  }

  function refreshButtons(key) {
    document.querySelectorAll('.model-test-action').forEach(button => {
      if (button.dataset.testKey !== key) return;
      const pending = running.has(key);
      button.setAttribute('aria-busy', String(pending));
      button.classList.toggle('is-testing', pending);
      // Clicking during a pending request reopens its status, without a second request.
    });
    document.querySelectorAll('.model-test-view').forEach(button => {
      if (button.dataset.testKey === key) button.disabled = !results.has(key) || running.has(key);
    });
  }

  async function run(connection) {
    const key = keyFor(connection);
    activeKey = key;
    ensureDialog().style.display = 'flex';
    if (running.has(key)) { renderResult(connection); return; }
    running.add(key);
    results.delete(key);
    renderResult(connection);
    refreshButtons(key);
    try {
      results.set(key, await window.API.post(`/api/model-connections/${encodeURIComponent(connection.id)}/test`, {},
        { timeoutMs: 1100000, silent: true }));
    } catch (error) {
      results.set(key, { success: false, message: `测试失败：${error.message || error}` });
    } finally {
      running.delete(key);
      renderResult(connection);
      refreshButtons(key);
    }
  }

  function createButton(connection) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'cc-icon-action model-test-action';
    button.dataset.testKey = keyFor(connection);
    button.title = `测试模型“${connection.name}”是否能成功返回`;
    button.setAttribute('aria-label', button.title);
    button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7z"></path></svg>';
    button.classList.toggle('is-testing', running.has(keyFor(connection)));
    button.setAttribute('aria-busy', String(running.has(keyFor(connection))));
    button.addEventListener('click', () => run(connection));
    const view = document.createElement('button');
    view.type = 'button';
    view.className = 'cc-icon-action model-test-view';
    view.dataset.testKey = keyFor(connection);
    view.title = `查看“${connection.name}”本次测试结果`;
    view.setAttribute('aria-label', view.title);
    view.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6M8 13h8M8 17h6"></path></svg>';
    view.disabled = !results.has(keyFor(connection)) || running.has(keyFor(connection));
    view.addEventListener('click', () => {
      activeKey = keyFor(connection);
      ensureDialog().style.display = 'flex';
      renderResult(connection);
    });
    const fragment = document.createDocumentFragment();
    fragment.append(button, view);
    return fragment;
  }
  function mountEditorActions(connection) {
    const target = document.getElementById('model-test-editor-actions');
    if (!target) return;
    target.replaceChildren();
    target.hidden = !connection;
    if (connection) target.append(createButton(connection));
  }
  window.PPTModelTests = { mountEditorActions };
})();
