(function () {
  'use strict';

  const MODAL_ID = 'modal-step2-storyboard-settings';

  function toast(message, duration) {
    if (window.showToast) window.showToast(message, duration || 3000);
    else console.log(message);
  }

  function ensureStyle() {
    if (document.getElementById('step2-storyboard-settings-style')) return;
    const style = document.createElement('style');
    style.id = 'step2-storyboard-settings-style';
    style.textContent = `
      #step2-btn-storyboard-settings { font-size: .85rem; padding: .35rem .9rem; }
      #step2-btn-script-prompt, #step2-btn-visual-prompt { display: none !important; }
      .step2-storyboard-settings-modal { max-width: 860px; width: min(860px, 94vw); }
      .step2-storyboard-note { color: #555; font-size: .9rem; line-height: 1.55; margin: .35rem 0 .9rem; }
      .step2-storyboard-warning { background: #fff8dc; border-left: 4px solid #d6a100; padding: .7rem .85rem; margin: .7rem 0 1rem; line-height: 1.5; font-size: .9rem; }
      .step2-storyboard-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .8rem; margin: 1rem 0; }
      .step2-storyboard-action { border: 2px solid #111; border-radius: 14px; background: #fffef9; padding: .85rem; cursor: pointer; text-align: left; box-shadow: 2px 2px 0 rgba(0,0,0,.12); }
      .step2-storyboard-action:hover { transform: translateY(-1px); }
      .step2-storyboard-action strong { display: block; font-size: .98rem; margin-bottom: .3rem; }
      .step2-storyboard-action span { display: block; color: #555; font-size: .86rem; line-height: 1.5; }
      .step2-storyboard-flow { border: 1.5px dashed #111; border-radius: 12px; padding: .75rem; background: #fff; color: #444; font-size: .88rem; line-height: 1.55; }
      @media (max-width: 760px) { .step2-storyboard-actions { grid-template-columns: 1fr; } }
    `;
    document.head.appendChild(style);
  }

  function ensureModal() {
    if (document.getElementById(MODAL_ID)) return;
    const modal = document.createElement('div');
    modal.id = MODAL_ID;
    modal.className = 'modal';
    modal.style.display = 'none';
    modal.innerHTML = `
      <div class="modal-content step2-storyboard-settings-modal">
        <h3 class="highlight-title">Step 2 分镜设置</h3>
        <p class="step2-storyboard-note">分镜风格只属于 Step 2。这里控制文章如何拆成 Slides，以及每页如何转换成视觉规划；不再通过项目创建或 Project Profile 设置。</p>
        <div class="step2-storyboard-warning"><strong>流程边界：</strong>Step 2 负责分镜结构和视觉规划；Step 3 才负责图片风格、参考图和以图定风格。</div>
        <div class="step2-storyboard-actions">
          <button id="btn-step2-open-script-prompt" class="step2-storyboard-action" type="button">
            <strong>文章转分镜提示词</strong>
            <span>控制文章如何拆页、每页讲什么、叙事节奏和页面数量。等价于旧按钮“文章 2slide”。</span>
          </button>
          <button id="btn-step2-open-visual-prompt" class="step2-storyboard-action" type="button">
            <strong>分镜转视觉规划提示词</strong>
            <span>控制每页需要哪些视觉元素、元素与旁白如何绑定、后续 Mask 语块如何组织。等价于旧按钮“slide 2visualization”。</span>
          </button>
        </div>
        <div class="step2-storyboard-flow">
          推荐流程：先调整“文章转分镜提示词”，再调整“分镜转视觉规划提示词”，最后点击“AI 生成分镜”。生成后的图片风格不要在这里调整，去 Step 3 的“图片风格”。
        </div>
        <div class="config-editor-actions" style="margin-top:1rem">
          <button id="btn-step2-storyboard-settings-close" class="secondary" type="button">关闭</button>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.addEventListener('click', event => {
      if (event.target === modal) closeModal();
    });
    document.getElementById('btn-step2-storyboard-settings-close')?.addEventListener('click', closeModal);
    document.getElementById('btn-step2-open-script-prompt')?.addEventListener('click', () => clickOriginal('step2-btn-script-prompt'));
    document.getElementById('btn-step2-open-visual-prompt')?.addEventListener('click', () => clickOriginal('step2-btn-visual-prompt'));
  }

  function clickOriginal(id) {
    const button = document.getElementById(id);
    if (!button) {
      toast('原始提示词编辑入口还没有加载完成，请稍后再试。', 4000);
      return;
    }
    closeModal();
    button.click();
  }

  function openModal() {
    ensureModal();
    document.getElementById(MODAL_ID).style.display = 'flex';
  }

  function closeModal() {
    const modal = document.getElementById(MODAL_ID);
    if (modal) modal.style.display = 'none';
  }

  function ensureButton() {
    ensureStyle();
    ensureModal();
    const toolbar = document.querySelector('#step-panel-2 .step2-sticky-header > div > div');
    if (!toolbar || document.getElementById('step2-btn-storyboard-settings')) return;
    const button = document.createElement('button');
    button.id = 'step2-btn-storyboard-settings';
    button.className = 'secondary';
    button.type = 'button';
    button.textContent = '分镜设置';
    button.addEventListener('click', openModal);
    const generate = document.getElementById('step2-btn-generate');
    if (generate?.parentElement === toolbar) toolbar.insertBefore(button, generate.nextSibling);
    else toolbar.appendChild(button);
  }

  function boot() {
    ensureStyle();
    ensureModal();
    ensureButton();
    const timer = setInterval(ensureButton, 700);
    setTimeout(() => clearInterval(timer), 15000);
  }

  document.addEventListener('DOMContentLoaded', boot);
  if (document.readyState !== 'loading') boot();
})();
