// DOM startup and page-level event registration.
// Load this after every core workflow module so all handlers exist before DOMContentLoaded.

function navigateToStepForReview(step) {
  return navigateToStep(step);
}

// 首次加载初始化
document.addEventListener('DOMContentLoaded', () => {
  initGlobalEvents();
  initAnnotationWorkspaceEvents();
  initAccountManagement?.();
  loadAccounts?.();
  loadProjects();
  loadSettings();
});

// 初始化全局页面级事件监听
function initGlobalEvents() {
  initModalAccessibility();
  initGenerationControls();
  document.addEventListener('generation-finished', event => {
    if (event.detail.projectId === state.currentProject?.id && event.detail.kind === 'tts'
        && state.currentStep === 6) loadStep7Data().catch(() => {});
  });
  // Buttons keep their visible label or aria-label, without native hover explanations.
  document.addEventListener('pointerover', event => {
    const button = event.target.closest?.('button, [role="button"]');
    if (button?.hasAttribute('title')) {
      if (!button.getAttribute('aria-label') && !button.textContent.trim()) {
        button.setAttribute('aria-label', button.getAttribute('title'));
      }
      button.removeAttribute('title');
    }
  }, true);
  document.addEventListener('click', event => {
    const helpButton = event.target.closest('[data-prompt-help]');
    if (helpButton) openPromptIOHelp(helpButton.dataset.promptHelp);
  });
  // 弹窗统一右上角 × 关闭（UI 审查 2026-10-06）：只隐藏弹层，不改动各弹窗自己的关闭函数。
  document.addEventListener('click', event => {
    const closeButton = event.target.closest('[data-modal-close]');
    if (!closeButton) return;
    const overlay = closeButton.closest('.modal-overlay');
    if (overlay) overlay.style.display = 'none';
  });
  // 项目画像向导会在运行时重写 #modal-create 的弹窗体，用观察器保证 × 常驻。
  const createModal = document.getElementById('modal-create');
  if (createModal) {
    const ensureCornerClose = () => {
      const content = createModal.querySelector('.modal-content');
      if (content && !content.querySelector('[data-modal-close]')) {
        const cornerClose = document.createElement('button');
        cornerClose.type = 'button';
        cornerClose.className = 'modal-corner-close';
        cornerClose.setAttribute('data-modal-close', '');
        cornerClose.setAttribute('aria-label', '关闭');
        cornerClose.textContent = '×';
        (content.querySelector('.project-profile-scroll') || content).prepend(cornerClose);
      }
    };
    ensureCornerClose();
    new MutationObserver(ensureCornerClose).observe(createModal, { childList: true, subtree: true });
  }

  // 顶栏按钮
  document.getElementById('btn-open-settings')?.addEventListener('click', () => openSettingsModal());
  document.getElementById('btn-settings-cancel')?.addEventListener('click', () => closeSettingsModal());
  document.getElementById('btn-settings-save')?.addEventListener('click', () => saveSettings());
  document.getElementById('system-settings-open-models')?.addEventListener('click', () => {
    closeSettingsModal();
    window.openModelManagement?.();
  });
  document.getElementById('system-settings-open-configs')?.addEventListener('click', () => {
    closeSettingsModal();
    window.openCreationConfigManagement?.();
  });
  document.getElementById('btn-settings-export')?.addEventListener('click', () => exportGlobalSettings());
  document.getElementById('btn-settings-import')?.addEventListener('click', () => {
    document.getElementById('settings-import-file')?.click();
  });
  document.getElementById('btn-config-export')?.addEventListener('click', () => exportGlobalSettings());
  document.getElementById('btn-config-import')?.addEventListener('click', () => {
    document.getElementById('settings-import-file')?.click();
  });
  document.getElementById('settings-import-file')?.addEventListener('change', (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) importGlobalSettings(file);
  });
  document.getElementById('btn-back-home')?.addEventListener('click', () => exitWorkspace());
  document.getElementById('btn-ai-mode-auto')?.addEventListener('click', () => setProjectAiMode('auto'));
  document.getElementById('btn-ai-mode-manual')?.addEventListener('click', () => setProjectAiMode('manual'));
  // 绑定设置测试连通性按钮
  document.getElementById('btn-test-llm')?.addEventListener('click', () => testLlmConnection());
  document.getElementById('btn-test-image')?.addEventListener('click', () => testImageConnection());
  document.getElementById('btn-test-tts')?.addEventListener('click', () => testTtsConnection());
  // This module owns the creation-config/model-connection panel listeners;
  // keeping the registration here preserves one shared DOM startup entry.
  window.initCreationConfigManagementEvents?.();
  
  // 新建项目 Modal
  document.getElementById('btn-create-project')?.addEventListener('click', () => {
    document.getElementById('input-project-name').value = '';
    document.getElementById('input-project-desc').value = '';
    loadCreationConfigs();
    document.getElementById('modal-create').style.display = 'flex';
  });
  document.getElementById('btn-create-cancel')?.addEventListener('click', () => {
    document.getElementById('modal-create').style.display = 'none';
  });
  document.getElementById('btn-create-submit')?.addEventListener('click', () => createProject());

  // 设置面板 Tab 切换
  const tabs = document.querySelectorAll('#modal-settings .tab-item');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      document.querySelectorAll('#modal-settings .tab-pane').forEach(p => p.style.display = 'none');
      document.getElementById(tab.dataset.tab).style.display = 'block';
    });
  });

  // 步骤条点击导航
  const stepItems = document.querySelectorAll('.step-item');
  stepItems.forEach(item => {
    item.setAttribute('role', 'button');
    item.tabIndex = 0;
    item.addEventListener('keydown', event => {
      if (event.target !== item) return;
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        if (item.getAttribute('aria-disabled') !== 'true') item.click();
        return;
      }
      const direction = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[event.key];
      if (!direction && !['Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const available = [...stepItems].filter(node => node.getAttribute('aria-disabled') !== 'true');
      const index = available.indexOf(item);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? available.length - 1
        : (index + direction + available.length) % available.length;
      available[next]?.focus();
    });
    item.addEventListener('click', () => {
      if (item.getAttribute('aria-disabled') === 'true') return;
      const step = parseInt(item.dataset.step);
      if (state.currentProject) navigateToStepForReview(step);
    });
  });

  // 流水线中所有的“下一步”按钮
  document.querySelectorAll('.btn-next-step').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (state.currentStep === 2) {
        if (!Array.isArray(state.slides) || state.slides.length === 0) {
          showStep2ValidationError('请先添加至少一个分镜，再进入图片生成。');
          return;
        }
        // 手动模式下，跳到 Step 3 前先提交手动分镜到后端
        if (isManualMode()) {
          const ok = await submitManualSkeletonIfNeeded();
          if (!ok) return;
        }
        navigateToStep(3);
      } else if (state.currentStep === 3) {
        navigateToStep(5);
      } else if (state.currentStep === 5) {
        const saved = await saveStep5Masks();
        if (saved) navigateToStep(6);
      } else if (state.currentStep < 8) {
        navigateToStep(state.currentStep + 1);
      }
    });
  });

  // ================= 步骤 1 事件 =================
  document.getElementById('step1-btn-submit')?.addEventListener('click', () => submitStep1());
  document.getElementById('step1-btn-save-edit')?.addEventListener('click', () => saveStep1Edit());
  document.querySelectorAll('[data-step1-mode]').forEach(button => {
    button.addEventListener('click', () => setStep1Mode(button.dataset.step1Mode));
  });
  document.getElementById('step1-btn-generate-article')?.addEventListener('click', () => generateStep1Article());
  document.getElementById('step1-btn-system-content')?.addEventListener('click', () => openArticleSystemContentModal());
  document.getElementById('step1-copy-article')?.addEventListener('click', () => copyStep1Article());
  document.getElementById('step1-article-input')?.addEventListener('input', event => autoResizeTextarea(event.currentTarget));
  document.getElementById('step1-markdown-editor')?.addEventListener('input', () => syncStep1MarkdownToSource());
  document.getElementById('step1-markdown-editor')?.addEventListener('paste', event => pasteStep1PlainText(event));

  // ================= 步骤 2 事件 =================
  document.getElementById('step2-btn-generate-script')?.addEventListener('click', () => openStep2ScriptStage());
  document.getElementById('step2-btn-generate-visual')?.addEventListener('click', () => generateStep2VisualPlan());
  document.getElementById('step2-btn-regenerate-script')?.addEventListener('click', () => openStep2GenerationModal());
  document.getElementById('btn-step2-generation-cancel')?.addEventListener('click', () => closeStep2GenerationModal());
  document.getElementById('btn-step2-generation-confirm')?.addEventListener('click', () => confirmStep2Generation());
  document.getElementById('step2-btn-script-prompt')?.addEventListener('click', () => openStoryboardRulesModal('script'));
  document.getElementById('step2-btn-visual-prompt')?.addEventListener('click', () => openStoryboardRulesModal('visual'));
  document.getElementById('step2-btn-save')?.addEventListener('click', () => handleStep2BatchDeleteButton());
  // 手动模式：添加幻灯片 + 批量导入
  document.getElementById('step2-btn-add-slide')?.addEventListener('click', () => addStep2Slide());
  document.getElementById('step2-btn-batch-import')?.addEventListener('click', () => openStep2BatchImportModal());
  document.getElementById('step2-batch-import-download')?.addEventListener('click', () => downloadStep2BatchTemplate());
  document.getElementById('step2-batch-import-file')?.addEventListener('change', e => handleStep2BatchImportFile(e));
  document.getElementById('btn-step2-batch-import-cancel')?.addEventListener('click', closeStep2BatchImportModal);
  document.getElementById('btn-step2-batch-import-append')?.addEventListener('click', () => submitStep2BatchImport('append'));
  document.getElementById('btn-step2-batch-import-overwrite')?.addEventListener('click', () => submitStep2BatchImport('overwrite'));

  // ================= 步骤 3 事件 =================
  document.getElementById('step3-btn-generate')?.addEventListener('click', () => generateStep3Image());
  document.getElementById('step3-btn-close-editor')?.addEventListener('click', () => closeStep3AIModal());
  document.getElementById('step3-btn-apply-candidate')?.addEventListener('click', () => applyStep3Candidate());
  document.getElementById('modal-step3-ai')?.addEventListener('click', (event) => {
    if (event.target.id === 'modal-step3-ai') closeStep3AIModal();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && document.getElementById('modal-step3-ai').style.display === 'flex') {
      closeStep3AIModal();
    }
  });
  document.getElementById('step3-batch-upload')?.addEventListener('change', (e) => handleStep3BatchUpload(e));
  document.getElementById('step3-btn-batch-generate')?.addEventListener('click', () => generateAllStep3Images());
  document.getElementById('step3-btn-stop-queue')?.addEventListener('click', stopStep3GenerationQueue);
  document.getElementById('step3-btn-copy-prompts')?.addEventListener('click', () => copyStep2Prompts());
  document.getElementById('step3-btn-prompt-settings')?.addEventListener('click', () => openStep3PromptSettingsModal());
  document.getElementById('btn-step3-prompt-cancel')?.addEventListener('click', () => closeStep3PromptSettingsModal());
  document.getElementById('btn-step3-prompt-save')?.addEventListener('click', () => saveStep3PromptSettings());
  document.getElementById('btn-step3-prompt-reset')?.addEventListener('click', () => resetStep3PromptSettings());
  document.getElementById('step3-image-system-prompt')?.addEventListener('input', () => updateStep3PromptFullPreview());
  document.getElementById('step3-btn-confirm')?.addEventListener('click', () => confirmStep3Images());

  // ================= 步骤 5 事件 =================
  document.getElementById('step5-btn-semantic-blocks')?.addEventListener('click', () => runStep5SemanticBlocks());
  document.getElementById('step5-btn-new-block')?.addEventListener('click', () => createCurrentSlideBlock());
  document.getElementById('step5-btn-clear-current')?.addEventListener('click', () => clearCurrentSlideMaskAnnotations());
  document.getElementById('step5-btn-subtitle-settings')?.addEventListener('click', () => openSubtitleSettingsModal());
  document.getElementById('step5-btn-animation-settings')?.addEventListener('click', () => openAnimationSettingsModal());
  document.getElementById('step5-btn-fullscreen')?.addEventListener('click', () => toggleStep5Fullscreen());
  document.getElementById('step5-brush-size')?.addEventListener('input', (e) => updateBrushSize(e.target.value));
  document.getElementById('step5-eraser-size')?.addEventListener('input', (e) => updateEraserSize(e.target.value));
  document.getElementById('step5-btn-confirm-next')?.addEventListener('click', async () => {
    const saved = await saveStep5Masks();
    if (saved) navigateToStep(6);
  });

  // ================= 步骤 6 事件 =================
  document.getElementById('step6-btn-init')?.addEventListener('click', () => initStep6Narration());
  document.getElementById('step6-btn-ai-annotate')?.addEventListener('click', () => annotateStep6Narration());
  document.getElementById('step6-btn-ai-prompt')?.addEventListener('click', () => openStep6AnnotationPromptModal());
  document.getElementById('btn-step6-ai-prompt-cancel')?.addEventListener('click', () => closeStep6AnnotationPromptModal());
  document.getElementById('btn-step6-ai-prompt-save')?.addEventListener('click', () => saveStep6AnnotationPrompts());
  document.getElementById('step6-ai-system-prompt')?.addEventListener('input', () => updateStep6AnnotationFullPrompt());
  document.getElementById('step6-ai-output-example')?.addEventListener('input', () => updateStep6AnnotationFullPrompt());
  document.getElementById('step6-btn-save-and-tts')?.addEventListener('click', () => saveNarrationAndRunTTS());
  document.getElementById('step6-btn-audio-confirm-next')?.addEventListener('click', async () => {
    const confirmed = await confirmStep7Audio();
    if (confirmed) navigateToStep(10);
  });
  document.getElementById('step10-btn-next')?.addEventListener('click', () => navigateToStep(9));
  document.getElementById('step9-btn-skip')?.addEventListener('click', () => navigateToStep(8));

  // 步骤 7 后端能力已合并到可见步骤 6
  document.getElementById('step7-btn-synthesize')?.addEventListener('click', () => runStep7TTS());
  document.getElementById('step7-btn-force-all')?.addEventListener('click', () => confirmForceRegenerateAllTTS());

  // ================= 步骤 8 事件 =================
  document.getElementById('step8-btn-render')?.addEventListener('click', () => runStep8Render());
  document.getElementById('step8-btn-pptx')?.addEventListener('click', () => runStep8PptxExport());
  document.getElementById('btn-storyboard-rules-cancel')?.addEventListener('click', () => closeStoryboardRulesModal());
  document.getElementById('btn-step2-prompts-save')?.addEventListener('click', () => saveStep2Prompts());
  document.getElementById('btn-step2-prompt-template-load')?.addEventListener('click', () => loadSelectedStep2PromptTemplate());
  document.getElementById('btn-step2-prompt-template-new')?.addEventListener('click', () => beginStep2PromptTemplateCreation());
  document.getElementById('btn-step2-prompt-template-save')?.addEventListener('click', () => saveStep2PromptTemplate());
  document.getElementById('btn-step2-prompt-template-create-cancel')?.addEventListener('click', () => cancelStep2PromptTemplateCreation());
  document.getElementById('btn-step2-prompt-template-delete')?.addEventListener('click', () => deleteSelectedStep2PromptTemplate());
  document.getElementById('step2-prompt-template-select')?.addEventListener('change', event => {
    cancelStep2PromptTemplateCreation();
    state.selectedStep2PromptTemplateId = event.target.value || '';
    updateStep2PromptTemplateDeleteButton();
  });
  document.getElementById('step2-visual-narration-map')?.addEventListener('input', event => handleStep2MapEditorInput(event));
  document.getElementById('step2-script-visuals')?.addEventListener('input', event => handleStep2MapEditorInput(event));
  document.getElementById('step2-visual-narration-map')?.addEventListener('change', event => handleStep2MapEditorChange(event));
  document.getElementById('step2-script-slides')?.addEventListener('input', event => handleStep2MapEditorInput(event));
  document.getElementById('step2-script-slides')?.addEventListener('change', event => handleStep2MapEditorChange(event));
  [
    'step2-script-system-prompt',
    'step2-script-output-example',
    'step2-visual-system-prompt',
    'step2-visual-output-example'
  ].forEach(id => {
    document.getElementById(id)?.addEventListener('input', () => updateStep2FullPromptPreviews());
  });
  document.getElementById('btn-subtitle-settings-close')?.addEventListener('click', () => closeSubtitleSettingsModal());
  document.getElementById('btn-subtitle-settings-save')?.addEventListener('click', () => saveSubtitleSettings());
  document.getElementById('btn-subtitle-settings-reset')?.addEventListener('click', () => resetSubtitleSettings());
  ['subtitle-enabled', 'subtitle-sample-text', 'subtitle-font-key', 'subtitle-font-size', 'subtitle-font-weight', 'subtitle-bottom', 'subtitle-horizontal-margin', 'subtitle-color', 'subtitle-highlight-color', 'subtitle-paging-window', 'subtitle-max-lines', 'subtitle-token-highlight']
    .forEach(id => document.getElementById(id)?.addEventListener('input', () => updateSubtitlePreview()));
  document.getElementById('btn-animation-settings-close')?.addEventListener('click', () => closeAnimationSettingsModal());
  document.getElementById('btn-animation-settings-preview')?.addEventListener('click', () => previewGlobalAnimationSettings());
  document.getElementById('btn-animation-settings-save')?.addEventListener('click', () => saveGlobalAnimationSettings());
  document.getElementById('btn-animation-settings-reset')?.addEventListener('click', () => resetGlobalAnimationSettings());
  document.getElementById('animation-setting-duration')?.addEventListener('input', (event) => {
    document.getElementById('animation-setting-duration-value').textContent = Number(event.target.value).toFixed(2);
  });
  document.getElementById('setting-llm-provider')?.addEventListener('change', (event) => applyLlmProviderPreset(event.target.value));
  document.addEventListener('wheel', handleGlobalMaskWheel, { passive: false, capture: true });

  // 窗口尺寸变化时重新校准 Step 6 旁白输入框高度（文本换行会随宽度变化）。
  let _step6ResizeTimer = null;
  window.addEventListener('resize', () => {
    if (_step6ResizeTimer) clearTimeout(_step6ResizeTimer);
    _step6ResizeTimer = setTimeout(() => {
      document.querySelectorAll('.step6-tts-input').forEach(ta => _resizeNarrationTextarea(ta));
    }, 150);
  });
}


