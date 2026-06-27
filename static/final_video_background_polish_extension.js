(function () {
  'use strict';

  function moveBackgroundButton() {
    const button = document.getElementById('step2-btn-background-settings');
    const toolbar = document.querySelector('#step-panel-2 .step2-sticky-header > div > div') || document.querySelector('#step-panel-2 .step2-sticky-header div[style*="align-items"] div');
    if (!button || !toolbar) return;
    button.textContent = '最终视频背景';
    button.title = '只影响最终视频合成背景；Step 3 生图仍保持纯白底。';
    const storyboardSettings = document.getElementById('step2-btn-storyboard-settings');
    if (storyboardSettings && storyboardSettings.parentElement === toolbar && storyboardSettings.nextSibling !== button) {
      toolbar.insertBefore(button, storyboardSettings.nextSibling);
    }
  }

  function addModalBoundaryNote() {
    const modal = document.getElementById('modal-storyboard-background');
    if (!modal || modal.querySelector('.final-video-bg-boundary-note')) return;
    const title = modal.querySelector('.highlight-title');
    if (!title) return;
    const note = document.createElement('div');
    note.className = 'final-video-bg-boundary-note';
    note.style.cssText = 'border:1.5px dashed #111;border-radius:10px;padding:.55rem .7rem;margin:.55rem 0 .8rem;background:#fff;font-size:.86rem;line-height:1.5;color:#444;';
    note.innerHTML = '<strong>边界说明：</strong>这里只设置最终视频背景。Step 3 的 visual_draft.png 仍然必须是纯白背景，不能把复杂背景画进生图。';
    title.insertAdjacentElement('afterend', note);
  }

  function boot() {
    moveBackgroundButton();
    addModalBoundaryNote();
  }

  const timer = setInterval(boot, 700);
  setTimeout(() => clearInterval(timer), 15000);
  document.addEventListener('DOMContentLoaded', boot);
})();
