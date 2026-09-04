const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const app = fs.readFileSync(path.join(root, 'static', 'workflow_state.js'), 'utf8');
const uiFoundation = fs.readFileSync(path.join(root, 'static', 'ui_foundation.js'), 'utf8');
const apiClient = fs.readFileSync(path.join(root, 'static', 'api_client.js'), 'utf8');
const artifactRepair = fs.readFileSync(path.join(root, 'static', 'artifact_repair.js'), 'utf8');
const settings = fs.readFileSync(path.join(root, 'static', 'settings.js'), 'utf8');
const projects = fs.readFileSync(path.join(root, 'static', 'projects.js'), 'utf8');
const article = fs.readFileSync(path.join(root, 'static', 'article.js'), 'utf8');
const storyboard = fs.readFileSync(path.join(root, 'static', 'storyboard.js'), 'utf8');
const storyboardPrompts = fs.readFileSync(path.join(root, 'static', 'storyboard_prompts.js'), 'utf8');
const images = fs.readFileSync(path.join(root, 'static', 'images.js'), 'utf8');
const imagePrompts = fs.readFileSync(path.join(root, 'static', 'image_prompts.js'), 'utf8');
const maskReveal = fs.readFileSync(path.join(root, 'static', 'mask_reveal.js'), 'utf8');
const maskWorkspace = fs.readFileSync(path.join(root, 'static', 'mask_workspace.js'), 'utf8');
const maskEditor = fs.readFileSync(path.join(root, 'static', 'mask_editor.js'), 'utf8');
const subtitleSettings = fs.readFileSync(path.join(root, 'static', 'subtitle_settings.js'), 'utf8');
const narrationAudio = fs.readFileSync(path.join(root, 'static', 'narration_audio.js'), 'utf8');
const outputRender = fs.readFileSync(path.join(root, 'static', 'output_render.js'), 'utf8');
const promptHelp = fs.readFileSync(path.join(root, 'static', 'prompt_help.js'), 'utf8');
const workspaceNavigation = fs.readFileSync(path.join(root, 'static', 'workspace_navigation.js'), 'utf8');
const eventBindings = fs.readFileSync(path.join(root, 'static', 'event_bindings.js'), 'utf8');
const step2Logic = `${app}\n${storyboard}\n${storyboardPrompts}`;
const html = fs.readFileSync(path.join(root, 'static', 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'static', 'style.css'), 'utf8');
const aiMask = fs.readFileSync(path.join(root, 'static', 'ai_mask_extension.js'), 'utf8');
const projectProfile = fs.readFileSync(path.join(root, 'static', 'project_profile_extension.js'), 'utf8');
const background = fs.readFileSync(path.join(root, 'static', 'storyboard_background_extension.js'), 'utf8');
const styleManager = fs.readFileSync(path.join(root, 'static', 'style_reference_manager_extension.js'), 'utf8');
const oneClick = fs.readFileSync(path.join(root, 'static', 'one_click_extension.js'), 'utf8');
const creationConfigManagement = fs.readFileSync(path.join(root, 'static', 'creation_config_management.js'), 'utf8');

if (fs.existsSync(path.join(root, 'static', 'app.js')) || html.includes('app.js')) {
  throw new Error('legacy app.js runtime entry was recreated');
}
for (const stateOwner of ['function createWorkflowState(', 'const state = createWorkflowState()', 'const PPTStudioRuntime =', 'runtime: PPTStudioRuntime']) {
  if (!app.includes(stateOwner)) throw new Error(`workflow state entry is missing ${stateOwner}`);
}
if (!css.includes('#toast-container')) throw new Error('toast container layout missing');
for (const uiOwner of ['getToastPresentation', 'showToast', 'showCustomConfirm', 'escHtml', 'narrationDedupeKey', 'uniqueNarrationLines', 'autoResizeTextarea']) {
  if (!uiFoundation.includes(`function ${uiOwner}(`)) throw new Error(`UI foundation is missing ${uiOwner}`);
  if (app.includes(`function ${uiOwner}(`)) throw new Error(`UI foundation ownership returned to app.js: ${uiOwner}`);
}
if (!(html.indexOf('workflow_state.js') < html.indexOf('ui_foundation.js') && html.indexOf('ui_foundation.js') < html.indexOf('api_client.js'))) {
  throw new Error('workflow state, UI foundation, and API client script order is unsafe');
}
for (const apiOwner of ['const API =', "headers.set('X-PPT-Studio-Request'", 'window.API = API']) {
  if (!apiClient.includes(apiOwner)) throw new Error(`API client is missing ${apiOwner}`);
  if (app.includes(apiOwner)) throw new Error(`API client ownership returned to app.js: ${apiOwner}`);
}
for (const repairOwner of ['artifactRepairPrompts', 'offerArtifactRepair']) {
  if (!artifactRepair.includes(repairOwner)) throw new Error(`artifact repair module is missing ${repairOwner}`);
  if (app.includes(repairOwner)) throw new Error(`artifact repair ownership returned to app.js: ${repairOwner}`);
}
if (!(html.indexOf('workflow_state.js') < html.indexOf('api_client.js') && html.indexOf('api_client.js') < html.indexOf('artifact_repair.js'))) {
  throw new Error('workflow state, API client, and artifact repair script order is unsafe');
}
if (!css.includes('left: 18px')) throw new Error('desktop toasts are not anchored inside the workflow rail');
if (/\.toast\s*\{[^}]*position:\s*fixed/s.test(css)) throw new Error('individual toasts still overlap at a fixed position');
if (!/\.step3-card-header\s*\{[^}]*min-height:\s*42px/s.test(css)) throw new Error('image card header height is not stable');
if (!/\.step3-card-actions\s*\{[^}]*grid-template-columns:\s*44px 36px 48px/s.test(css)) throw new Error('image card action columns are not stable');
if (!/\.step3-card-action[\s\S]*?white-space:\s*nowrap\s*!important/s.test(css)) throw new Error('image card actions can still wrap and jitter');
if (!images.includes('step3-action-placeholder')) throw new Error('image card delete action does not reserve a stable slot');
if (images.indexOf('step3-delete-action') > images.indexOf('step3-upload-action')) throw new Error('image card delete action must sit between AI generation and upload');
if (!images.includes('step3UploadingSlides') || !images.includes("step3GeneratingPreviewHtml('上传中'")) throw new Error('per-card upload progress is missing');
if (!background.includes('step3-btn-delete-all-images') || !images.includes('deleteAllStep3Images')) throw new Error('bulk image deletion control is missing');
if (html.includes('step3-image-order-hint')) throw new Error('obsolete fixed-position image hint is still visible');