// 勾画标注工作区(可选步骤 10)页面级事件。功能实现位于
// annotations_workspace.js / annotations_editor.js,此处只做绑定。
function initAnnotationWorkspaceEvents() {
  const enabledToggle = document.getElementById('annotation-enabled-toggle');
  enabledToggle?.addEventListener('change', () => {
    window.setAnnotationsEnabled?.(enabledToggle.checked);
  });

  document.getElementById('annotation-btn-goto-images')?.addEventListener('click', () => navigateToStepForReview(3));
  document.getElementById('annotation-btn-goto-narration')?.addEventListener('click', () => navigateToStepForReview(6));

  document.getElementById('annotation-btn-region')?.addEventListener('click', () => {
    const active = document.getElementById('annotation-btn-region').classList.contains('active');
    window.setAnnotationDrawMode?.(active ? null : 'region');
  });
  document.getElementById('annotation-btn-select')?.addEventListener('click', () => window.setAnnotationDrawMode?.(null));
  document.getElementById('annotation-btn-freehand')?.addEventListener('click', () => {
    const active = document.getElementById('annotation-btn-freehand').classList.contains('active');
    window.setAnnotationDrawMode?.(active ? null : 'freehand');
  });
  document.getElementById('annotation-btn-finish-freehand')?.addEventListener('click', () => window.finishAnnotationFreehand?.(true));
  document.getElementById('annotation-btn-detect')?.addEventListener('click', () => {
    window.submitAnnotationJob?.('detect_text');
  });
  document.getElementById('annotation-btn-align')?.addEventListener('click', () => window.submitAnnotationJob?.('align'));
  document.getElementById('annotation-btn-ai-all')?.addEventListener('click', () => window.autoAnnotateCurrentPage?.(true));
  document.getElementById('annotation-btn-ai-plan')?.addEventListener('click', () => {
    window.autoAnnotateCurrentPage?.();
  });
  document.getElementById('annotation-ai-emphasis')?.addEventListener('change', event => {
    window.setAnnotationEmphasis?.(event.target.value);
  });
  document.getElementById('annotation-btn-undo')?.addEventListener('click', () => window.undoAnnotationEdit?.());
  document.getElementById('annotation-btn-redo')?.addEventListener('click', () => window.redoAnnotationEdit?.());
  document.getElementById('annotation-btn-preview')?.addEventListener('click', () => window.previewAnnotationAnimation?.());
  document.getElementById('annotation-btn-confirm-page')?.addEventListener('click', () => window.confirmAnnotationPage?.());

  const canvasFrame = document.getElementById('annotation-canvas-frame');
  canvasFrame?.addEventListener('pointerdown', event => {
    if (typeof handleAnnotationDrawPointerDown === 'function') handleAnnotationDrawPointerDown(event);
  });
  canvasFrame?.addEventListener('pointermove', event => {
    if (typeof handleAnnotationDrawPointerMove === 'function') handleAnnotationDrawPointerMove(event);
  });
  canvasFrame?.addEventListener('pointerup', event => {
    if (typeof handleAnnotationDrawPointerUp === 'function') handleAnnotationDrawPointerUp(event);
  });
  canvasFrame?.addEventListener('pointercancel', event => {
    if (typeof handleAnnotationDrawPointerCancel === 'function') handleAnnotationDrawPointerCancel(event);
  });

  document.addEventListener('keydown', event => {
    window.annotationEditorKeyboardHandler?.(event);
  });

  // 关闭标签页前若有未保存编辑,同步给出提示;不依赖 beforeunload 异步写入。
  window.addEventListener('beforeunload', event => {
    if (window.hasUnsavedAnnotationEdits?.()) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
}