if (html.includes('config_effectiveness.js')) throw new Error('runtime patch script is still loaded');
if (!html.includes('settings.js')) throw new Error('settings frontend module is not loaded explicitly');
for (const settingsFunction of [
  'loadSettings',
  'saveSettings',
  'exportGlobalSettings',
  'importGlobalSettings',
  'testLlmConnection',
  'testImageConnection',
  'testTtsConnection',
]) {
  if (!settings.includes(`function ${settingsFunction}(`)) {
    throw new Error(`settings module is missing ${settingsFunction}`);
  }
  if (app.includes(`function ${settingsFunction}(`)) {
    throw new Error(`settings implementation returned to app.js: ${settingsFunction}`);
  }
}
if (!html.includes('projects.js')) throw new Error('project library frontend module is not loaded explicitly');
for (const projectFunction of ['loadProjects', 'createProject', 'deleteProject']) {
  if (!projects.includes(`function ${projectFunction}(`)) {
    throw new Error(`project library module is missing ${projectFunction}`);
  }
  if (app.includes(`function ${projectFunction}(`)) {
    throw new Error(`project library implementation returned to app.js: ${projectFunction}`);
  }
}
for (const creationConfigFunction of ['ensureCreationConfigSelector', 'selectedCreationConfig', 'loadCreationConfigs']) {
  if (!projects.includes(`function ${creationConfigFunction}(`)) {
    throw new Error(`project creation configuration selector is missing ${creationConfigFunction}`);
  }
}
if (!html.includes('id="input-creation-config"')) {
  throw new Error('project creation configuration selector is missing from the static modal');
}
for (const creationConfigToken of [
  "API.get('/api/creation-configs')",
  'config_package_id: creationConfig.id',
  'config_package_version: creationConfig.version',
  'option.textContent = `${String(item.name || \'未命名配置包\')} · v${version}`',
]) {
  if (!projects.includes(creationConfigToken)) {
    throw new Error(`project creation configuration contract missing: ${creationConfigToken}`);
  }
}
if (!eventBindings.includes('loadCreationConfigs();')) {
  throw new Error('creation configuration packages are not loaded when opening the project modal');
}
for (const managementToken of [
  'openCreationConfigManagement',
  "window.API.get('/api/creation-configs')",
  "window.API.get('/api/model-connections')",
  "window.API.post('/api/model-connections', payload)",
  'buildStructuredEditor',
  'syncStructuredFieldsToJson',
  'loadPayloadIntoStructured',
  'readBindingValue',
  'versions',
  'copyPackage',
  'archivePackage',
]) {
  if (!creationConfigManagement.includes(managementToken)) {
    throw new Error(`creation configuration management UI missing: ${managementToken}`);
  }
}
if (!html.includes('creation_config_management.js')
  || !html.includes('btn-open-creation-config-management')
  || !html.includes('modal-creation-config-management')
  || !html.includes('creation-config-prompt-fields')
  || !html.includes('creation-config-model-binding-fields')
  || !html.includes('creation-config-tts-voice-id')
  || !html.includes('creation-config-subtitle-enabled')) {
  throw new Error('creation configuration management UI is not declared');
}
if (!(html.indexOf('api_client.js') < html.indexOf('creation_config_management.js')
  && html.indexOf('creation_config_management.js') < html.indexOf('event_bindings.js'))) {
  throw new Error('creation configuration management script order is unsafe');
}
if (!eventBindings.includes('initCreationConfigManagementEvents')) {
  throw new Error('creation configuration management events are not bound at startup');
}
if (!projectProfile.includes("apiGet('/api/creation-configs')")
  || !projectProfile.includes('config_package_id: creationConfig.id')
  || !projectProfile.includes('config_package_version: creationConfig.version')) {
  throw new Error('profile project creation does not preserve the selected creation configuration');
}
if (projects.includes('onclick=')) throw new Error('project cards still use interpolated inline click handlers');
if (!projects.includes('escHtml(project.name)') || !projects.includes("escHtml(project.description || '无项目描述')")) {
  throw new Error('project card user content is not HTML escaped');
}
if (!html.includes('article.js')) throw new Error('Step 1 article frontend module is not loaded explicitly');
for (const articleFunction of [
  'loadStep1Data',
  'setStep1Mode',
  'ensureArticleSystemContentModal',
  'openArticleSystemContentModal',
  'generateStep1Article',
  'submitStep1',
  'saveStep1Edit',
]) {
  if (!article.includes(`function ${articleFunction}(`)) {
    throw new Error(`Step 1 article module is missing ${articleFunction}`);
  }
  if (app.includes(`function ${articleFunction}(`)) {
    throw new Error(`Step 1 implementation returned to app.js: ${articleFunction}`);
  }
}
if (!article.includes("saveEditButton.style.display = 'inline-flex'")) {
  throw new Error('saved Step 1 articles do not restore the edit action');
}
if (!article.includes('await navigateToStep(2)') || article.includes('setTimeout(() =>')) {
  throw new Error('Step 1 save still relies on an artificial navigation delay');
}
if (!html.includes('storyboard.js')) throw new Error('Step 2 storyboard frontend module is not loaded explicitly');
for (const storyboardFunction of [
  'loadStep2Data',
  'addManualSlide',
  'submitStep2BatchImport',
  'generateStep2Contract',
  'renderStep2Workspace',
  'handleStep2MapEditorInput',
  'saveStep2Contract',
]) {
  if (!storyboard.includes(`function ${storyboardFunction}(`)) {
    throw new Error(`Step 2 storyboard module is missing ${storyboardFunction}`);
  }
  if (app.includes(`function ${storyboardFunction}(`)) {
    throw new Error(`Step 2 implementation returned to app.js: ${storyboardFunction}`);
  }
}
if (!html.includes('storyboard_prompts.js')) throw new Error('Step 2 Prompt frontend module is not loaded explicitly');
for (const promptFunction of [
  'openStoryboardRulesModal',
  'updateStep2FullPromptPreviews',
  'renderStep2PromptEditor',
  'renderStep2PromptTemplateOptions',
  'loadSelectedStep2PromptTemplate',
  'saveStep2PromptTemplate',
  'deleteSelectedStep2PromptTemplate',
  'saveStep2Prompts',
  'closeStoryboardRulesModal',
]) {
  if (!storyboardPrompts.includes(`function ${promptFunction}(`)) {
    throw new Error(`Step 2 Prompt module is missing ${promptFunction}`);
  }
  if (app.includes(`function ${promptFunction}(`) || storyboard.includes(`function ${promptFunction}(`)) {
    throw new Error(`Step 2 Prompt implementation escaped its module: ${promptFunction}`);
  }
}
if (!html.includes('images.js')) throw new Error('Step 3 image frontend module is not loaded explicitly');
for (const imageFunction of [
  'loadStep3Data',
  'refreshStep3Images',
  'renderStep3Grid',
  'reorderStep3Images',
  'openStep3AI',
  'uploadStep3ImageById',
  'deleteStep3Image',
  'deleteAllStep3Images',
  'handleStep3BatchUpload',
  'generateAllStep3Images',
  'generateStep3Image',
  'applyStep3Candidate',
  'confirmStep3Images',
]) {
  if (!images.includes(`function ${imageFunction}(`)) {
    throw new Error(`Step 3 image module is missing ${imageFunction}`);
  }
  if (app.includes(`function ${imageFunction}(`)) {
    throw new Error(`Step 3 image implementation returned to app.js: ${imageFunction}`);
  }
}
if (!html.includes('image_prompts.js')) throw new Error('Step 3 image Prompt frontend module is not loaded explicitly');
for (const imagePromptFunction of [
  'refreshStep3Prompts',
  'currentStep3PromptInfo',
  'updateStep3PromptFullPreview',
  'openStep3PromptSettingsModal',
  'closeStep3PromptSettingsModal',
  'resetStep3PromptSettings',
  'saveStep3PromptSettings',
]) {
  if (!imagePrompts.includes(`function ${imagePromptFunction}(`)) {
    throw new Error(`Step 3 image Prompt module is missing ${imagePromptFunction}`);
  }
  if (app.includes(`function ${imagePromptFunction}(`) || images.includes(`function ${imagePromptFunction}(`)) {
    throw new Error(`Step 3 image Prompt implementation escaped its module: ${imagePromptFunction}`);
  }
}
if (!imagePrompts.includes('window.refreshStep3Prompts = refreshStep3Prompts')) {
  throw new Error('Step 3 image Prompt refresh bridge is missing');
}
if (!html.includes('mask_workspace.js')) throw new Error('Step 5 Mask workspace module is not loaded explicitly');
for (const maskWorkspaceFunction of [
  'resetStep5ProjectState',
  'loadStep5Data',
  'normalizeManifestNarrationFragments',
  'getSlideMaskBoxes',
  'renderStep5Workspace',
  'switchStep5Slide',
  'toggleStep5Fullscreen',
  'renderStep5BoxesForm',
  'renderStep5NarrationPanel',
  'toggleStep5FragmentLink',
  'selectStep5MaskBox',
  'focusAiMaskIssue',
]) {
  if (!maskWorkspace.includes(`function ${maskWorkspaceFunction}(`)) {
    throw new Error(`Step 5 Mask workspace module is missing ${maskWorkspaceFunction}`);
  }
  if (app.includes(`function ${maskWorkspaceFunction}(`)) {
    throw new Error(`Step 5 Mask workspace implementation returned to app.js: ${maskWorkspaceFunction}`);
  }
}
for (const bridge of ['window.loadStep5Data', 'window.renderStep5Workspace', 'window.focusAiMaskIssue', 'window.getCurrentStep5SlideId']) {
  if (!maskWorkspace.includes(bridge)) throw new Error(`Step 5 Mask workspace bridge is missing: ${bridge}`);
}
if (!html.includes('mask_editor.js')) throw new Error('Step 5 Mask editor module is not loaded explicitly');
for (const maskEditorFunction of [
  'updateBrushSize',
  'updateEraserSize',
  'startMaskTool',
  'createCurrentSlideBlock',
  'beginMaskStroke',
  'continueMaskStroke',
  'finishMaskStroke',
  'initCanvasEvents',
  'applyMaskCanvasZoom',
  'buildMaskDisplayLayer',
  'rasterizeManualMask',
  'setStep5MaskPreviewMode',
  'drawManualMaskStrokes',
  'redrawCanvas',
  'saveStep5CurrentState',
  'scheduleStep5Autosave',
  'saveStep5Draft',
  'flushStep5Draft',
  'runStep5SemanticBlocks',
  'saveStep5Masks',
]) {
  if (!maskEditor.includes(`function ${maskEditorFunction}(`)) {
    throw new Error(`Step 5 Mask editor module is missing ${maskEditorFunction}`);
  }
  if (app.includes(`function ${maskEditorFunction}(`) || maskWorkspace.includes(`function ${maskEditorFunction}(`)) {
    throw new Error(`Step 5 Mask editor implementation escaped its module: ${maskEditorFunction}`);
  }
}
for (const bridge of [
  'window.saveStep5Draft',
  'window.saveStep5CurrentState',
  'window.focusFirstAiMaskResult',
  'window.setStep5MaskPreviewMode',
  'window.PPTStudio',
]) {
  if (!maskEditor.includes(bridge)) throw new Error(`Step 5 Mask editor bridge is missing: ${bridge}`);
}
if (!html.includes('subtitle_settings.js')) throw new Error('subtitle settings module is not loaded explicitly');
for (const subtitleFunction of [
  'readSubtitleSettingsForm',
  'populateSubtitleSettingsForm',
  'updateSubtitlePreview',
  'openSubtitleSettingsModal',
  'saveSubtitleSettings',
]) {
  if (!subtitleSettings.includes(`function ${subtitleFunction}(`)) {
    throw new Error(`subtitle settings module is missing ${subtitleFunction}`);
  }
  if (app.includes(`function ${subtitleFunction}(`) || narrationAudio.includes(`function ${subtitleFunction}(`)) {
    throw new Error(`subtitle settings implementation escaped its module: ${subtitleFunction}`);
  }
}
if (!html.includes('narration_audio.js')) throw new Error('narration/audio module is not loaded explicitly');
for (const narrationFunction of [
  'loadStep6Data',
  'initStep6Narration',
  'openStep6AnnotationPromptModal',
  'annotateStep6Narration',
  'normalizeStep6Data',
  'renderStep6Workspace',
  'saveStep6CurrentState',
  'scheduleStep6Autosave',
  'flushStep6Autosave',
  'saveStep6Narration',
  'loadStep7Data',
  'runStep7TTS',
  'saveNarrationAndRunTTS',
  'confirmStep7Audio',
]) {
  if (!narrationAudio.includes(`function ${narrationFunction}(`)) {
    throw new Error(`narration/audio module is missing ${narrationFunction}`);
  }
  if (app.includes(`function ${narrationFunction}(`)) {
    throw new Error(`narration/audio implementation returned to app.js: ${narrationFunction}`);
  }
}
if (!html.includes('output_render.js')) throw new Error('output/render module is not loaded explicitly');
for (const outputFunction of [
  'updateStep8LoadingText',
  'stopStep8RenderPolling',
  'startStep8RenderPolling',
  'loadStep8Data',
  'runStep8Render',
  'stopStep8PptxPolling',
  'setStep8OutputError',
  'updateStep8PptxLoading',
  'startStep8PptxPolling',
  'refreshStep8PptxReadiness',
  'loadStep8PptxData',
  'runStep8PptxExport',
  'showStep8PptxResults',
  'deleteStep8Pptx',
  'showStep8VideoResult',
  'generateStep8SpeedVideo',
  'deleteStep8Video',
]) {
  if (!outputRender.includes(`function ${outputFunction}(`)) {
    throw new Error(`output/render module is missing ${outputFunction}`);
  }
  if (app.includes(`function ${outputFunction}(`)) {
    throw new Error(`output/render implementation returned to app.js: ${outputFunction}`);
  }
}
for (const bridge of ['window.deleteStep8Video', 'window.deleteStep8Pptx']) {
  if (!outputRender.includes(bridge)) throw new Error(`output/render bridge is missing: ${bridge}`);
}
if (!html.includes('prompt_help.js')) throw new Error('Prompt help module is not loaded explicitly');
for (const promptHelpFunction of ['ensurePromptIOHelpModal', 'openPromptIOHelp']) {
  if (!promptHelp.includes(`function ${promptHelpFunction}(`)) {
    throw new Error(`Prompt help module is missing ${promptHelpFunction}`);
  }
  if (app.includes(`function ${promptHelpFunction}(`)) {
    throw new Error(`Prompt help implementation returned to app.js: ${promptHelpFunction}`);
  }
}
if (!promptHelp.includes('window.openPromptIOHelp = openPromptIOHelp')) {
  throw new Error('Prompt help global bridge is missing');
}
if (!html.includes('workspace_navigation.js')) throw new Error('workspace navigation module is not loaded explicitly');
for (const navigationFunction of [
  'enterWorkspace',
  'exitWorkspace',
  'applyProjectAiMode',
  'toggleProjectAiMode',
  'updateStepperUI',
  'refreshCurrentProjectStatus',
  'navigateToStep',
  'loadStepData',
]) {
  if (!workspaceNavigation.includes(`function ${navigationFunction}(`)) {
    throw new Error(`workspace navigation module is missing ${navigationFunction}`);
  }
  if (app.includes(`function ${navigationFunction}(`)) {
    throw new Error(`workspace navigation implementation returned to app.js: ${navigationFunction}`);
  }
}
if (!html.includes('event_bindings.js')) throw new Error('event bindings module is not loaded explicitly');
if (!eventBindings.includes('function initGlobalEvents(') || !eventBindings.includes("document.addEventListener('DOMContentLoaded'")) {
  throw new Error('shared DOM startup contract is missing');
}
if (app.includes('function initGlobalEvents(') || app.includes("document.addEventListener('DOMContentLoaded'")) {
  throw new Error('DOM startup or event bindings returned to app.js');
}
const workspaceScriptIndex = html.indexOf('workspace_navigation.js');
const eventScriptIndex = html.indexOf('event_bindings.js');
const extensionScriptIndex = html.indexOf('project_profile_extension.js');
if (!(workspaceScriptIndex > html.indexOf('output_render.js') && eventScriptIndex > workspaceScriptIndex && extensionScriptIndex > eventScriptIndex)) {
  throw new Error('core workflow, navigation, event, and extension script order is unsafe');
}
for (const settingsOwner of ['LLM_PROVIDER_PRESETS', 'detectLlmProvider', 'applyLlmProviderPreset']) {
  if (!settings.includes(settingsOwner)) {
    throw new Error(`settings module is missing LLM provider ownership: ${settingsOwner}`);
  }
  if (app.includes(settingsOwner)) {
    throw new Error(`LLM provider configuration returned to app.js: ${settingsOwner}`);
  }
}
const fullscreenStart = maskWorkspace.indexOf('function toggleStep5Fullscreen');
const fullscreenEnd = maskWorkspace.indexOf('function uuid', fullscreenStart);
const fullscreenImplementation = maskWorkspace.slice(fullscreenStart, fullscreenEnd);
if (!fullscreenImplementation.includes("fullscreenLabel.textContent = state.canvasState.maskFullscreen ? '退出全屏' : '放大标注'")) {
  throw new Error('Step 5 fullscreen toggle does not update its label directly');
}
if (fullscreenImplementation.includes('renderStep5Workspace')) {
  throw new Error('Step 5 fullscreen toggle still reloads unsaved workspace state');
}
for (const requiredStep2Token of [
  'step2-btn-script-prompt',
  'step2-btn-visual-prompt',
  'step2-script-system-prompt',
  'step2-script-output-example',
  'step2-visual-system-prompt',
  'step2-visual-output-example',
  'btn-step2-prompt-template-new',
  'step2-prompt-template-create-panel',
  'step2-slide-title-input',
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
  'step2-slide-subtitle-input',
  'step2-subtitle-field',
]) {
  if (step2Logic.includes(removedStep2Token) || html.includes(removedStep2Token) || css.includes(removedStep2Token)) {
    throw new Error(`legacy Step 2 editor still present: ${removedStep2Token}`);
  }
}
if (step2Logic.includes("group.id === 'body_group_02'")) {
  throw new Error('legacy hard-coded visual group filtering is still present');
}
if (!html.includes('step3-btn-batch-generate')) throw new Error('step 3 batch image generation action missing');
if (!background.includes('step3-btn-background-settings')) throw new Error('Step 3 final video background entry missing');
if (html.includes('step3-video-background-apply') || background.includes('step3-video-background-apply')) {
  throw new Error('obsolete video background apply button is still present');
}
if (!background.includes('铺满画面') || !background.includes('完整显示')) throw new Error('video background fit modes missing');
for (const backgroundMode of ['data-mode-card="image"', 'data-mode-card="solid"', 'canvasAspectLabel()']) {
  if (!background.includes(backgroundMode)) throw new Error(`final background modal contract missing: ${backgroundMode}`);
}
if (!storyboard.includes('handleStep2MapEditorInput') || !storyboard.includes('handleStep2MapEditorChange')) {
  throw new Error('Step 2 visual/narration mapping is not editable');
}
if (!html.includes('step2-slide-narration-input') || !html.includes('aria-describedby="step2-narration-source-hint"')) {
  throw new Error('Step 2 full narration editor is missing');
}
for (const confusingMappingToken of ['画面文字 / 元素名称', '对应旁白与绑定关系', '<span>绑定到</span>']) {
  if (step2Logic.includes(confusingMappingToken)) throw new Error(`Step 2 still exposes internal mapping control: ${confusingMappingToken}`);
}
if (!css.includes('grid-column: 3 / 5') || !css.includes('grid-row: 2')) {
  throw new Error('stale step status is not positioned below the step label');
}
if (!css.includes('.storyboard-bg-preview') || !css.includes('aspect-ratio:var(--project-aspect-ratio,16 / 9)')) {
  throw new Error('final background preview does not follow the current project canvas ratio');
}
if (!css.includes('calc(min(52dvh, 620px) * var(--project-aspect-ratio-scale, 1.7777778))')) {
  throw new Error('video review preview is not constrained by the viewport and project ratio');
}
if (!css.includes('.video-preview-box video') || !css.includes('object-fit: contain;')) {
  throw new Error('video review preview can crop its source video');
}
if (!maskEditor.includes('hexToRgba(color, isSelected ? 0.68 : 0.55)')) {
  throw new Error('mask overlay colors are too faint');
}
if (!images.includes('generateAllStep3Images')) throw new Error('step 3 batch generation handler missing');
if (!images.includes('step3GeneratingSlides')) throw new Error('step 3 per-slide generation state missing');
if (!images.includes('tasks.forEach(task => step3GeneratingSlides.add(task.slideId))')) {
  throw new Error('batch generation does not switch all cards to loading immediately');
}
if (!images.includes("document.getElementById('step3-preview-box').innerHTML = step3GeneratingPreviewHtml()")) {
  throw new Error('single image generation does not show loading in the preview pane');
}
if (!css.includes('.step3-generating-preview')) throw new Error('step 3 loading preview style missing');
if (!images.includes('await refreshStep3Images();')) throw new Error('step 3 does not wait for image state');
if (!images.includes('confirmBtn.disabled = !allImagesReady')) throw new Error('step 3 confirmation is not gated');
if (!maskEditor.includes('step5AutoSavePromise')) throw new Error('step 5 save serialization missing');
if (!maskReveal.includes("raw.type || raw.value || 'crop_fade_up'")) {
  throw new Error('mask animation preset values are not normalized correctly');
}
if (!maskReveal.includes('applyGlobalMaskReveal') || !maskEditor.includes('previewGlobalAnimationSettings')) {
  throw new Error('global Mask animation sync or preview is missing');
}
for (const animation of ['wipe_left_to_right', 'scratch_reveal', 'sticker_pop', 'stamp_in', 'paper_drop']) {
  if (!maskReveal.includes(`value: '${animation}'`)) {
    throw new Error(`mask animation preset missing: ${animation}`);
  }
}
for (const revealOwner of ['MASK_ANIMATION_PRESETS', 'normalizeMaskReveal', 'applyGlobalMaskReveal', 'ensureGlobalMaskRevealDefault']) {
  if (!maskReveal.includes(revealOwner)) throw new Error(`Mask Reveal module is missing ${revealOwner}`);
  if (app.includes(revealOwner)) throw new Error(`Mask Reveal ownership returned to app.js: ${revealOwner}`);
}
if (!(html.indexOf('mask_reveal.js') < html.indexOf('mask_workspace.js'))) {
  throw new Error('Mask Reveal module must load before the Mask workspace');
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
if (!maskWorkspace.includes('visual_description') || !css.includes('.mask-visual-card')) {
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
  if (step2Logic.includes(removedNarrationPolicyToken) || html.includes(removedNarrationPolicyToken)) {
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
if (!html.includes('step5-tool-cursor') || !maskEditor.includes('toolSize * displayScale')) {
  throw new Error('Mask tool cursor does not track the real canvas pixel diameter');
}
if (!maskEditor.includes('getCoalescedEvents') || !maskEditor.includes('scheduleLiveMaskRedraw')) {
  throw new Error('Mask painting does not coalesce pointer samples and redraws');
}
if (maskEditor.includes('MASK_PREVIEW_OUTLINE_PX') || !maskEditor.includes('buildMaskDisplayLayer')) {
  throw new Error('Mask preview must render the exact painted pixels without an added outline');
}
if (!maskWorkspace.includes('claimUniqueMaskColor') || !maskWorkspace.includes('idx + offset')) {
  throw new Error('Mask color collision handling must search for an unused palette color');
}
if (!css.includes('.step3-toolbar-row::before') || !css.includes('backdrop-filter: saturate(135%) blur(24px)') || !css.includes('mask-image: linear-gradient(')) {
  throw new Error('sticky workflow headers must use the full-width fading glass layer');
}
if (!css.includes('.sidebar .step-status-tag') || !css.includes('grid-row: 2') || !css.includes('position: static !important')) {
  throw new Error('pending-reconfirmation badges must sit below the step label');
}
if (aiMask.includes("setInlineStatus('AI 标注已完成'")) {
  throw new Error('completed AI Mask status must be a temporary toast, not persistent sidebar content');
}
for (const manualMaskHandler of ['startMaskPaint', 'startMaskErase', 'deleteMaskBox', 'beginMaskStroke']) {
  const owner = manualMaskHandler === 'deleteMaskBox' ? maskWorkspace : maskEditor;
  if (!owner.includes(manualMaskHandler)) throw new Error(`manual Mask fallback handler missing: ${manualMaskHandler}`);
}
if (!aiMask.includes('maybeAutoAnnotate') || !aiMask.includes('multimodal') && !aiMask.includes('AI 正在关联')) {
  throw new Error('automatic AI Mask flow is missing');
}
for (const reviewToken of ['ai-mask-review-panel', 'focusReviewIssue', 'quality_status', 'completed_needs_review']) {
  if (!aiMask.includes(reviewToken)) throw new Error(`AI Mask review UX missing: ${reviewToken}`);
}
for (const previewToken of ['data-preview-mode="source"', 'data-preview-mode="mask"', 'data-preview-mode="final"', 'buildExactPreview']) {
  if (!aiMask.includes(previewToken)) throw new Error(`production Mask preview control missing: ${previewToken}`);
}
if (!maskEditor.includes('setStep5MaskPreviewMode') || !maskWorkspace.includes('focusAiMaskIssue')) {
  throw new Error('Mask preview or issue focus bridge missing');
}
if (!maskEditor.includes('rebuildStep5SourceCache')) throw new Error('source image cache missing');
if (!maskEditor.includes('ctx.drawImage(step5SourceCanvas, 0, 0)')) {
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
  if (html.includes(removedToken) || app.includes(removedToken) || maskEditor.includes(removedToken) || css.includes(removedToken)) {
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
if (!maskWorkspace.includes("rle.encoding === 'row_runs_v1'") || !maskEditor.includes('exactRuns.forEach')) {
  throw new Error('exact RLE Mask preview support missing');
}
if (aiMask.includes('setInterval(fitFullscreenCanvas, 800)') || !aiMask.includes("new MutationObserver(fitFullscreenCanvas)")) {
  throw new Error('Mask fullscreen fitting must be event-driven rather than permanently polled');
}
if (html.includes('请在下方粘贴您的 Markdown 格式文章')) throw new Error('obsolete Step 1 top hint is still present');
for (const script of ['project_profile_extension.js', 'storyboard_background_extension.js', 'style_reference_manager_extension.js', 'ai_mask_auto_state.js', 'ai_mask_extension.js', 'one_click_extension.js']) {
  if (!html.includes(script)) throw new Error(`direct frontend script declaration missing: ${script}`);
}
if (!styleManager.includes('style-panel-template-name') || !styleManager.includes('最多只能上传 3 张')) {
  throw new Error('named image-style templates or three-image limit missing');
}
for (const styleMode of ['data-style-tab="template"', 'data-style-tab="manual"', 'data-style-tab="reverse"']) {
  if (!styleManager.includes(styleMode)) throw new Error(`image-style mode missing: ${styleMode}`);
}
if (!css.includes('.style-ref-card') || !css.includes('aspect-ratio:16 / 9') || !styleManager.includes('这 3 张效果预览会作为后续图片生成的实际参考图')) {
  throw new Error('image-style System Content / 16:9 reference output contract missing');
}
if (styleManager.includes('visual-draft-quality') || oneClick.includes('图片质量检查')) {
  throw new Error('removed image quality feature is still user-visible');
}
if (!oneClick.includes('button-spinner')) throw new Error('one-click stage spinner missing');
if (!oneClick.includes('one-click-sidebar-entry') || !oneClick.includes('stepper.appendChild(entry)')) {
  throw new Error('one-click button is not anchored directly below the video step');
}
// [轮询自愈 20260904] 一键轮询必须保留连接失败计数、前台恢复刷新与
// 新鲜度展示，且不允许回退到完全静默吞错的轮询实现。
if (oneClick.includes('catch(() => {})')) {
  throw new Error('one-click polling must not swallow connection errors silently');
}
for (const token of ['renderConnectionAlert', 'visibilitychange', 'lastRefreshAt', '页面数据刷新于']) {
  if (!oneClick.includes(token)) throw new Error(`one-click polling self-healing missing: ${token}`);
}
if (!css.includes('one-click-conn-alert')) throw new Error('one-click connection alert style missing');
if (!workspaceNavigation.includes("document.body.classList.add('workspace-open')") || !css.includes('body.workspace-open #toast-container')) {
  throw new Error('workspace notifications can still overlap the sidebar action');
}
if (html.includes('sidebar-flow-title') || html.includes('sidebar-flow-mark')) {
  throw new Error('obsolete workflow rail title/icon is still visible');
}
if (!html.includes('step-complete') || !css.includes('.sidebar .step-icon svg')) {
  throw new Error('workflow rail redesign is incomplete');
}
if (!css.includes('left: 30.875px') || !css.includes('repeating-linear-gradient') || !css.includes('height: calc((64px + 0.35rem) * 5)')) {
  throw new Error('workflow rail connector is not centered, dashed, and bounded to six steps');
}
if (!html.includes('step2-generation-status') || !storyboard.includes('setStep2GenerationStatus') || storyboard.includes('// 捕获报错')) {
  throw new Error('Step 2 failure is still swallowed without persistent feedback');
}
if (!css.includes('#step6-btn-audio-confirm-next:disabled') || !css.includes('#step8-btn-render:disabled')) {
  throw new Error('disabled primary button contrast contract is missing');
}
if (!projectProfile.includes("const aiMode = profile.automation_mode === 'auto' ? 'auto' : 'manual'")) {
  throw new Error('project profile mode is not mapped to the backend ai_mode contract');
}
if (!projectProfile.includes('ai_mode: aiMode')) {
  throw new Error('project creation does not submit the selected AI mode');
}
if (!workspaceNavigation.includes("document.getElementById('btn-toggle-ai-mode').style.display = 'none'")) {
  throw new Error('project AI mode control remains visible after returning to the project library');
}
if (!workspaceNavigation.includes('await navigateToStep(visibleStep)') || !workspaceNavigation.includes('workspaceNavigationVersion')) {
  throw new Error('workspace navigation does not await or invalidate stale loads');
}
if (!workspaceNavigation.includes('const entryVersion = ++workspaceNavigationVersion') || !workspaceNavigation.includes('entryVersion !== workspaceNavigationVersion')) {
  throw new Error('workspace entry can still be overwritten by a stale project request');
}
if (!uiFoundation.includes('await onYes()') || !uiFoundation.includes('showToast(`操作失败')) {
  throw new Error('shared confirmation does not handle asynchronous failures');
}
for (const token of ['智能继续', '从头重跑', "startOneClick('resume')", "startOneClick('restart')"]) {
  if (!oneClick.includes(token)) throw new Error(`one-click recovery control missing: ${token}`);
}
if (!uiFoundation.includes('narrationDedupeKey') || !uiFoundation.includes('uniqueNarrationLines')) {
  throw new Error('frontend narration deduplication guard is missing');
}
if (!html.includes('id="btn-back-home" class="secondary header-action" hidden')) {
  throw new Error('back-home control must use semantic hidden state instead of an inline display override');
}
if (!html.includes('id="step3-btn-batch-generate" class="secondary"') || !html.includes('批量生图')) {
  throw new Error('Step 3 batch generation action must keep the approved concise label');
}
if (!workspaceNavigation.includes("btnBackHome.hidden = false") || !workspaceNavigation.includes("btnBackHome.hidden = true")) {
  throw new Error('back-home visibility must preserve its inline-flex layout');
}
for (const token of [
  '--workflow-space-top: 12px',
  '--workflow-action-gap: 8px',
  '--workflow-tab-height: 28px',
  '.workflow-header',
  '.workflow-toolbar',
  '.workflow-tabs',
]) {
  if (!css.includes(token)) throw new Error(`workflow spacing system missing: ${token}`);
}
for (const panelClass of [
  'workflow-header workflow-header--titlebar',
  'workflow-header workflow-header--tabs',
  'workflow-header workflow-header--stacked',
]) {
  if (!html.includes(panelClass)) throw new Error(`workflow header variant missing: ${panelClass}`);
}
if (/step2-sticky-header" style="[^"]*margin-top:/s.test(html) || /step3-toolbar-row" style="[^"]*margin-/s.test(html)) {
  throw new Error('workflow header spacing must not be controlled by inline margins');
}

console.log('frontend quality checks passed');
