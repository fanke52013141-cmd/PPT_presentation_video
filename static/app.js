// 全局状态管理
let state = {
  currentProject: null,
  currentStep: 1,
  slides: [], // 第二步及后续的分镜/图片/Mask数据
  activeSlideIndex: 0, // 步骤2/3/5/6中当前激活的 slide 索引
  settings: {},
  step2BatchDeleteMode: false,
  step2DeleteSelection: new Set(),
  step2BatchOriginalSlides: null,
  step2BatchOriginalActiveIndex: 0,
  step2AutoSaveTimer: null,
  step2AutoSaveInFlight: false,
  canvasState: {
    boxes: [], // 当前 slide 的标注框列表 [{group_id: '', box: [x1,y1,x2,y2], text_label: '', role: ''}]
    selectedBoxIndex: -1,
    draggedBoxIndex: -1,
    draggedHandle: null, // 'nw', 'ne', 'se', 'sw', 'move'
    paintMode: false,
    paintingBoxIndex: -1,
    eraserMode: false,
    isPainting: false,
    currentStroke: null,
    brushSize: 80,
    brushCursorClientX: null,
    brushCursorClientY: null,
    maskZoom: 1,
    maskZoomOriginX: 50,
    maskZoomOriginY: 50,
    autoMaskLoading: false,
    semanticLoading: false,
    narrationPickerBoxIndex: -1,
    narrationPickerSelection: [],
    startX: 0,
    startY: 0
  }
};

// API 请求工具方法
const API = {
  async fetch(url, options = {}) {
    try {
      const response = await fetch(url, options);
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || '请求失败');
      }
      return data;
    } catch (error) {
      showToast(`❌ 错误: ${error.message}`);
      throw error;
    }
  },
  
  async get(url) {
    return this.fetch(url);
  },
  
  async post(url, body) {
    const isFormData = body instanceof FormData;
    return this.fetch(url, {
      method: 'POST',
      body: isFormData ? body : JSON.stringify(body),
      headers: isFormData ? {} : { 'Content-Type': 'application/json' }
    });
  },
  
  async put(url, body) {
    return this.fetch(url, {
      method: 'PUT',
      body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json' }
    });
  },
  
  async delete(url) {
    return this.fetch(url, { method: 'DELETE' });
  }
};

// Toast 提示
function showToast(message, duration = 3000) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerText = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'slideUp 0.3s ease-in reverse';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// 全局手绘风格自定义确认弹窗
function showCustomConfirm(title, message, onYes, onNo = null) {
  const modal = document.getElementById('modal-confirm');
  document.getElementById('confirm-title').innerText = title;
  document.getElementById('confirm-message').innerText = message;
  
  const btnYes = document.getElementById('btn-confirm-yes');
  const btnNo = document.getElementById('btn-confirm-no');
  
  // 克隆节点清除旧事件
  const newYes = btnYes.cloneNode(true);
  const newNo = btnNo.cloneNode(true);
  btnYes.parentNode.replaceChild(newYes, btnYes);
  btnNo.parentNode.replaceChild(newNo, btnNo);
  
  modal.style.display = 'flex';
  
  newYes.addEventListener('click', () => {
    modal.style.display = 'none';
    if (onYes) onYes();
  });
  
  newNo.addEventListener('click', () => {
    modal.style.display = 'none';
    if (onNo) onNo();
  });
}

// 首次加载初始化
document.addEventListener('DOMContentLoaded', () => {
  initGlobalEvents();
  loadProjects();
  loadSettings();
});

// 初始化全局页面级事件监听
function initGlobalEvents() {
  // 顶栏按钮
  document.getElementById('btn-open-settings').addEventListener('click', () => openSettingsModal());
  document.getElementById('btn-settings-cancel').addEventListener('click', () => closeSettingsModal());
  document.getElementById('btn-settings-save').addEventListener('click', () => saveSettings());
  document.getElementById('btn-back-home').addEventListener('click', () => exitWorkspace());
  
  // 绑定设置测试连通性按钮
  document.getElementById('btn-test-llm').addEventListener('click', () => testLlmConnection());
  document.getElementById('btn-test-image').addEventListener('click', () => testImageConnection());
  document.getElementById('btn-test-tts').addEventListener('click', () => testTtsConnection());
  
  // 新建项目 Modal
  document.getElementById('btn-create-project').addEventListener('click', () => {
    document.getElementById('input-project-name').value = '';
    document.getElementById('input-project-desc').value = '';
    document.getElementById('modal-create').style.display = 'flex';
  });
  document.getElementById('btn-create-cancel').addEventListener('click', () => {
    document.getElementById('modal-create').style.display = 'none';
  });
  document.getElementById('btn-create-submit').addEventListener('click', () => createProject());

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
    item.addEventListener('click', () => {
      const step = parseInt(item.dataset.step);
      const stepStatus = state.currentProject.step_status;
      const currentStep = state.currentProject.current_step;
      // 解锁逻辑：
      // 1. 目标步骤小于等于当前进行中的步骤 (step <= currentStep)
      // 2. 目标步骤已经被标记完成 (completed) 或待重新确认 (pending_reconfirmation)
      // 3. 目标步骤的前一步已经完成或待确认 (说明下一步已解锁，支持点击)
      const isUnlocked = step <= currentStep
        || stepStatus[step.toString()] === 'completed'
        || stepStatus[step.toString()] === 'pending_reconfirmation'
        || (step > 1 && (stepStatus[(step - 1).toString()] === 'completed' || stepStatus[(step - 1).toString()] === 'pending_reconfirmation'));
      if (isUnlocked) {
        navigateToStep(step);
      } else {
        showToast(`⚠️ 请先完成前序步骤再进行第 ${step} 步操作`);
      }
    });
  });

  // 流水线中所有的“下一步”按钮
  document.querySelectorAll('.btn-next-step').forEach(btn => {
    btn.addEventListener('click', () => {
      if (state.currentStep === 3) {
        navigateToStep(5);
      } else if (state.currentStep < 8) {
        navigateToStep(state.currentStep + 1);
      }
    });
  });

  // ================= 步骤 1 事件 =================
  document.getElementById('step1-btn-submit').addEventListener('click', () => submitStep1());
  document.getElementById('step1-btn-save-edit').addEventListener('click', () => saveStep1Edit());

  // ================= 步骤 2 事件 =================
  document.getElementById('step2-btn-generate').addEventListener('click', () => generateStep2Contract());
  document.getElementById('step2-btn-save').addEventListener('click', () => handleStep2BatchDeleteButton());
  document.getElementById('step2-btn-cancel-delete')?.addEventListener('click', () => cancelStep2BatchDelete());
  document.getElementById('step2-core-message')?.addEventListener('input', (e) => updateCurrentSlideField('core_message', e.target.value));

  // ================= 步骤 3 事件 =================
  document.getElementById('step3-btn-generate').addEventListener('click', () => generateStep3Image());
  document.getElementById('step3-file-upload').addEventListener('change', (e) => uploadStep3Image(e));
  document.getElementById('step3-batch-upload').addEventListener('change', (e) => handleStep3BatchUpload(e));
  document.getElementById('step3-btn-copy-prompts').addEventListener('click', () => copyStep2Prompts());
  document.getElementById('step3-btn-confirm').addEventListener('click', () => confirmStep3Images());

  // ================= 步骤 4 事件 =================
  document.getElementById('step4-btn-confirm').addEventListener('click', () => confirmStep4Images());

  // ================= 步骤 5 事件 =================
  document.getElementById('step5-btn-semantic-blocks')?.addEventListener('click', () => runStep5SemanticBlocks());
  document.getElementById('step5-btn-automask').addEventListener('click', () => runStep5AutoMask());
  document.getElementById('step5-btn-new-block')?.addEventListener('click', () => createCurrentSlideBlock());
  document.getElementById('step5-btn-clear-current')?.addEventListener('click', () => clearAllMaskAnnotations());
  document.getElementById('step5-btn-save').addEventListener('click', () => saveStep5Masks());
  document.getElementById('step5-brush-size')?.addEventListener('input', (e) => updateBrushSize(e.target.value));
  document.getElementById('btn-narration-picker-cancel')?.addEventListener('click', () => closeNarrationPicker());
  document.getElementById('btn-narration-picker-confirm')?.addEventListener('click', () => confirmNarrationPicker());

  // ================= 步骤 6 事件 =================
  document.getElementById('step6-btn-init').addEventListener('click', () => initStep6Narration());
  document.getElementById('step6-btn-save').addEventListener('click', () => saveStep6Narration());

  // ================= 步骤 7 事件 =================
  document.getElementById('step7-btn-synthesize').addEventListener('click', () => runStep7TTS());

  // ================= 步骤 8 事件 =================
  document.getElementById('step8-btn-render').addEventListener('click', () => runStep8Render());
  document.getElementById('step8-btn-finish').addEventListener('click', () => exitWorkspace());
}

// ==================== 项目管理与系统设置逻辑 ====================

async function loadProjects() {
  const data = await API.get('/api/projects');
  const listEl = document.getElementById('project-list');
  listEl.innerHTML = '';
  
  if (data.length === 0) {
    listEl.innerHTML = `
      <div class="card sketch-dashed" style="text-align: center; padding: 4rem 2rem; grid-column: 1/-1;">
        <p style="font-size: 1.2rem; margin-bottom: 1rem;">还没有项目，快去新建一个吧！</p>
        <button onclick="document.getElementById('btn-create-project').click()">立即新建</button>
      </div>`;
    return;
  }
  
  data.forEach(p => {
    // 计算已完成步骤百分比
    const status = p.step_status || {};
    let completedCount = 0;
    for (let i = 1; i <= 8; i++) {
      if (status[i.toString()] === 'completed') completedCount++;
    }
    const percent = Math.round((completedCount / 8) * 100);
    
    // 检查是否有后续步骤标记为待重新确认
    let hasPendingReconfirm = false;
    for (let key in status) {
      if (status[key] === 'pending_reconfirmation') {
        hasPendingReconfirm = true;
        break;
      }
    }
    
    const card = document.createElement('div');
    card.className = 'project-card sketch-shadow';
    card.innerHTML = `
      <div>
        <div class="project-card-header">
          <h3 class="highlight-title">${p.name}</h3>
        </div>
        <p style="color: #666; font-size: 0.95rem; min-height: 40px; margin-bottom: 0.5rem;">${p.description || '无项目描述'}</p>
        <div style="font-size: 0.9rem; margin-top: 0.5rem;">
          <div>当前步骤: <strong>第 ${p.current_step} 步</strong></div>
          ${hasPendingReconfirm ? '<div style="color: #c9a002; font-weight: bold;">⚠️ 有步骤待重新确认</div>' : ''}
        </div>
      </div>
      <div>
        <div class="project-progress-bar">
          <div class="project-progress-fill" style="width: ${percent}%"></div>
        </div>
        <div style="text-align: right; font-size: 0.8rem; margin-top: 2px; color: #555;">完成度: ${percent}%</div>
        <div style="display: flex; gap: 0.8rem; margin-top: 1rem;">
          <button class="success" onclick="enterWorkspace('${p.id}')" style="flex: 1; justify-content: center; font-size: 0.95rem; padding: 0.4rem;">继续设计</button>
          <button class="danger" onclick="deleteProject('${p.id}')" style="font-size: 0.95rem; padding: 0.4rem 0.6rem;">
            <svg class="icon" viewBox="0 0 24 24" style="width: 16px; height: 16px;"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
          </button>
        </div>
      </div>
    `;
    listEl.appendChild(card);
  });
}

async function createProject() {
  const name = document.getElementById('input-project-name').value.trim();
  const desc = document.getElementById('input-project-desc').value.trim();
  
  if (!name) {
    showToast('⚠️ 请输入项目名称');
    return;
  }
  
  const res = await API.post('/api/projects', { name, description: desc });
  if (res.success) {
    document.getElementById('modal-create').style.display = 'none';
    showToast('🎉 项目新建成功！');
    enterWorkspace(res.project.id);
  }
}

async function deleteProject(id) {
  showCustomConfirm(
    '🗑️ 删除项目确认',
    '您确定要永久删除该项目及其所有的素材、视频文件吗？此操作不可逆！',
    async () => {
      const res = await API.delete(`/api/projects/${id}`);
      if (res.success) {
        showToast('🗑️ 项目删除成功');
        loadProjects();
      }
    }
  );
}

async function loadSettings() {
  state.settings = await API.get('/api/settings');
  
  // 填充设置输入框
  document.getElementById('setting-llm-base-url').value = state.settings.llm_base_url || '';
  document.getElementById('setting-llm-api-key').value = state.settings.llm_api_key || '';
  document.getElementById('setting-llm-model').value = state.settings.llm_model || '';
  document.getElementById('setting-vision-model').value = state.settings.vision_model || '';
  document.getElementById('setting-llm-temp').value = state.settings.llm_temperature || '0.7';
  
  document.getElementById('setting-image-base-url').value = state.settings.image_base_url || '';
  document.getElementById('setting-image-api-key').value = state.settings.image_api_key || '';
  document.getElementById('setting-image-model').value = state.settings.image_model || 'gpt-image-1';
  document.getElementById('setting-image-size').value = state.settings.image_size || '1024x1024';
  
  document.getElementById('setting-tts-endpoint').value = state.settings.tts_endpoint || '';
  document.getElementById('setting-tts-api-key').value = state.settings.tts_api_key || '';
  document.getElementById('setting-tts-model').value = state.settings.tts_model || '';
  document.getElementById('setting-tts-voice-id').value = state.settings.tts_voice_id || '';
  document.getElementById('setting-tts-speed').value = state.settings.tts_speed || '1.0';
  document.getElementById('setting-tts-volume').value = state.settings.tts_volume || '1.0';
  document.getElementById('setting-tts-pitch').value = state.settings.tts_pitch || '0';
}

function openSettingsModal() {
  document.getElementById('modal-settings').style.display = 'flex';
}

function closeSettingsModal() {
  document.getElementById('modal-settings').style.display = 'none';
}

async function saveSettings() {
  const settings = {
    llm_base_url: document.getElementById('setting-llm-base-url').value.trim(),
    llm_api_key: document.getElementById('setting-llm-api-key').value.trim(),
    llm_model: document.getElementById('setting-llm-model').value.trim(),
    vision_model: document.getElementById('setting-vision-model').value.trim(),
    llm_temperature: document.getElementById('setting-llm-temp').value.trim(),
    
    image_base_url: document.getElementById('setting-image-base-url').value.trim(),
    image_api_key: document.getElementById('setting-image-api-key').value.trim(),
    image_model: document.getElementById('setting-image-model').value.trim(),
    image_size: document.getElementById('setting-image-size').value.trim(),
    
    tts_endpoint: document.getElementById('setting-tts-endpoint').value.trim(),
    tts_api_key: document.getElementById('setting-tts-api-key').value.trim(),
    tts_model: document.getElementById('setting-tts-model').value.trim(),
    tts_voice_id: document.getElementById('setting-tts-voice-id').value.trim(),
    tts_speed: document.getElementById('setting-tts-speed').value.trim(),
    tts_volume: document.getElementById('setting-tts-volume').value.trim(),
    tts_pitch: document.getElementById('setting-tts-pitch').value.trim()
  };
  
  const res = await API.put('/api/settings', { settings });
  if (res.success) {
    state.settings = settings;
    closeSettingsModal();
    showToast('💾 系统全局设置保存成功');
  }
}

async function testLlmConnection() {
  const btn = document.getElementById('btn-test-llm');
  const originalHtml = btn.innerHTML;
  
  const payload = {
    base_url: document.getElementById('setting-llm-base-url').value.trim() || null,
    api_key: document.getElementById('setting-llm-api-key').value.trim(),
    model: document.getElementById('setting-llm-model').value.trim()
  };
  
  if (!payload.api_key) {
    showToast('⚠️ 请填写接口密钥 (API Key)');
    return;
  }
  if (!payload.model) {
    showToast('⚠️ 请填写文本模型');
    return;
  }
  
  btn.disabled = true;
  btn.innerHTML = '测试中...';
  
  try {
    const res = await API.post('/api/settings/test-llm', payload);
    if (res.success) {
      showToast('✅ ' + res.message);
    } else {
      showToast('❌ ' + res.message);
    }
  } catch (err) {
    showToast('❌ 测试请求发送失败: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
  }
}

async function testImageConnection() {
  const btn = document.getElementById('btn-test-image');
  const originalHtml = btn.innerHTML;
  
  const payload = {
    base_url: document.getElementById('setting-image-base-url').value.trim() || null,
    api_key: document.getElementById('setting-image-api-key').value.trim(),
    model: document.getElementById('setting-image-model').value.trim()
  };
  
  if (!payload.api_key) {
    showToast('⚠️ 请填写生图接口密钥 (API Key)');
    return;
  }
  if (!payload.model) {
    showToast('⚠️ 请填写生图模型');
    return;
  }
  
  btn.disabled = true;
  btn.innerHTML = '测试中...';
  
  try {
    const res = await API.post('/api/settings/test-image', payload);
    if (res.success) {
      showToast('✅ ' + res.message);
    } else {
      showToast('❌ ' + res.message);
    }
  } catch (err) {
    showToast('❌ 测试请求发送失败: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
  }
}

async function testTtsConnection() {
  const btn = document.getElementById('btn-test-tts');
  const originalHtml = btn.innerHTML;
  
  const payload = {
    endpoint: document.getElementById('setting-tts-endpoint').value.trim(),
    api_key: document.getElementById('setting-tts-api-key').value.trim(),
    model: document.getElementById('setting-tts-model').value.trim(),
    voice_id: document.getElementById('setting-tts-voice-id').value.trim()
  };
  
  if (!payload.endpoint) {
    showToast('⚠️ 请填写语音接口地址 (Endpoint)');
    return;
  }
  if (!payload.api_key) {
    showToast('⚠️ 请填写语音接口密钥 (API Key)');
    return;
  }
  if (!payload.model) {
    showToast('⚠️ 请填写语音模型');
    return;
  }
  if (!payload.voice_id) {
    showToast('⚠️ 请填写音色标识');
    return;
  }
  
  btn.disabled = true;
  btn.innerHTML = '测试中...';
  
  try {
    const res = await API.post('/api/settings/test-tts', payload);
    if (res.success) {
      showToast('✅ ' + res.message);
    } else {
      showToast('❌ ' + res.message);
    }
  } catch (err) {
    showToast('❌ 测试请求发送失败: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
  }
}

function copyLlmUrlToImage() {
  const llmUrl = document.getElementById('setting-llm-base-url').value.trim();
  if (!llmUrl) {
    showToast('请先填写文本模型的接口地址');
    return;
  }
  document.getElementById('setting-image-base-url').value = llmUrl;
  showToast('✅ 已将文本模型 Base URL 同步到图片生成配置');
}

// ==================== 工作区视图控制逻辑 ====================

async function enterWorkspace(projectId) {
  const project = await API.get(`/api/projects/${projectId}`);
  state.currentProject = project;
  
  // 顶栏切换
  document.getElementById('project-info-header').style.display = 'block';
  document.getElementById('current-project-name').innerText = project.name;
  document.getElementById('btn-back-home').style.display = 'block';
  
  // 页面切换
  document.getElementById('page-home').style.display = 'none';
  document.getElementById('page-workspace').style.display = 'flex';
  
  // 加载步骤状态并导航至当前步骤
  updateStepperUI(project.current_step, project.step_status);
  navigateToStep(project.current_step);
}

function exitWorkspace() {
  document.getElementById('project-info-header').style.display = 'none';
  document.getElementById('btn-back-home').style.display = 'none';
  document.getElementById('page-workspace').style.display = 'none';
  document.getElementById('page-home').style.display = 'block';
  
  state.currentProject = null;
  loadProjects();
}

function updateStepperUI(currentStep, stepStatus) {
  const stepItems = document.querySelectorAll('.step-item');
  stepItems.forEach(item => {
    const step = parseInt(item.dataset.step);
    item.className = 'step-item'; // 重置
    
    if (step === currentStep) {
      item.classList.add('active');
    }
    
    const status = stepStatus[step.toString()];
    if (status === 'completed') {
      item.classList.add('completed');
    } else if (status === 'pending_reconfirmation') {
      item.classList.add('pending_reconfirmation');
      // 可以在此处插入一个状态角标
      let badge = item.querySelector('.step-status-tag');
      if (!badge) {
        badge = document.createElement('span');
        badge.className = 'step-status-tag';
        item.appendChild(badge);
      }
      badge.innerText = '待确认';
    } else {
      const badge = item.querySelector('.step-status-tag');
      if (badge) badge.remove();
    }
  });
}

// 步骤面板切换
async function navigateToStep(step) {
  state.currentStep = step;
  
  // 隐藏所有面板
  document.querySelectorAll('.step-panel').forEach(panel => panel.style.display = 'none');
  
  // 显示指定步骤面板
  const panel = document.getElementById(`step-panel-${step}`);
  if (panel) panel.style.display = 'block';
  
  // 刷新左侧步骤条高亮，若当前步骤有改动则进行同步
  if (state.currentProject && state.currentProject.current_step !== step) {
    // 更新数据库步骤与后处理状态
    const res = await API.get(`/api/projects/${state.currentProject.id}`);
    state.currentProject = res;
  }
  updateStepperUI(step, state.currentProject.step_status);
  
  // 针对特定步骤加载结果数据
  loadStepData(step);
}

function loadStepData(step) {
  switch (step) {
    case 1:
      loadStep1Data();
      break;
    case 2:
      loadStep2Data();
      break;
    case 3:
      loadStep3Data();
      break;
    case 4:
      loadStep4Data();
      break;
    case 5:
      loadStep5Data();
      break;
    case 6:
      loadStep6Data();
      break;
    case 7:
      loadStep7Data();
      break;
    case 8:
      loadStep8Data();
      break;
  }
}

// ==================== 步骤 1: 导入文章 ====================

async function loadStep1Data() {
  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/1/result`);
  if (res.success && res.brief) {
    document.getElementById('step1-article-input').value = res.brief.content || '';
    document.getElementById('step1-res-title').value = res.brief.title || '';
    document.getElementById('step1-res-summary').value = res.brief.summary || '';
    document.getElementById('step1-result-box').style.display = 'block';
  } else {
    document.getElementById('step1-article-input').value = '';
    document.getElementById('step1-result-box').style.display = 'none';
    const hint = document.getElementById('step1-status-hint');
    if (hint) hint.innerText = '';
    const saveEditBtn = document.getElementById('step1-btn-save-edit');
    if (saveEditBtn) saveEditBtn.style.display = 'none';
  }
}

async function submitStep1() {
  const content = document.getElementById('step1-article-input').value.trim();
  if (!content) {
    showToast('⚠️ 请输入 Markdown 文章内容');
    return;
  }
  const submitBtn = document.getElementById('step1-btn-submit');
  const origHtml = submitBtn.innerHTML;
  submitBtn.disabled = true;
  submitBtn.innerHTML = '保存中...';
  showToast('🚀 正在保存文章，请稍候...');
  const formData = new FormData();
  formData.append('content', content);
  
  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/1/import`, formData);
    if (res.success) {
      showToast('✨ 文章已保存，正在进入分镜规划...');
      document.getElementById('step1-res-title').value = res.brief.title;
      document.getElementById('step1-res-summary').value = res.brief.summary || '';
      document.getElementById('step1-result-box').style.display = 'none';
      const hint = document.getElementById('step1-status-hint');
      if (hint) hint.innerText = '✅ 文章已保存，已自动进入分镜规划';
      document.getElementById('step1-btn-save-edit').style.display = 'inline-flex';
      state.currentProject.current_step = Math.max(state.currentProject.current_step, 2);
      state.currentProject.step_status['1'] = 'completed';
      updateStepperUI(1, state.currentProject.step_status);
      setTimeout(() => {
        navigateToStep(2);
      }, 500);
    }
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = origHtml;
  }
}

async function saveStep1Edit() {
  const title = document.getElementById('step1-res-title').value.trim();
  const summary = document.getElementById('step1-res-summary').value.trim();
  const content = document.getElementById('step1-article-input').value.trim();
  const payload = { title: state.currentProject?.name || title, summary, content };
  const res = await API.put(`/api/projects/${state.currentProject.id}/steps/1/result`, payload);
  if (res.success) {
    showToast('💾 修改已保存');
  }
}

async function loadStep2Data() {
  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/2/result`);
  if (res.success && res.contract) {
    state.slides = res.contract.slides || [];
    state.step2BatchDeleteMode = false;
    state.step2DeleteSelection = new Set();
    state.step2BatchOriginalSlides = null;
    renderStep2Workspace();
  } else {
    state.slides = [];
    state.step2BatchDeleteMode = false;
    state.step2DeleteSelection = new Set();
    state.step2BatchOriginalSlides = null;
    document.getElementById('step2-editor-area').style.display = 'none';
    document.getElementById('step2-btn-generate').style.display = 'inline-flex';
    document.getElementById('step2-btn-generate').innerHTML = `<svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg> 智能规划分镜`;
    document.getElementById('step2-btn-save').style.display = 'none';
    document.getElementById('step2-btn-next').style.display = 'none';
    updateStep2AutosaveStatus('');
  }
}

async function generateStep2Contract() {
  document.getElementById('step2-loading').style.display = 'block';
  document.getElementById('step2-btn-generate').disabled = true;
  
  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/2/execute`);
    if (res.success) {
      showToast('🎉 分镜规划已生成！');
      state.slides = res.contract.slides || [];
      renderStep2Workspace();
    }
  } catch(e) {
    // 捕获报错
  } finally {
    document.getElementById('step2-loading').style.display = 'none';
    document.getElementById('step2-btn-generate').disabled = false;
  }
}

function renderStep2Workspace() {
  if (state.activeSlideIndex >= state.slides.length) {
    state.activeSlideIndex = Math.max(0, state.slides.length - 1);
  }
  document.getElementById('step2-editor-area').style.display = 'block';
  document.getElementById('step2-btn-generate').innerHTML = `<svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg> 重新规划分镜`;
  document.getElementById('step2-btn-save').style.display = 'inline-flex';
  document.getElementById('step2-btn-next').style.display = 'inline-flex';
  updateStep2BatchDeleteButton();
  
  // 渲染精简版横向缩略图（只显示 Slide 编号+主标题）
  const thumbsContainer = document.getElementById('step2-thumbs');
  thumbsContainer.style.display = 'flex'; // 显式呈现
  thumbsContainer.classList.toggle('step2-batch-delete-mode', state.step2BatchDeleteMode);
  thumbsContainer.innerHTML = '';
  
  state.slides.forEach((slide, idx) => {
    const thumb = document.createElement('div');
    thumb.className = `slide-thumbnail-card step2-slide-thumb ${idx === state.activeSlideIndex ? 'active' : ''}`;
    thumb.style.cssText = 'min-width: 90px; max-width: 110px; padding: 0.4rem 0.5rem; cursor: pointer;';
    thumb.innerHTML = `
      ${state.step2BatchDeleteMode ? `
        <button class="step2-thumb-delete" type="button" title="删除此分镜" aria-label="删除此分镜">
          <svg class="icon" viewBox="0 0 24 24"><path d="M18 6 6 18"></path><path d="m6 6 12 12"></path></svg>
        </button>
      ` : ''}
      <div style="font-size: 0.7rem; font-weight: bold; color: #888; margin-bottom: 2px;">${slide.slide_id}</div>
      <div style="font-size: 0.8rem; font-weight: bold; color: #111; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${slide.main_title || '无标题'}</div>
    `;
    thumb.addEventListener('click', () => {
      if (state.step2BatchDeleteMode) {
        return;
      }
      saveCurrentSlideInputToState();
      state.activeSlideIndex = idx;
      renderStep2Workspace();
    });
    const deleteBtn = thumb.querySelector('.step2-thumb-delete');
    if (deleteBtn) {
      deleteBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        removeStep2DraftSlide(slide.slide_id);
      });
    }
    thumbsContainer.appendChild(thumb);
  });
  
  // 加载当前 Slide 详情（只展示 core_message + visual_groups）
  const slide = state.slides[state.activeSlideIndex];
  if (slide) {
    const slideIdEl = document.getElementById('step2-current-slide-id');
    const slideTitleEl = document.getElementById('step2-current-slide-title');
    if (slideIdEl) slideIdEl.innerText = slide.slide_id;
    if (slideTitleEl) slideTitleEl.innerText = slide.main_title ? `「${slide.main_title}」` : '';
    // 同步隐藏字段
    document.getElementById('step2-main-title').value = slide.main_title || '';
    document.getElementById('step2-subtitle').value = slide.subtitle || '';
    document.getElementById('step2-core-message').value = slide.core_message || '';
    
    // 渲染 visual_groups 属性编辑
    const groupsList = document.getElementById('step2-groups-list');
    groupsList.innerHTML = '';
    
    slide.visual_groups.forEach((group, gIdx) => {
      // 过滤不需要展示的 body_group_02
      if (group.id === 'body_group_02') return;

      const groupEl = document.createElement('div');
      groupEl.className = 'sketch-dashed';
      groupEl.style.cssText = 'padding: 0.8rem; background: #fff; margin-bottom: 0.6rem; border-radius: 8px;';
      
      const roleMap = {
        'title': '标题',
        'subtitle': '副标题',
        'content_body': '正文',
        'diagram': '图解',
        'summary': '总结',
        'annotation': '批注',
        'decoration': '装饰'
      };
      const chineseRole = roleMap[group.role] || group.role || '元素';

      groupEl.innerHTML = `
        <div style="display: flex; align-items: center; margin-bottom: 0.6rem;">
          <span style="font-size: 0.8rem; font-weight: bold; color: var(--ink-color); background: var(--primary-color); border: 2px solid var(--ink-color); border-radius: 4px; padding: 2px 8px; box-shadow: 1px 1px 0px 0px var(--ink-color);">${chineseRole}</span>
        </div>
        <div style="margin-bottom: 0.5rem;">
          <label style="font-size: 0.8rem; font-weight: bold; display: block; margin-bottom: 0.2rem; color: #555;">画面显示中文：</label>
          <input type="text" value="${escHtml(group.visible_text)}" placeholder="请输入页面上显示的中文文字" style="font-size: 0.85rem; padding: 4px 8px;" oninput="updateGroupField(${gIdx}, 'visible_text', this.value)">
        </div>
        <div>
          <label style="font-size: 0.8rem; font-weight: bold; display: block; margin-bottom: 0.2rem; color: #555;">线稿视觉描述：</label>
          <input type="text" value="${escHtml(group.visual_anchor)}" placeholder="请输入线稿画面的视觉描述元素" style="font-size: 0.85rem; padding: 4px 8px; color: #444;" oninput="updateGroupField(${gIdx}, 'visual_anchor', this.value)">
        </div>
      `;
      groupsList.appendChild(groupEl);
    });
  }
}

// 拼接并一键复制所有 Slide 的生图提示词
function copyStep2Prompts() {
  saveCurrentSlideInputToState();
  
  if (!state.slides || state.slides.length === 0) {
    showToast('⚠️ 暂无分镜规划数据，无法复制提示词');
    return;
  }
  
  const topicName = state.currentProject.name;
  let textParts = [];
  
  state.slides.forEach((slide) => {
    const mainTitle = slide.main_title || '';
    const subtitle = slide.subtitle || '';
    const anchors = [];
    
    (slide.visual_groups || []).forEach(g => {
      // 过滤掉 title / subtitle 角色和不希望展示的 body_group_02，防止打乱提示词
      if (g.role !== 'title' && g.role !== 'subtitle' && g.id !== 'body_group_02') {
        if (g.visible_text && g.visual_anchor) {
          anchors.push(`${g.visible_text}(${g.visual_anchor})`);
        } else if (g.visible_text) {
          anchors.push(g.visible_text);
        } else if (g.visual_anchor) {
          anchors.push(g.visual_anchor);
        }
      }
    });
    
    const anchorsStr = anchors.join('，');
    
    // 结合项目风格与线稿风预设拼接 Prompt 
    const prompt = `A warm, minimalist, hand-drawn vector line art style presentation slide for topic '${topicName}'. ` +
      `Title: '${mainTitle}'. ` +
      (subtitle ? `Subtitle: '${subtitle}'. ` : '') +
      `The slide contains the following visual elements and concepts: ${anchorsStr}. ` +
      `Uniform pure beige background #FFFDF7. Reserve the bottom 150 px subtitle-safe zone on a 1920x1080 canvas (y=930..1080): keep it clean with no important text, labels, faces, or key drawings. ` +
      `Ink black lines (#111111), fine rough hand-drawn strokes. ` +
      `Subtle single accent yellow highlight (#F9D65C) on key concepts. ` +
      `Minimalist whiteboard drawing, korean line art webtoon style, cute hand sketch, no shadows, no gradients.`;
      
    textParts.push(`--- Slide ${slide.slide_id} ---`);
    textParts.push(prompt);
    textParts.push(''); // 空行
  });
  
  const allPromptsText = textParts.join('\n');
  
  navigator.clipboard.writeText(allPromptsText).then(() => {
    showToast('📋 已成功复制所有 Slide 的生图提示词到剪贴板！');
  }).catch(err => {
    console.error('复制失败:', err);
    showToast('⚠️ 复制失败，请手动选择复制');
  });
}

function escHtml(str) {
  if (!str) return '';
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function updateStep2BatchDeleteButton() {
  const btn = document.getElementById('step2-btn-save');
  const cancelBtn = document.getElementById('step2-btn-cancel-delete');
  if (!btn) return;
  if (state.step2BatchDeleteMode) {
    btn.className = 'success';
    btn.innerHTML = `
      <svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg>
      保存
    `;
    if (cancelBtn) cancelBtn.style.display = 'inline-flex';
  } else {
    btn.className = 'secondary';
    btn.innerHTML = `
      <svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;"><path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="M19 6l-1 14H6L5 6"></path></svg>
      批量删除
    `;
    if (cancelBtn) cancelBtn.style.display = 'none';
  }
}

async function handleStep2BatchDeleteButton() {
  if (!state.slides || state.slides.length === 0) return;
  if (!state.step2BatchDeleteMode) {
    saveCurrentSlideInputToState();
    clearTimeout(state.step2AutoSaveTimer);
    await saveStep2Contract({ silent: true });
    state.step2BatchOriginalSlides = JSON.parse(JSON.stringify(state.slides));
    state.step2BatchOriginalActiveIndex = state.activeSlideIndex;
    state.step2BatchDeleteMode = true;
    state.step2DeleteSelection = new Set();
    renderStep2Workspace();
    showToast('已进入批量删除模式。点卡片右上角删除，此处只临时移除，点击保存后生效。');
    return;
  }
  saveStep2BatchDelete();
}

function removeStep2DraftSlide(slideId) {
  if (!state.step2BatchDeleteMode) return;
  if (state.slides.length <= 1) {
    showToast('至少需要保留 1 个分镜。');
    return;
  }
  const removedIndex = state.slides.findIndex(slide => slide.slide_id === slideId);
  if (removedIndex < 0) return;
  state.slides.splice(removedIndex, 1);
  if (state.activeSlideIndex >= state.slides.length) {
    state.activeSlideIndex = state.slides.length - 1;
  } else if (removedIndex < state.activeSlideIndex) {
    state.activeSlideIndex -= 1;
  }
  renderStep2Workspace();
}

async function saveStep2BatchDelete() {
  saveCurrentSlideInputToState();
  clearTimeout(state.step2AutoSaveTimer);
  const originalCount = state.step2BatchOriginalSlides?.length || state.slides.length;
  const removedCount = Math.max(0, originalCount - state.slides.length);
  if (removedCount === 0) {
    state.step2BatchDeleteMode = false;
    state.step2BatchOriginalSlides = null;
    renderStep2Workspace();
    showToast('已退出批量删除模式。');
    return;
  }
  state.step2BatchDeleteMode = false;
  state.step2DeleteSelection = new Set();
  state.step2BatchOriginalSlides = null;
  await saveStep2Contract({ silent: true });
  renderStep2Workspace();
  showToast(`已删除 ${removedCount} 个分镜，并保存当前规划。`);
}

function cancelStep2BatchDelete() {
  if (!state.step2BatchDeleteMode) return;
  if (Array.isArray(state.step2BatchOriginalSlides)) {
    state.slides = JSON.parse(JSON.stringify(state.step2BatchOriginalSlides));
    state.activeSlideIndex = Math.min(state.step2BatchOriginalActiveIndex || 0, Math.max(0, state.slides.length - 1));
  }
  state.step2BatchDeleteMode = false;
  state.step2DeleteSelection = new Set();
  state.step2BatchOriginalSlides = null;
  renderStep2Workspace();
  showToast('已取消批量删除，分镜列表已恢复。');
}

function updateStep2AutosaveStatus(text) {
  const el = document.getElementById('step2-autosave-status');
  if (el) el.innerText = text || '';
}

function scheduleStep2AutoSave() {
  if (state.currentStep !== 2 || !state.currentProject || !state.slides?.length) return;
  if (state.step2BatchDeleteMode) return;
  updateStep2AutosaveStatus('自动保存中...');
  clearTimeout(state.step2AutoSaveTimer);
  state.step2AutoSaveTimer = setTimeout(() => {
    saveStep2Contract({ silent: true, autosave: true });
  }, 700);
}

function updateCurrentSlideField(field, val) {
  const slide = state.slides[state.activeSlideIndex];
  if (slide) {
    slide[field] = val;
    scheduleStep2AutoSave();
  }
}

function updateGroupField(gIdx, field, val) {
  const slide = state.slides[state.activeSlideIndex];
  if (slide && slide.visual_groups[gIdx]) {
    slide.visual_groups[gIdx][field] = val;
    scheduleStep2AutoSave();
  }
}

function saveCurrentSlideInputToState() {
  const slide = state.slides[state.activeSlideIndex];
  if (slide) {
    slide.main_title = document.getElementById('step2-main-title').value;
    slide.subtitle = document.getElementById('step2-subtitle').value;
    slide.core_message = document.getElementById('step2-core-message').value;
  }
}

async function saveStep2Contract(options = {}) {
  saveCurrentSlideInputToState();
  const payload = {
    version: "visual_contract_v1",
    topic: state.currentProject.topic || {
      topic_id: "topic_" + state.currentProject.id,
      topic_name: state.currentProject.name
    },
    slides: state.slides
  };
  
  if (state.step2AutoSaveInFlight && options.autosave) {
    scheduleStep2AutoSave();
    return { success: false };
  }
  state.step2AutoSaveInFlight = true;
  try {
    const res = await API.put(`/api/projects/${state.currentProject.id}/steps/2/result`, payload);
    if (res.success) {
      updateStep2AutosaveStatus(options.autosave ? '已自动保存' : '');
      if (!options.silent) {
        showToast('💾 分镜规划已成功保存！');
      }
    }
    return res;
  } finally {
    state.step2AutoSaveInFlight = false;
    if (options.autosave) {
      setTimeout(() => updateStep2AutosaveStatus(''), 1400);
    }
  }
}

// ==================== 步骤 3: 图片生成 ====================

let slidePrompts = [];
// 全局图片顺序（用于拖拽排序）
let step3ImageOrder = []; // [{slide_id, exists, url}]

async function loadStep3Data() {
  // 优先加载分镜数据，保证即使无图片也能渲染占位卡
  if (!state.slides || state.slides.length === 0) {
    const contractRes = await API.get(`/api/projects/${state.currentProject.id}/steps/2/result`);
    if (contractRes.success && contractRes.contract) {
      state.slides = contractRes.contract.slides || [];
    }
  }

  // 获取每个 slide 拼接的 Prompt
  try {
    const promptRes = await API.get(`/api/projects/${state.currentProject.id}/steps/3/prompts`);
    if (promptRes.success) slidePrompts = promptRes.prompts || [];
  } catch(e) {}
  
  // 获取生成的图片文件状态
  refreshStep3Images();
}

async function refreshStep3Images() {
  let images = [];
  try {
    const res = await API.get(`/api/projects/${state.currentProject.id}/steps/3/images`);
    if (res.success) images = res.images || [];
  } catch(e) {}

  // 如果后端返回空列表但分镜数据已有，自动生成占位展示
  if (images.length === 0 && state.slides && state.slides.length > 0) {
    images = state.slides.map(s => ({ slide_id: s.slide_id, exists: false, url: '' }));
  }
  step3ImageOrder = images;
  renderStep3Grid();
}

function renderStep3Grid() {
  const grid = document.getElementById('step3-images-grid');
  if (!grid) return;
  grid.innerHTML = '';

  const hasAnyImage = step3ImageOrder.some(img => img.exists);
  const confirmBtn = document.getElementById('step3-btn-confirm');
  if (confirmBtn) confirmBtn.style.display = hasAnyImage ? 'inline-flex' : 'none';

  step3ImageOrder.forEach((img, idx) => {
    const card = document.createElement('div');
    card.className = 'card sketch-shadow slide-card-draggable';
    card.setAttribute('draggable', 'true');
    card.style.cssText = 'padding: 0.8rem; position: relative; cursor: grab; background: var(--bg-color); margin-bottom: 0;';

    // 拖拽事件注册
    card.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', idx);
      card.style.opacity = '0.4';
      card.style.border = '2px dashed var(--ink-color)';
    });

    card.addEventListener('dragover', (e) => {
      e.preventDefault(); // 允许放置
    });

    card.addEventListener('drop', (e) => {
      e.preventDefault();
      const draggedIdx = parseInt(e.dataTransfer.getData('text/plain'));
      const targetIdx = idx;
      if (draggedIdx !== targetIdx && !isNaN(draggedIdx)) {
        const temp = step3ImageOrder[draggedIdx];
        step3ImageOrder.splice(draggedIdx, 1);
        step3ImageOrder.splice(targetIdx, 0, temp);
        renderStep3Grid();
        showToast('🔀 顺序已调整，请点击“确认所有图片”自动重新命名绑定');
      }
    });

    card.addEventListener('dragend', () => {
      card.style.opacity = '1';
      card.style.border = '2px solid var(--ink-color)';
    });

    const previewHtml = img.exists
      ? `<img src="${img.url}" style="width: 100%; height: 100%; object-fit: cover;" title="点击预览并编辑此张 Slide">`
      : `<div style="width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 0.3rem; color: #888; background: #fffdf5;">
           <svg class="icon" viewBox="0 0 24 24" style="width: 20px; height: 20px; color: #aaa;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"></path></svg>
           <span style="font-size: 0.75rem; font-weight: 500;">暂无图片，点击上传/生成</span>
         </div>`;

    card.innerHTML = `
      <!-- 头部： slide 编号与控制按钮 -->
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.6rem;">
        <div style="display: flex; align-items: center; gap: 0.3rem;">
          <span style="font-weight: bold; font-size: 0.95rem; color: var(--ink-color);">${img.slide_id}</span>
          <span style="font-size: 0.72rem; font-weight: bold; color: ${img.exists ? 'var(--ink-color)' : '#888'}; background: ${img.exists ? 'var(--success-color)' : '#f3f4f6'}; border: 1.5px solid var(--ink-color); border-radius: 4px; padding: 1px 4px;">
            ${img.exists ? '已就绪' : '待生成'}
          </span>
        </div>
        <div style="display: flex; gap: 0.3rem; align-items: center;">
          <button class="success" style="font-size: 0.72rem; padding: 0.2rem 0.4rem; box-shadow: 1px 1px 0px 0px var(--ink-color); margin: 0;" onclick="event.stopPropagation(); openStep3AI('${img.slide_id}')">
            AI生成
          </button>
          <label class="btn secondary" style="font-size: 0.72rem; padding: 0.2rem 0.4rem; cursor: pointer; box-shadow: 1px 1px 0px 0px var(--ink-color); display: inline-flex; align-items: center; gap: 0.1rem; margin: 0;">
            上传
            <input type="file" accept="image/*" style="display: none;" onchange="uploadStep3ImageById('${img.slide_id}', this)">
          </label>
        </div>
      </div>

      <!-- 预览区 -->
      <div class="img-preview-container" style="width: 100%; aspect-ratio: 16/9; position: relative; border: 2px solid var(--ink-color); border-radius: 6px; overflow: hidden; background: #fffdf5; cursor: pointer;" onclick="openStep3AI('${img.slide_id}')">
        ${previewHtml}
      </div>
    `;
    grid.appendChild(card);
  });
}

function moveStep3Image(idx, direction) {
  const newIdx = idx + direction;
  if (newIdx < 0 || newIdx >= step3ImageOrder.length) return;
  const tmp = step3ImageOrder[idx];
  step3ImageOrder[idx] = step3ImageOrder[newIdx];
  step3ImageOrder[newIdx] = tmp;
  renderStep3Grid();
  showToast('🔀 顺序已调整，请点击“确认所有图片”自动重新命名绑定');
}

window.moveStep3Image = moveStep3Image;

function openStep3AI(slideId) {
  // 刷新当前激活的 slide并展开 AI 生成展板
  state.activeSlideIndex = step3ImageOrder.findIndex(img => img.slide_id === slideId);
  const editor = document.getElementById('step3-editor');
  editor.style.display = 'block';
  document.getElementById('step3-slide-id-label').innerText = slideId;
  const pInfo = slidePrompts.find(p => p.slide_id === slideId);
  document.getElementById('step3-prompt-input').value = pInfo ? pInfo.prompt : '';
  const imgInfo = step3ImageOrder.find(img => img.slide_id === slideId);
  const prevEl = document.getElementById('step3-preview-box');
  if (imgInfo && imgInfo.exists) {
    prevEl.innerHTML = `<img src="${imgInfo.url}" style="width:100%; height:100%; object-fit:contain;">`;
  } else {
    prevEl.innerHTML = '<span style="color: #888;">暂无图片</span>';
  }
  editor.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

window.openStep3AI = openStep3AI;

async function uploadStep3ImageById(slideId, input) {
  const file = input.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('slide_id', slideId);
  formData.append('file', file);
  showToast('📤 正在上传并裁剪为标准格式...');
  const res = await API.post(`/api/projects/${state.currentProject.id}/steps/3/upload`, formData);
  if (res.success) {
    showToast('🎉 图片上传成功！');
    refreshStep3Images();
  }
  input.value = '';
}

window.uploadStep3ImageById = uploadStep3ImageById;

// 批量上传处理
async function handleStep3BatchUpload(e) {
  const files = Array.from(e.target.files);
  if (files.length === 0) return;
  
  // 按分镜顺序逐一匹配上传
  const slideIds = step3ImageOrder.map(img => img.slide_id);
  showToast(`📤 正在批量上传 ${files.length} 张图片...`);
  
  for (let i = 0; i < files.length; i++) {
    const slideId = slideIds[i];
    if (!slideId) break;
    const formData = new FormData();
    formData.append('slide_id', slideId);
    formData.append('file', files[i]);
    try {
      await API.post(`/api/projects/${state.currentProject.id}/steps/3/upload`, formData);
    } catch(err) {
      showToast(`⚠️ 第 ${i+1} 张上传失败`);
    }
  }
  showToast('✅ 批量上传完成！');
  refreshStep3Images();
  e.target.value = '';
}


// AI 生成单张图片（来自 AI 展板的提交）
async function generateStep3Image() {
  const slideId = document.getElementById('step3-slide-id-label').innerText;
  const prompt = document.getElementById('step3-prompt-input').value.trim();
  
  if (!prompt) {
    showToast('⚠️ 提示词不能为空');
    return;
  }
  
  document.getElementById('step3-loading').style.display = 'block';
  document.getElementById('step3-btn-generate').disabled = true;
  showToast(`🎨 正在调用 ${state.settings?.image_model || 'gpt-image-1'} 合成 1536x1024 中...`);
  
  try {
    const formData = new FormData();
    formData.append('slide_id', slideId);
    formData.append('prompt', prompt);
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/3/generate`, formData);
    if (res.success) {
      showToast('🎉 图片生成并已缩放裁剪至 1920x1080！');
      refreshStep3Images();
    }
  } catch(e) {
  } finally {
    document.getElementById('step3-loading').style.display = 'none';
    document.getElementById('step3-btn-generate').disabled = false;
  }
}

// 单张上传（来自 AI 展板的上传按钮，绑定了 id=step3-file-upload 的 input change）
async function uploadStep3Image(e) {
  const slideId = document.getElementById('step3-slide-id-label').innerText;
  if (!slideId || slideId === '--') {
    showToast('⚠️ 请先点击某张 Slide 的 AI 生成面板再上传');
    return;
  }
  const file = e.target.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('slide_id', slideId);
  formData.append('file', file);
  showToast('📤 正在上传并裁剪为标准格式...');
  const res = await API.post(`/api/projects/${state.currentProject.id}/steps/3/upload`, formData);
  if (res.success) {
    showToast('🎉 图片上传成功！');
    refreshStep3Images();
    // 同步更新 AI 展板预览
    document.getElementById('step3-preview-box').innerHTML =
      `<img src="${res.url || ''}" style="width:100%; height:100%; object-fit:contain;">`;
  }
  e.target.value = '';
}

async function confirmStep3Images() {
  const res = await API.post(`/api/projects/${state.currentProject.id}/steps/3/confirm`);
  if (res.success) {
    const formData = new FormData();
    formData.append('target_step', '5');
    const navRes = await API.post(`/api/projects/${state.currentProject.id}/navigate`, formData);
    if (navRes.success) {
      showToast('🔒 所有图片已确认并锁定！进入标注阶段。');
      navigateToStep(5);
    }
  }
}

// ==================== 步骤 4: 图片审核确认 ====================

async function loadStep4Data() {
  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/3/images`);
  const grid = document.getElementById('step4-grid');
  grid.innerHTML = '';
  
  if (res.success) {
    res.images.forEach(img => {
      const card = document.createElement('div');
      card.className = 'card';
      card.style.padding = '0.5rem';
      card.innerHTML = `
        <div style="height: 140px; border: 1px solid #111; border-radius: 5px; background-color: #eee; overflow: hidden; margin-bottom: 0.5rem;">
          ${img.exists ? `<img src="${img.url}" style="width:100%; height:100%; object-fit:cover;">` : '<span style="color:#aaa; display:flex; align-items:center; justify-content:center; height:100%;">无图片</span>'}
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-weight:bold;">${img.slide_id}</span>
          <button class="secondary" style="font-size:0.8rem; padding: 2px 6px;" onclick="goToSlideStep3('${img.slide_id}')">🔄 重构</button>
        </div>
      `;
      grid.appendChild(card);
    });
  }
}

window.goToSlideStep3 = function(slideId) {
  // 查找 slideIndex 并在第3步渲染激活它
  const idx = state.slides.findIndex(s => s.slide_id === slideId);
  if (idx !== -1) {
    state.activeSlideIndex = idx;
    navigateToStep(3);
  }
};

async function confirmStep4Images() {
  const res = await API.post(`/api/projects/${state.currentProject.id}/steps/3/confirm`);
  if (res.success) {
    showToast('🔒 图片已锁定！坐标文件自动生成。接下来进入标注阶段。');
    navigateToStep(5);
  }
}

// ==================== 步骤 5: Mask 可视化标注 ====================

let manifestData = null;

let step2Contract = null; // 用于缓存步骤 2 分镜规划数据

const MASK_COLORS = [
  '#E84A5F',
  '#1B998B',
  '#F6AE2D',
  '#3D5A80',
  '#7B2CBF',
  '#2F80ED',
  '#D45113',
  '#4C956C',
  '#C9184A',
  '#0077B6'
];

function getMaskColor(idx) {
  return MASK_COLORS[idx % MASK_COLORS.length];
}

function getBoxColor(maskBox, idx) {
  return getMaskColor(idx);
}

function roleToSemanticLabel(role) {
  const roleName = String(role || '').toLowerCase();
  if (roleName === 'title') return '主标题';
  if (roleName === 'subtitle') return '副标题';
  if (roleName === 'summary') return '总结区';
  if (roleName === 'diagram') return '图示';
  if (roleName === 'annotation') return '注释';
  if (roleName === 'decoration') return '装饰元素';
  return '正文内容';
}

function hexToRgba(hex, alpha) {
  const clean = String(hex || '#111111').replace('#', '');
  const full = clean.length === 3 ? clean.split('').map(ch => ch + ch).join('') : clean;
  const num = parseInt(full, 16);
  if (Number.isNaN(num)) return `rgba(17, 17, 17, ${alpha})`;
  const r = (num >> 16) & 255;
  const g = (num >> 8) & 255;
  const b = num & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function cloneManualMask(mask) {
  if (!mask || typeof mask !== 'object') return { strokes: [] };
  return {
    color: mask.color || '',
    bounds: mask.bounds ? { ...mask.bounds } : null,
    strokes: Array.isArray(mask.strokes)
      ? mask.strokes.map(stroke => ({
          color: stroke.color || '',
          size: Number(stroke.size || 42),
          mode: stroke.mode || (stroke.eraser ? 'erase' : 'paint'),
          eraser: !!stroke.eraser,
          points: Array.isArray(stroke.points)
            ? stroke.points.map(point => ({
                x: Number(point.x || 0),
                y: Number(point.y || 0)
              }))
            : []
        }))
      : []
  };
}

function ensureManualMask(maskBox, idx = 0) {
  if (!maskBox.manual_mask || typeof maskBox.manual_mask !== 'object') {
    maskBox.manual_mask = { color: getMaskColor(idx), strokes: [] };
  }
  if (!Array.isArray(maskBox.manual_mask.strokes)) {
    maskBox.manual_mask.strokes = [];
  }
  maskBox.manual_mask.color = getMaskColor(idx);
  return maskBox.manual_mask;
}

function getCurrentManifestSlide() {
  return manifestData?.slides?.[state.activeSlideIndex] || null;
}

function getStep2SlideForManifestSlide(manifestSlide = getCurrentManifestSlide()) {
  if (!manifestSlide || !step2Contract?.slides) return null;
  return step2Contract.slides.find(s => s.slide_id === manifestSlide.slide_id) || null;
}

function splitNarrationText(text) {
  const value = String(text || '').trim();
  if (!value) return [];
  const parts = value.match(/[^，,。！？!?；;：:\n]+[，,。！？!?；;：:]?/g) || [value];
  return parts.map(part => part.trim()).filter(Boolean);
}

function getNarrationFragments(step2Slide = getStep2SlideForManifestSlide()) {
  const beats = step2Slide?.narration_beats || [];
  const fragments = [];
  beats.forEach((beat, beatIdx) => {
    splitNarrationText(beat.spoken_text || '').forEach((text, fragIdx) => {
      fragments.push({
        id: `${beat.id || `beat_${beatIdx + 1}`}::${fragIdx + 1}`,
        beat_id: beat.id || '',
        group_id: beat.group_id || '',
        beat_index: beatIdx,
        fragment_index: fragIdx,
        order: fragments.length + 1,
        text
      });
    });
  });
  return fragments;
}

function getSelectedFragmentIds(maskBox) {
  if (!maskBox) return [];
  if (Array.isArray(maskBox.narration_fragments) && maskBox.narration_fragments.length > 0) {
    return maskBox.narration_fragments.map(fragment => fragment.id).filter(Boolean);
  }
  return [];
}

function getSelectedFragmentText(maskBox, step2Slide = getStep2SlideForManifestSlide()) {
  if (!maskBox) return '';
  if (Array.isArray(maskBox.narration_fragments) && maskBox.narration_fragments.length > 0) {
    return maskBox.narration_fragments.map(fragment => fragment.text).filter(Boolean).join('');
  }
  const beat = getNarrationBeatForBox(maskBox, step2Slide);
  return maskBox.spoken_text || beat?.spoken_text || '';
}

function getNarrationBeatForBox(maskBox, step2Slide = getStep2SlideForManifestSlide()) {
  const beats = step2Slide?.narration_beats || [];
  if (!beats.length || !maskBox) return null;
  if (Array.isArray(maskBox.narration_beat_ids) && maskBox.narration_beat_ids.length > 0) {
    const byFirstId = beats.find(beat => beat.id === maskBox.narration_beat_ids[0]);
    if (byFirstId) return byFirstId;
  }
  if (maskBox.narration_beat_id) {
    const byId = beats.find(beat => beat.id === maskBox.narration_beat_id);
    if (byId) return byId;
  }
  if (maskBox.narration_group_id) {
    const byLinkedGroup = beats.find(beat => beat.group_id === maskBox.narration_group_id);
    if (byLinkedGroup) return byLinkedGroup;
  }
  return beats.find(beat => beat.group_id === maskBox.group_id) || null;
}

function isBeatLinkedToMaskBox(beat, maskBox) {
  if (!beat || !maskBox) return false;
  if (Array.isArray(maskBox.narration_beat_ids) && maskBox.narration_beat_ids.includes(beat.id)) return true;
  if (maskBox.narration_beat_id && beat.id === maskBox.narration_beat_id) return true;
  if (maskBox.narration_group_id && beat.group_id === maskBox.narration_group_id) return true;
  return beat.group_id === maskBox.group_id;
}

function isEraseStroke(stroke) {
  return !!stroke?.eraser || String(stroke?.mode || '').toLowerCase() === 'erase';
}

function hasPaintStroke(maskBox) {
  return (maskBox?.manual_mask?.strokes || []).some(stroke => !isEraseStroke(stroke) && (stroke.points || []).length > 0);
}

function isManualEmptyBox(maskBox) {
  return String(maskBox?.group_id || '').startsWith('manual_group_') && !hasPaintStroke(maskBox);
}

function isSemanticDraftBox(maskBox) {
  return String(maskBox?.source || '') === 'ai_semantic' && !hasPaintStroke(maskBox);
}

function isDraftMaskBox(maskBox) {
  return isManualEmptyBox(maskBox) || isSemanticDraftBox(maskBox);
}

function copySemanticFields(target, source) {
  if (!target || !source) return target;
  [
    'source',
    'visual_group_id',
    'semantic_element_type',
    'visual_description',
    'semantic_note',
    'semantic_confidence'
  ].forEach(field => {
    if (source[field] !== undefined && source[field] !== null && source[field] !== '') {
      target[field] = source[field];
    }
  });
  return target;
}

function groupToMaskBox(group) {
  const box = group.box || {};
  const x = Number(box.x || 0);
  const y = Number(box.y || 0);
  const w = Number(box.w || 1);
  const h = Number(box.h || 1);
  return copySemanticFields({
    group_id: group.id || group.group_id || '',
    role: group.role || 'content_body',
    text_label: group.visible_text || group.text_label || '',
    visual_anchor: group.visual_anchor || '',
    narration_beat_id: group.narration_beat_id || group.linked_segment_id || '',
    narration_beat_ids: Array.isArray(group.narration_beat_ids) ? [...group.narration_beat_ids] : [],
    narration_group_id: group.narration_group_id || '',
    narration_fragments: Array.isArray(group.narration_fragments) ? JSON.parse(JSON.stringify(group.narration_fragments)) : [],
    spoken_text: group.spoken_text || '',
    manual_mask: cloneManualMask(group.manual_mask),
    box: [x, y, x + w, y + h]
  }, group);
}

function normalizeRevealBox(box, idx) {
  return copySemanticFields({
    ...box,
    visual_anchor: box.visual_anchor || '',
    narration_beat_id: box.narration_beat_id || '',
    narration_beat_ids: Array.isArray(box.narration_beat_ids) ? [...box.narration_beat_ids] : [],
    narration_group_id: box.narration_group_id || '',
    narration_fragments: Array.isArray(box.narration_fragments) ? JSON.parse(JSON.stringify(box.narration_fragments)) : [],
    manual_mask: cloneManualMask(box.manual_mask || { color: getMaskColor(idx), strokes: [] })
  }, box);
}

function semanticBlockToMaskBox(box, idx) {
  return normalizeRevealBox({
    role: "content_body",
    text_label: `语块 ${idx + 1}`,
    visual_anchor: "",
    spoken_text: "",
    box: [860, 460, 1060, 620],
    ...box,
    source: "ai_semantic",
    manual_mask: cloneManualMask(box.manual_mask || { color: getMaskColor(idx), strokes: [] })
  }, idx);
}

function getSlideMaskBoxes(slide) {
  if (!slide) return [];
  const semanticBoxes = Array.isArray(slide.semantic_blocks)
    ? slide.semantic_blocks.map(semanticBlockToMaskBox)
    : [];
  const semanticIds = new Set(semanticBoxes.map(box => box.group_id).filter(Boolean));

  let baseBoxes = [];
  if (Array.isArray(slide.groups) && slide.groups.length > 0) {
    baseBoxes = slide.groups.map(groupToMaskBox);
  } else if (Array.isArray(slide.reveal_boxes) && slide.reveal_boxes.length > 0) {
    baseBoxes = JSON.parse(JSON.stringify(slide.reveal_boxes)).map(normalizeRevealBox);
  }

  const baseById = new Map(baseBoxes.map(box => [box.group_id, box]));
  const merged = semanticBoxes.map((semanticBox, idx) => {
    const existing = baseById.get(semanticBox.group_id);
    if (!existing) return semanticBlockToMaskBox(semanticBox, idx);
    return {
      ...semanticBox,
      ...existing,
      source: existing.source || semanticBox.source,
      visual_group_id: existing.visual_group_id || semanticBox.visual_group_id,
      semantic_element_type: existing.semantic_element_type || semanticBox.semantic_element_type,
      visual_description: existing.visual_description || semanticBox.visual_description,
      semantic_note: existing.semantic_note || semanticBox.semantic_note,
      semantic_confidence: existing.semantic_confidence || semanticBox.semantic_confidence,
      manual_mask: cloneManualMask(existing.manual_mask || semanticBox.manual_mask)
    };
  });
  baseBoxes.forEach(box => {
    if (!semanticIds.has(box.group_id)) merged.push(box);
  });
  return merged.map((box, idx) => ({
    ...box,
    manual_mask: {
      ...cloneManualMask(box.manual_mask || { strokes: [] }),
      color: getMaskColor(idx)
    }
  }));
}

function syncMaskBoxesToSlide(slide, boxes) {
  if (!slide) return;
  const readyBoxes = boxes.filter(maskBox => !isDraftMaskBox(maskBox));
  const semanticBoxes = boxes
    .filter(maskBox => String(maskBox?.source || '') === 'ai_semantic')
    .map((maskBox, idx) => ({
      ...maskBox,
      manual_mask: {
        ...cloneManualMask(maskBox.manual_mask || { strokes: [] }),
        color: getMaskColor(idx)
      }
    }));
  slide.semantic_blocks = JSON.parse(JSON.stringify(semanticBoxes));

  if (!Array.isArray(slide.groups)) {
    slide.groups = [];
  }
  const visibleGroupIds = new Set(readyBoxes.map(maskBox => maskBox.group_id).filter(Boolean));
  slide.groups = slide.groups.filter(group => visibleGroupIds.has(group.id || group.group_id));
  readyBoxes.forEach((maskBox, idx) => {
    ensureManualMask(maskBox, idx);
    const [rawX1, rawY1, rawX2, rawY2] = maskBox.box || [0, 0, 1, 1];
    const x1 = Math.max(0, Math.round(Math.min(rawX1, rawX2)));
    const y1 = Math.max(0, Math.round(Math.min(rawY1, rawY2)));
    const x2 = Math.min(1920, Math.round(Math.max(rawX1, rawX2)));
    const y2 = Math.min(1080, Math.round(Math.max(rawY1, rawY2)));
    let group = slide.groups.find(g => g.id === maskBox.group_id);
    if (!group) {
      group = {
        id: maskBox.group_id || `custom_group_${idx + 1}`,
        role: maskBox.role || 'content_body',
        visible_text: maskBox.text_label || '',
        reveal: { type: 'cover_fade_out', duration: 0.45 },
        padding_px: 32,
        z_index: 40 + idx
      };
      slide.groups.push(group);
    }
    group.role = maskBox.role || group.role || 'content_body';
    group.source = maskBox.source || group.source || '';
    if (maskBox.text_label) group.visible_text = maskBox.text_label;
    if (maskBox.visual_anchor) group.visual_anchor = maskBox.visual_anchor;
    if (maskBox.visual_group_id) group.visual_group_id = maskBox.visual_group_id;
    if (maskBox.semantic_element_type) group.semantic_element_type = maskBox.semantic_element_type;
    if (maskBox.visual_description) group.visual_description = maskBox.visual_description;
    if (maskBox.semantic_note) group.semantic_note = maskBox.semantic_note;
    if (maskBox.semantic_confidence) group.semantic_confidence = maskBox.semantic_confidence;
    if (maskBox.narration_beat_id) group.narration_beat_id = maskBox.narration_beat_id;
    group.narration_beat_ids = Array.isArray(maskBox.narration_beat_ids) ? [...maskBox.narration_beat_ids] : [];
    if (maskBox.narration_group_id) group.narration_group_id = maskBox.narration_group_id;
    group.narration_fragments = Array.isArray(maskBox.narration_fragments) ? JSON.parse(JSON.stringify(maskBox.narration_fragments)) : [];
    if (maskBox.spoken_text) group.spoken_text = maskBox.spoken_text;
    group.manual_mask = cloneManualMask(maskBox.manual_mask || { strokes: [] });
    group.manual_mask.color = getMaskColor(idx);
    if (group.manual_mask.strokes.length > 0) {
      group.review_status = "manual_painted";
    }
    group.box = {
      x: x1,
      y: y1,
      w: Math.max(1, x2 - x1),
      h: Math.max(1, y2 - y1)
    };
  });
  slide.reveal_boxes = JSON.parse(JSON.stringify(
    readyBoxes
      .map((maskBox, idx) => ({
        ...maskBox,
        manual_mask: {
          ...cloneManualMask(maskBox.manual_mask || { strokes: [] }),
          color: getMaskColor(idx)
        }
      }))
  ));
}

async function loadStep5Data() {
  try {
    const contractRes = await API.get(`/api/projects/${state.currentProject.id}/steps/2/result`);
    if (contractRes.success && contractRes.contract) {
      step2Contract = contractRes.contract;
    }
  } catch (e) {}

  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/5/result`);
  if (res.success && res.manifest) {
    manifestData = res.manifest;
    // 智能初始化每一页 slide 的状态并向下兼容
    manifestData.slides.forEach(s => {
      if (!s.status) {
        // 如果存在标注块尚未审核完成，则设为 pending，否则设为 completed
        const needsAdjustment = (s.groups || []).some(g => 
          g.review_status === "needs_manual_adjustment_after_image_gen" || 
          g.review_status === "auto_fitted_needs_review"
        );
        s.status = needsAdjustment ? "pending" : "completed";
      }
    });
    renderStep5Workspace();
  }
}

function renderStep5Workspace() {
  updateStep5AutoMaskButton();
  updateStep5SemanticButton();
  const thumbsContainer = document.getElementById('step5-thumbs');
  thumbsContainer.className = 'step5-slides-grid'; // 改用平铺换行类名
  thumbsContainer.innerHTML = '';
  
  manifestData.slides.forEach((slide, idx) => {
    const btn = document.createElement('div');
    const isCurrent = idx === state.activeSlideIndex;
    const isRunning = state.canvasState.autoMaskLoading && isCurrent;
    const isSemanticRunning = state.canvasState.semanticLoading && isCurrent;
    const isCompleted = slide.status === 'completed';
    
    let statusClass = '';
    let statusText = '待标注';
    let statusColor = '#888';
    
    if (isSemanticRunning) {
      statusClass = 'active';
      statusText = '分块中';
      statusColor = '#7b2cbf';
    } else if (isRunning) {
      statusClass = 'active';
      statusText = '框选中';
      statusColor = '#2f80ed';
    } else if (isCurrent) {
      statusClass = 'active';
      statusText = '标注中';
      statusColor = '#d29a00';
    } else if (isCompleted) {
      statusClass = 'completed';
      statusText = '已标注';
      statusColor = '#4caf50';
    }
    
    btn.className = `step5-slide-btn ${statusClass}`;
    btn.innerHTML = `
      <div style="font-size: 0.85rem; font-weight: bold; color: var(--ink-color);">${slide.slide_id}</div>
      <div style="font-size: 0.65rem; margin-top: 0.15rem; color: ${statusColor}; font-weight: 500;">
        ${statusText === '已标注' ? '✓ 已标注' : statusText === '分块中' ? '… 分块中' : statusText === '框选中' ? '… 框选中' : statusText === '标注中' ? '✍ 标注中' : '待标注'}
      </div>
    `;
    
    btn.addEventListener('click', () => {
      saveStep5CurrentState();
      state.activeSlideIndex = idx;
      renderStep5Workspace();
    });
    thumbsContainer.appendChild(btn);
  });
  
  // 加载当前 Slide 详情
  const slide = manifestData.slides[state.activeSlideIndex];
  if (slide) {
    // 设置 Canvas 背景图
    const imgUrl = `/api/projects/${state.currentProject.id}/slides/${slide.slide_id}/image?t=${uuid()}`;
    document.getElementById('step5-bg-img').src = imgUrl;
    
    // 初始化 canvas 标注框数据并重绘
    state.canvasState.boxes = getSlideMaskBoxes(slide);
    state.canvasState.selectedBoxIndex = -1;
    state.canvasState.draggedBoxIndex = -1;
    state.canvasState.draggedHandle = null;
    state.canvasState.paintMode = false;
    state.canvasState.eraserMode = false;
    state.canvasState.paintingBoxIndex = -1;
    state.canvasState.isPainting = false;
    state.canvasState.currentStroke = null;
    updateBrushSize(state.canvasState.brushSize, false);
    initCanvasEvents();
    redrawCanvas();
    
    // 渲染右侧属性列表
    renderStep5BoxesForm();
    renderStep5NarrationPanel();
  }
}

function uuid() {
  return Math.random().toString(36).substring(2, 6);
}

// 渲染右侧的 box 编辑表单列表
function renderStep5BoxesForm() {
  const container = document.getElementById('step5-boxes-list');
  container.innerHTML = '';
  const currentSlide = getCurrentManifestSlide();
  const step2Slide = getStep2SlideForManifestSlide(currentSlide);
  
  if (!state.canvasState.boxes.length) {
    container.innerHTML = `
      <div class="sketch-dashed mask-empty-state">
        当前页没有语义块。保存后将按整页展示处理；如果需要逐一呈现，请新建语块、选择旁白片段，再用同色画笔涂抹区域。
      </div>
    `;
    return;
  }

  state.canvasState.boxes.forEach((box, idx) => {
    const isSelected = idx === state.canvasState.selectedBoxIndex;
    const isPaintTarget = state.canvasState.paintMode && !state.canvasState.eraserMode && idx === state.canvasState.paintingBoxIndex;
    const isEraseTarget = state.canvasState.paintMode && state.canvasState.eraserMode && idx === state.canvasState.paintingBoxIndex;
    const item = document.createElement('div');
    item.className = `mask-block-card sketch-dashed${isSelected ? ' highlight-glow' : ''}${isPaintTarget ? ' paint-active' : ''}${isEraseTarget ? ' erase-active' : ''}`;
    const maskColor = getBoxColor(box, idx);
    item.style.setProperty('--mask-color', maskColor);

    const spokenText = getSelectedFragmentText(box, step2Slide);
    const strokes = box.manual_mask?.strokes || [];
    const paintCount = strokes.filter(stroke => !isEraseStroke(stroke)).length;
    const eraseCount = strokes.filter(stroke => isEraseStroke(stroke)).length;
    const strokeSummary = paintCount || eraseCount ? `画笔 ${paintCount} 笔 · 橡皮 ${eraseCount} 笔` : '可用画笔补正区域';
    const semanticType = box.semantic_element_type || roleToSemanticLabel(box.role);
    const visualDescription = box.visual_description || box.visual_anchor || '';
    const semanticNote = box.semantic_note || '';
    const visualCard = visualDescription || semanticNote ? `
      <div class="mask-visual-card">
        <span class="mask-visual-label">画面内容</span>
        <div class="mask-visual-title">${escHtml(semanticType || '可见元素')}</div>
        ${visualDescription ? `<div class="mask-visual-desc">${escHtml(visualDescription)}</div>` : ''}
        ${semanticNote ? `<div class="mask-visual-note">${escHtml(semanticNote)}</div>` : ''}
      </div>
    ` : '';
    
    item.innerHTML = `
      <div class="mask-block-head">
        <span class="mask-block-number">${idx + 1}</span>
        <span class="mask-block-caption">语块 ${idx + 1}</span>
        <button class="mask-icon-btn${isPaintTarget ? ' active' : ''}" type="button" data-action="paint" title="涂抹这个语块的 Mask 区域" aria-label="涂抹区域">
          <svg class="icon" viewBox="0 0 24 24"><path d="M12 20h9"></path><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"></path></svg>
        </button>
        <button class="mask-icon-btn${isEraseTarget ? ' active' : ''}" type="button" data-action="erase" title="擦除这个语块的涂抹区域" aria-label="擦除区域">
          <svg class="icon" viewBox="0 0 24 24"><path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21"></path><path d="M22 21H7"></path><path d="m5 11 9 9"></path></svg>
        </button>
        <button class="danger mask-icon-btn mask-delete-btn" type="button" data-action="delete" title="删除语块" aria-label="删除语块">
          <svg class="icon" viewBox="0 0 24 24"><path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="M19 6l-1 14H6L5 6"></path></svg>
        </button>
      </div>
      <div class="mask-narration-card">
        <span class="mask-narration-label">演讲旁白</span>
        <span class="mask-narration-text">${spokenText ? escHtml(spokenText) : '在下方演讲稿中点选片段'}</span>
      </div>
      ${visualCard}
      <div class="mask-block-foot">
        <span>${strokeSummary}</span>
      </div>
    `;
    
    item.addEventListener('click', () => {
      selectStep5MaskBox(idx);
    });

    item.querySelector('[data-action="paint"]').addEventListener('click', (e) => {
      e.stopPropagation();
      startMaskPaint(idx);
    });

    item.querySelector('[data-action="erase"]').addEventListener('click', (e) => {
      e.stopPropagation();
      startMaskErase(idx);
    });

    item.querySelector('[data-action="delete"]').addEventListener('click', (e) => {
      e.stopPropagation();
      deleteMaskBox(idx);
    });
    
    container.appendChild(item);
    
    if (isSelected) {
      setTimeout(() => {
        item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }, 50);
    }
  });
}

function renderStep5NarrationPanel() {
  const panel = document.getElementById('step5-narration-panel');
  if (!panel) return;
  const fragments = getNarrationFragments();
  if (!fragments.length) {
    panel.innerHTML = '<div class="step5-narration-empty">当前页暂无演讲旁白。</div>';
    return;
  }
  const selectedByFragment = new Map();
  state.canvasState.boxes.forEach((box, idx) => {
    getSelectedFragmentIds(box).forEach(fragmentId => {
      selectedByFragment.set(fragmentId, idx);
    });
  });
  panel.innerHTML = `
    <div class="step5-narration-title">演讲稿</div>
    <div class="step5-narration-fragments">
      ${fragments.map(fragment => {
        const ownerIdx = selectedByFragment.get(fragment.id);
        const owned = ownerIdx !== undefined;
        const current = owned && ownerIdx === state.canvasState.selectedBoxIndex;
        const color = owned ? getBoxColor(state.canvasState.boxes[ownerIdx], ownerIdx) : '#777777';
        return `
          <button class="step5-narration-fragment${owned ? ' linked' : ''}${current ? ' current' : ''}" type="button" data-fragment-id="${escHtml(fragment.id)}" style="--fragment-color:${color};">
            <span class="step5-narration-fragment-index">${fragment.order}</span>
            ${escHtml(fragment.text)}
          </button>
        `;
      }).join('')}
    </div>
  `;
  panel.querySelectorAll('.step5-narration-fragment').forEach(btn => {
    btn.addEventListener('click', () => toggleNarrationFragmentForSelectedBox(btn.dataset.fragmentId));
  });
}

function toggleNarrationFragmentForSelectedBox(fragmentId) {
  const idx = state.canvasState.selectedBoxIndex;
  const maskBox = state.canvasState.boxes[idx];
  if (!maskBox) {
    showToast('请先在右侧选中一个语块。');
    return;
  }
  const fragments = getNarrationFragments();
  const fragment = fragments.find(item => item.id === fragmentId);
  if (!fragment) return;
  if (!Array.isArray(maskBox.narration_fragments)) {
    maskBox.narration_fragments = [];
  }

  state.canvasState.boxes.forEach((box, boxIdx) => {
    if (boxIdx === idx || !Array.isArray(box.narration_fragments)) return;
    box.narration_fragments = box.narration_fragments.filter(item => item.id !== fragmentId);
    const beatIds = [...new Set(box.narration_fragments.map(item => item.beat_id).filter(Boolean))];
    const groupIds = [...new Set(box.narration_fragments.map(item => item.group_id).filter(Boolean))];
    box.narration_beat_ids = beatIds;
    box.narration_beat_id = beatIds[0] || '';
    box.narration_group_id = groupIds[0] || '';
    box.spoken_text = box.narration_fragments.map(item => item.text).join('');
  });

  const existingIndex = maskBox.narration_fragments.findIndex(item => item.id === fragmentId);
  if (existingIndex >= 0) {
    maskBox.narration_fragments.splice(existingIndex, 1);
  } else {
    maskBox.narration_fragments.push({
      id: fragment.id,
      beat_id: fragment.beat_id,
      group_id: fragment.group_id,
      text: fragment.text
    });
  }
  const beatIds = [...new Set(maskBox.narration_fragments.map(item => item.beat_id).filter(Boolean))];
  const groupIds = [...new Set(maskBox.narration_fragments.map(item => item.group_id).filter(Boolean))];
  maskBox.narration_beat_ids = beatIds;
  maskBox.narration_beat_id = beatIds[0] || '';
  maskBox.narration_group_id = groupIds[0] || '';
  maskBox.spoken_text = maskBox.narration_fragments.map(item => item.text).join('');
  renderStep5BoxesForm();
  renderStep5NarrationPanel();
}

function updateStep5AutoMaskButton() {
  const btn = document.getElementById('step5-btn-automask');
  if (!btn) return;
  btn.disabled = !!state.canvasState.autoMaskLoading || !!state.canvasState.semanticLoading;
  btn.classList.toggle('loading', !!state.canvasState.autoMaskLoading);
  btn.innerHTML = state.canvasState.autoMaskLoading
    ? `<span class="button-spinner"></span><span class="btn-label">AI 框选中...</span>`
    : `<svg class="icon" viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="10" rx="2"></rect><circle cx="12" cy="5" r="2"></circle><path d="M12 7v4M8 16h.01M16 16h.01"></path></svg><span class="btn-label">AI 视觉自动框选</span>`;
}

function updateStep5SemanticButton() {
  const btn = document.getElementById('step5-btn-semantic-blocks');
  if (!btn) return;
  btn.disabled = !!state.canvasState.semanticLoading || !!state.canvasState.autoMaskLoading;
  btn.classList.toggle('loading', !!state.canvasState.semanticLoading);
  btn.innerHTML = state.canvasState.semanticLoading
    ? `<span class="button-spinner"></span><span class="btn-label">AI 分块中...</span>`
    : `<svg class="icon" viewBox="0 0 24 24"><path d="M4 5h16"></path><path d="M4 12h10"></path><path d="M4 19h16"></path><circle cx="18" cy="12" r="2"></circle></svg><span class="btn-label">AI 语义分块</span>`;
}

function selectStep5MaskBox(idx, shouldScroll = true) {
  state.canvasState.selectedBoxIndex = idx;
  redrawCanvas();
  renderStep5NarrationPanel();
  document.querySelectorAll('#step5-boxes-list > div').forEach((el, elIdx) => {
    const isSelected = elIdx === idx;
    el.classList.toggle('highlight-glow', isSelected);
    if (isSelected && shouldScroll) {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  });
}

function updateBrushSize(value, shouldRedraw = true) {
  const size = Math.max(12, Math.min(140, Number(value) || 80));
  state.canvasState.brushSize = size;
  const input = document.getElementById('step5-brush-size');
  const label = document.getElementById('step5-brush-size-value');
  if (input) input.value = String(size);
  if (label) label.innerText = String(size);
  refreshBrushCursor();
  if (shouldRedraw) redrawCanvas();
}

function startMaskPaint(idx) {
  const maskBox = state.canvasState.boxes[idx];
  if (!maskBox) return;
  ensureManualMask(maskBox, idx);
  state.canvasState.paintMode = true;
  state.canvasState.eraserMode = false;
  state.canvasState.paintingBoxIndex = idx;
  state.canvasState.selectedBoxIndex = idx;
  redrawCanvas();
  renderStep5BoxesForm();
  renderStep5NarrationPanel();
  showToast(`已进入第 ${idx + 1} 个语块的涂抹模式，拖动画布即可补正区域。`);
}

function startMaskErase(idx) {
  const maskBox = state.canvasState.boxes[idx];
  if (!maskBox) return;
  ensureManualMask(maskBox, idx);
  state.canvasState.paintMode = true;
  state.canvasState.eraserMode = true;
  state.canvasState.paintingBoxIndex = idx;
  state.canvasState.selectedBoxIndex = idx;
  redrawCanvas();
  renderStep5BoxesForm();
  renderStep5NarrationPanel();
  showToast(`已进入第 ${idx + 1} 个语块的橡皮模式，拖动画布即可擦除涂抹痕迹。`);
}

function createCurrentSlideBlock() {
  const nextIdx = state.canvasState.boxes.length;
  const blockId = `manual_group_${Date.now().toString(36)}_${nextIdx + 1}`;
  const newBox = {
    group_id: blockId,
    role: "content_body",
    text_label: `语块 ${nextIdx + 1}`,
    visual_anchor: "",
    narration_beat_id: "",
    narration_beat_ids: [],
    narration_group_id: "",
    narration_fragments: [],
    spoken_text: "",
    manual_mask: { color: getMaskColor(nextIdx), strokes: [] },
    box: [860, 460, 1060, 620]
  };
  state.canvasState.boxes.push(newBox);
  state.canvasState.selectedBoxIndex = nextIdx;
  state.canvasState.paintMode = false;
  state.canvasState.eraserMode = false;
  state.canvasState.paintingBoxIndex = -1;
  redrawCanvas();
  renderStep5BoxesForm();
  renderStep5NarrationPanel();
  showToast(`已添加第 ${nextIdx + 1} 个语块。请在下方演讲稿点选片段，再用画笔涂抹区域。`);
}

function stopMaskPaint() {
  state.canvasState.paintMode = false;
  state.canvasState.eraserMode = false;
  state.canvasState.paintingBoxIndex = -1;
  state.canvasState.isPainting = false;
  state.canvasState.currentStroke = null;
  hideBrushCursor();
  redrawCanvas();
  renderStep5BoxesForm();
}

function clearAllMaskAnnotations() {
  if (!manifestData?.slides?.length) {
    showToast('当前没有可清除的标注数据。');
    return;
  }
  showCustomConfirm(
    '清除全部标注',
    '将清除所有 Slide 的 AI 框选、语块和手动画笔痕迹。未重新创建语块的页面会按整页展示处理。',
    () => {
      manifestData.slides.forEach(slide => {
        slide.groups = [];
        slide.reveal_boxes = [];
        slide.semantic_blocks = [];
        slide.status = "pending";
      });
      state.canvasState.boxes = [];
      state.canvasState.selectedBoxIndex = -1;
      stopMaskPaint();
      renderStep5Workspace();
      showToast('正在保存清空后的整页展示兜底状态...');
      API.put(`/api/projects/${state.currentProject.id}/steps/5/result`, manifestData)
        .then(() => showToast('已清除所有 Slide 的标注，未重建语块的页面将整页展示。'));
    }
  );
}

function collectManualMaskPoints(manualMask) {
  const points = [];
  const strokes = manualMask?.strokes || [];
  strokes.forEach(stroke => {
    if (isEraseStroke(stroke)) return;
    const radius = Math.max(1, Number(stroke.size || 42) / 2);
    (stroke.points || []).forEach(point => {
      points.push({ x: point.x - radius, y: point.y - radius });
      points.push({ x: point.x + radius, y: point.y + radius });
    });
  });
  return points;
}

function updateMaskBoxFromManualMask(idx) {
  const maskBox = state.canvasState.boxes[idx];
  if (!maskBox) return;
  const manualMask = ensureManualMask(maskBox, idx);
  const points = collectManualMaskPoints(manualMask);
  if (!points.length) return;
  const x1 = Math.max(0, Math.min(...points.map(p => p.x)));
  const y1 = Math.max(0, Math.min(...points.map(p => p.y)));
  const x2 = Math.min(1920, Math.max(...points.map(p => p.x)));
  const y2 = Math.min(1080, Math.max(...points.map(p => p.y)));
  if (x2 - x1 < 4 || y2 - y1 < 4) return;
  maskBox.box = [x1, y1, x2, y2];
  manualMask.bounds = {
    x: Math.round(x1),
    y: Math.round(y1),
    w: Math.round(x2 - x1),
    h: Math.round(y2 - y1)
  };
}

function openNarrationPicker(idx) {
  const maskBox = state.canvasState.boxes[idx];
  const step2Slide = getStep2SlideForManifestSlide();
  const fragments = getNarrationFragments(step2Slide);
  const modal = document.getElementById('modal-narration-picker');
  const list = document.getElementById('narration-picker-list');
  const preview = document.getElementById('narration-picker-preview-img');
  if (!modal || !list || !maskBox) return;

  state.canvasState.narrationPickerBoxIndex = idx;
  state.canvasState.narrationPickerSelection = getSelectedFragmentIds(maskBox);
  if (preview) {
    const slide = getCurrentManifestSlide();
    preview.src = slide ? `/api/projects/${state.currentProject.id}/slides/${slide.slide_id}/image?t=${uuid()}` : '';
  }

  if (!fragments.length) {
    list.innerHTML = '<div class="sketch-dashed mask-empty-state">当前页还没有可绑定的演讲旁白。</div>';
  } else {
    list.innerHTML = fragments.map((fragment) => {
      const isSelected = state.canvasState.narrationPickerSelection.includes(fragment.id);
      return `
        <button class="narration-option${isSelected ? ' selected' : ''}" type="button" data-fragment-id="${escHtml(fragment.id)}" style="--mask-color:${getBoxColor(maskBox, idx)};">
          <span class="narration-option-index">${fragment.order}</span>
          <span class="narration-option-text">${escHtml(fragment.text)}</span>
        </button>
      `;
    }).join('');
    list.querySelectorAll('.narration-option').forEach(option => {
      option.addEventListener('click', () => {
        const fragmentId = option.dataset.fragmentId;
        const selected = state.canvasState.narrationPickerSelection;
        const existingIndex = selected.indexOf(fragmentId);
        if (existingIndex >= 0) {
          selected.splice(existingIndex, 1);
          option.classList.remove('selected');
        } else {
          selected.push(fragmentId);
          option.classList.add('selected');
        }
      });
    });
  }

  modal.style.display = 'flex';
}

function closeNarrationPicker() {
  const modal = document.getElementById('modal-narration-picker');
  if (modal) modal.style.display = 'none';
  state.canvasState.narrationPickerBoxIndex = -1;
  state.canvasState.narrationPickerSelection = [];
}

function confirmNarrationPicker() {
  const boxIdx = state.canvasState.narrationPickerBoxIndex;
  const maskBox = state.canvasState.boxes[boxIdx];
  const step2Slide = getStep2SlideForManifestSlide();
  const fragments = getNarrationFragments(step2Slide);
  const selectedIds = state.canvasState.narrationPickerSelection;
  const selectedFragments = fragments.filter(fragment => selectedIds.includes(fragment.id));
  if (!maskBox || selectedFragments.length === 0) {
    closeNarrationPicker();
    return;
  }
  const beatIds = [...new Set(selectedFragments.map(fragment => fragment.beat_id).filter(Boolean))];
  const groupIds = [...new Set(selectedFragments.map(fragment => fragment.group_id).filter(Boolean))];
  maskBox.narration_beat_ids = beatIds;
  maskBox.narration_beat_id = beatIds[0] || '';
  maskBox.narration_group_id = groupIds[0] || '';
  maskBox.narration_fragments = selectedFragments.map(fragment => ({
    id: fragment.id,
    beat_id: fragment.beat_id,
    group_id: fragment.group_id,
    text: fragment.text
  }));
  maskBox.spoken_text = selectedFragments.map(fragment => fragment.text).join('');
  if (!maskBox.text_label || /^语块\s+\d+$/.test(maskBox.text_label)) {
    maskBox.text_label = maskBox.spoken_text.slice(0, 12) || maskBox.text_label;
  }
  closeNarrationPicker();
  redrawCanvas();
  renderStep5BoxesForm();
  renderStep5NarrationPanel();
  showToast(`第 ${boxIdx + 1} 个语块已绑定 ${selectedFragments.length} 个旁白片段。`);
}

window.deleteMaskBox = function(idx) {
  state.canvasState.boxes.splice(idx, 1);
  state.canvasState.selectedBoxIndex = -1;
  if (state.canvasState.paintingBoxIndex === idx) {
    state.canvasState.paintMode = false;
    state.canvasState.eraserMode = false;
    state.canvasState.paintingBoxIndex = -1;
  } else if (state.canvasState.paintingBoxIndex > idx) {
    state.canvasState.paintingBoxIndex -= 1;
  }
  redrawCanvas();
  renderStep5BoxesForm();
  renderStep5NarrationPanel();
};

window.updateMaskBoxField = function(idx, field, val) {
  if (state.canvasState.boxes[idx]) {
    state.canvasState.boxes[idx][field] = val;
  }
};

// Canvas 的拖拽与大小缩放事件实现
function initCanvasEvents() {
  const canvas = document.getElementById('step5-canvas');
  
  // 移除旧事件（利用 cloneNode）
  const newCanvas = canvas.cloneNode(true);
  canvas.parentNode.replaceChild(newCanvas, canvas);
  
  newCanvas.addEventListener('mousedown', (e) => handleCanvasMouseDown(e, newCanvas));
  newCanvas.addEventListener('mousemove', (e) => handleCanvasMouseMove(e, newCanvas));
  newCanvas.addEventListener('mouseup', handleCanvasMouseUp);
  newCanvas.addEventListener('wheel', (e) => handleMaskCanvasWheel(e, newCanvas), { passive: false });
  newCanvas.addEventListener('mouseleave', (e) => {
    hideBrushCursor();
    handleCanvasMouseUp(e);
  });
  applyMaskCanvasZoom(newCanvas);
}

function getCanvasCoords(e, canvas) {
  const rect = canvas.getBoundingClientRect();
  const x = (e.clientX - rect.left) * (1920 / rect.width);
  const y = (e.clientY - rect.top) * (1080 / rect.height);
  return { x, y };
}

function getBrushCursor() {
  return document.getElementById('step5-brush-cursor');
}

function hideBrushCursor() {
  const cursor = getBrushCursor();
  if (!cursor) return;
  cursor.classList.remove('visible', 'eraser');
  state.canvasState.brushCursorClientX = null;
  state.canvasState.brushCursorClientY = null;
}

function refreshBrushCursor(canvas = document.getElementById('step5-canvas')) {
  const { brushCursorClientX, brushCursorClientY } = state.canvasState;
  if (brushCursorClientX === null || brushCursorClientY === null || !canvas) return;
  positionBrushCursor(canvas, brushCursorClientX, brushCursorClientY);
}

function updateBrushCursor(e, canvas) {
  state.canvasState.brushCursorClientX = e.clientX;
  state.canvasState.brushCursorClientY = e.clientY;
  positionBrushCursor(canvas, e.clientX, e.clientY);
}

function positionBrushCursor(canvas, clientX, clientY) {
  const cursor = getBrushCursor();
  if (!cursor || !canvas) return;
  if (!state.canvasState.paintMode || state.canvasState.paintingBoxIndex < 0) {
    hideBrushCursor();
    return;
  }
  const canvasRect = canvas.getBoundingClientRect();
  if (clientX < canvasRect.left || clientX > canvasRect.right || clientY < canvasRect.top || clientY > canvasRect.bottom) {
    hideBrushCursor();
    return;
  }
  const wrapperRect = cursor.parentElement.getBoundingClientRect();
  const size = Math.max(8, state.canvasState.brushSize * (canvasRect.width / 1920));
  const color = getBoxColor(state.canvasState.boxes[state.canvasState.paintingBoxIndex], state.canvasState.paintingBoxIndex);
  cursor.style.left = `${clientX - wrapperRect.left}px`;
  cursor.style.top = `${clientY - wrapperRect.top}px`;
  cursor.style.setProperty('--cursor-size', `${size}px`);
  cursor.style.setProperty('--cursor-color', color);
  cursor.classList.toggle('eraser', !!state.canvasState.eraserMode);
  cursor.classList.add('visible');
}

function applyMaskCanvasZoom(canvas = document.getElementById('step5-canvas')) {
  const bg = document.getElementById('step5-bg-img');
  if (!canvas || !bg) return;
  const zoom = Math.max(1, Math.min(4, Number(state.canvasState.maskZoom || 1)));
  state.canvasState.maskZoom = zoom;
  const originX = Math.max(0, Math.min(100, Number(state.canvasState.maskZoomOriginX || 50)));
  const originY = Math.max(0, Math.min(100, Number(state.canvasState.maskZoomOriginY || 50)));
  const transform = `scale(${zoom})`;
  const origin = `${originX}% ${originY}%`;
  [bg, canvas].forEach(el => {
    el.style.transform = transform;
    el.style.transformOrigin = origin;
  });
  refreshBrushCursor(canvas);
}

function handleMaskCanvasWheel(e, canvas) {
  if (!e.ctrlKey) return;
  e.preventDefault();
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  state.canvasState.maskZoomOriginX = ((e.clientX - rect.left) / rect.width) * 100;
  state.canvasState.maskZoomOriginY = ((e.clientY - rect.top) / rect.height) * 100;
  const current = Number(state.canvasState.maskZoom || 1);
  const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
  state.canvasState.maskZoom = Math.max(1, Math.min(4, current * factor));
  applyMaskCanvasZoom(canvas);
}

function handleCanvasMouseDown(e, canvas) {
  updateBrushCursor(e, canvas);
  const { x, y } = getCanvasCoords(e, canvas);
  if (state.canvasState.paintMode && state.canvasState.paintingBoxIndex >= 0) {
    const idx = state.canvasState.paintingBoxIndex;
    const maskBox = state.canvasState.boxes[idx];
    if (!maskBox) return;
    const manualMask = ensureManualMask(maskBox, idx);
    const color = getBoxColor(maskBox, idx);
    const stroke = {
      color,
      size: state.canvasState.brushSize,
      mode: state.canvasState.eraserMode ? 'erase' : 'paint',
      eraser: !!state.canvasState.eraserMode,
      points: [{ x: Math.round(x), y: Math.round(y) }]
    };
    manualMask.color = color;
    manualMask.strokes.push(stroke);
    state.canvasState.isPainting = true;
    state.canvasState.currentStroke = stroke;
    state.canvasState.selectedBoxIndex = idx;
    updateMaskBoxFromManualMask(idx);
    redrawCanvas();
    return;
  }

  // 点击空白只取消选择；新建语块使用右侧按钮，区域用画笔涂抹完成。
  state.canvasState.selectedBoxIndex = -1;
  redrawCanvas();
  renderStep5BoxesForm();
  renderStep5NarrationPanel();
}

function handleCanvasMouseMove(e, canvas) {
  updateBrushCursor(e, canvas);
  const { x, y } = getCanvasCoords(e, canvas);

  if (state.canvasState.isPainting && state.canvasState.currentStroke) {
    const stroke = state.canvasState.currentStroke;
    const last = stroke.points[stroke.points.length - 1];
    if (!last || Math.hypot(x - last.x, y - last.y) > 5) {
      stroke.points.push({ x: Math.round(x), y: Math.round(y) });
      updateMaskBoxFromManualMask(state.canvasState.paintingBoxIndex);
      redrawCanvas();
    }
    return;
  }

  return;
}

function handleCanvasMouseUp() {
  if (state.canvasState.isPainting) {
    state.canvasState.isPainting = false;
    state.canvasState.currentStroke = null;
    updateMaskBoxFromManualMask(state.canvasState.paintingBoxIndex);
    redrawCanvas();
    renderStep5BoxesForm();
    renderStep5NarrationPanel();
    return;
  }

  state.canvasState.draggedBoxIndex = -1;
  state.canvasState.draggedHandle = null;
  renderStep5BoxesForm();
}

function drawManualMaskStrokes(ctx, item, idx) {
  const strokes = item.manual_mask?.strokes || [];
  if (!strokes.length) return;
  const isSelected = idx === state.canvasState.selectedBoxIndex;
  const color = getBoxColor(item, idx);
  const maskLayer = document.createElement('canvas');
  maskLayer.width = 1920;
  maskLayer.height = 1080;
  const maskCtx = maskLayer.getContext('2d');
  maskCtx.lineCap = 'round';
  maskCtx.lineJoin = 'round';

  strokes.forEach(stroke => {
    const points = stroke.points || [];
    if (!points.length) return;
    const erase = isEraseStroke(stroke);
    const width = Number(stroke.size || state.canvasState.brushSize);
    const radius = Math.max(1, width / 2);

    maskCtx.save();
    maskCtx.globalCompositeOperation = erase ? 'destination-out' : 'source-over';
    maskCtx.strokeStyle = 'rgba(0,0,0,1)';
    maskCtx.fillStyle = 'rgba(0,0,0,1)';
    maskCtx.lineWidth = width;
    maskCtx.beginPath();
    maskCtx.moveTo(points[0].x, points[0].y);
    points.slice(1).forEach(point => maskCtx.lineTo(point.x, point.y));
    if (points.length === 1) {
      const point = points[0];
      maskCtx.arc(point.x, point.y, radius, 0, Math.PI * 2);
      maskCtx.fill();
      maskCtx.restore();
      return;
    }
    maskCtx.stroke();
    points.forEach(point => {
      maskCtx.beginPath();
      maskCtx.arc(point.x, point.y, radius, 0, Math.PI * 2);
      maskCtx.fill();
    });
    maskCtx.restore();
  });

  const colorLayer = document.createElement('canvas');
  colorLayer.width = 1920;
  colorLayer.height = 1080;
  const colorCtx = colorLayer.getContext('2d');
  colorCtx.fillStyle = hexToRgba(color, isSelected ? 0.24 : 0.18);
  colorCtx.fillRect(0, 0, 1920, 1080);
  colorCtx.globalCompositeOperation = 'destination-in';
  colorCtx.drawImage(maskLayer, 0, 0);
  ctx.drawImage(colorLayer, 0, 0);
}

// 在 Canvas 上绘制手动涂抹的 Mask 图层
function redrawCanvas() {
  const canvas = document.getElementById('step5-canvas');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, 1920, 1080);
  canvas.classList.toggle('painting', state.canvasState.paintMode);
  canvas.classList.toggle('erasing', state.canvasState.paintMode && state.canvasState.eraserMode);

  state.canvasState.boxes.forEach((item, idx) => {
    drawManualMaskStrokes(ctx, item, idx);
  });
  refreshBrushCursor(canvas);
}

function saveStep5CurrentState() {
  const slide = manifestData.slides[state.activeSlideIndex];
  syncMaskBoxesToSlide(slide, state.canvasState.boxes);
}

async function runStep5AutoMask() {
  if (state.canvasState.autoMaskLoading || state.canvasState.semanticLoading) return;
  saveStep5CurrentState();
  state.canvasState.autoMaskLoading = true;
  updateStep5AutoMaskButton();
  renderStep5Workspace();
  showToast('🤖 正在调用 Vision API 进行自动框选与自适应对齐修剪，这可能需要大约 10 秒...');

  try {
    // 将当前的临时 manifest 存盘
    await API.put(`/api/projects/${state.currentProject.id}/steps/5/result`, manifestData);

    // 发起自动标注
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/5/auto-mask`);
    if (res.success) {
      const icon = res.vision_used ? '🔍' : '✏️';
      showToast(`${icon} ${res.message || '智能标注完成！已加载最新的目标包围框。'}`);
      await loadStep5Data();
    }
  } finally {
    state.canvasState.autoMaskLoading = false;
    updateStep5AutoMaskButton();
    renderStep5Workspace();
  }
}

async function runStep5SemanticBlocks() {
  if (state.canvasState.semanticLoading || state.canvasState.autoMaskLoading) return;
  if (!manifestData?.slides?.length) return;
  saveStep5CurrentState();
  state.canvasState.semanticLoading = true;
  updateStep5SemanticButton();
  renderStep5Workspace();
  showToast('🤖 正在让 AI 为所有 Slide 预识别语义块、旁白和画面内容，不会自动绘制 Mask...');

  try {
    await API.put(`/api/projects/${state.currentProject.id}/steps/5/result`, manifestData);
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/5/semantic-blocks`, {});
    if (res.success) {
      const source = res.vision_used ? 'AI 已结合画面完成语义分块' : '已用分镜合约生成语义分块草稿';
      showToast(`✅ ${res.message || source}`);
      await loadStep5Data();
    }
  } finally {
    state.canvasState.semanticLoading = false;
    updateStep5SemanticButton();
    renderStep5Workspace();
  }
}

async function saveStep5Masks() {
  saveStep5CurrentState();
  
  // 标记当前 Slide 状态为已完成
  const currentSlide = manifestData.slides[state.activeSlideIndex];
  if (currentSlide) {
    currentSlide.status = "completed";
  }
  
  showToast('💾 正在保存当前标注坐标并为您自动裁剪图层...');
  const res = await API.put(`/api/projects/${state.currentProject.id}/steps/5/result`, manifestData);
  if (res.success) {
    showToast('🎉 标注图层保存并重建成功！');
    renderStep5Workspace(); // 重新绘制切换栏以更新已标注绿色状态
  }
}

// ==================== 步骤 6: 演讲稿编辑 ====================

let narrationData = null;

async function loadStep6Data() {
  // 获取标注的 manifest 以供左侧 Canvas 框线显示参考
  const manifestRes = await API.get(`/api/projects/${state.currentProject.id}/steps/5/result`);
  if (manifestRes.success) {
    manifestData = manifestRes.manifest;
  }

  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/6/result`);
  if (res.success && res.beats) {
    narrationData = res.beats;
    renderStep6Workspace();
  } else {
    // 首次进入没有演讲稿，提示同步初始化
    initStep6Narration();
  }
}

async function initStep6Narration() {
  showToast('📝 正在根据视觉合约自动初始化演讲稿旁白文本...');
  const res = await API.post(`/api/projects/${state.currentProject.id}/steps/6/init`);
  if (res.success) {
    narrationData = res.beats;
    renderStep6Workspace();
  }
}

function renderStep6Workspace() {
  const thumbsContainer = document.getElementById('step6-thumbs');
  thumbsContainer.innerHTML = '';
  
  narrationData.slides.forEach((slide, idx) => {
    const thumb = document.createElement('div');
    thumb.className = `slide-thumbnail-card ${idx === state.activeSlideIndex ? 'active' : ''}`;
    const url = `/api/projects/${state.currentProject.id}/slides/${slide.slide_id}/image?t=${uuid()}`;
    thumb.innerHTML = `
      <div class="img-preview"><img src="${url}"></div>
      <div class="slide-num">${slide.slide_id}</div>
    `;
    thumb.addEventListener('click', () => {
      saveStep6CurrentState();
      state.activeSlideIndex = idx;
      renderStep6Workspace();
    });
    thumbsContainer.appendChild(thumb);
  });
  
  const slide = narrationData.slides[state.activeSlideIndex];
  if (slide) {
    const imgUrl = `/api/projects/${state.currentProject.id}/slides/${slide.slide_id}/image?t=${uuid()}`;
    document.getElementById('step6-bg-img').src = imgUrl;
    
    // 初始化只读 Canvas 用来在鼠标划过右侧旁白段落时高亮显示对应的 Mask 区域
    drawStep6StaticCanvas(-1);
    
    // 渲染右侧的段落列表
    const container = document.getElementById('step6-beats-list');
    container.innerHTML = '';
    
    slide.beats.forEach((beat, idx) => {
      const row = document.createElement('div');
      row.className = 'sketch-dashed';
      row.id = `step6-beat-card-${idx}`;
      row.style.padding = '0.5rem';
      row.style.backgroundColor = '#fff';
      row.innerHTML = `
        <div style="display:flex; justify-content:space-between; margin-bottom:0.2rem; font-size:0.85rem; font-weight:bold;">
          <span>句段 ${idx + 1} (${beat.group_id} - ${beat.visible_anchor})</span>
          <span style="color:#888;">意图: ${beat.spoken_intent}</span>
        </div>
        <textarea rows="2" style="font-size:0.95rem; width:100%;" onchange="updateNarrationBeatText(${idx}, this.value)">${beat.spoken_text}</textarea>
      `;
      
      // 鼠标划入该旁白，高亮左图对应的 Mask
      row.addEventListener('mouseenter', () => {
        row.classList.add('highlight-glow');
        row.style.backgroundColor = '#fffde0';
        // 查找对应 group_id 的坐标索引
        const mSlide = manifestData.slides.find(s => s.slide_id === slide.slide_id);
        if (mSlide) {
          const maskBoxes = getSlideMaskBoxes(mSlide);
          const boxIdx = maskBoxes.findIndex(b => isBeatLinkedToMaskBox(beat, b));
          drawStep6StaticCanvas(boxIdx);
        }
      });
      
      row.addEventListener('mouseleave', () => {
        row.classList.remove('highlight-glow');
        row.style.backgroundColor = '#fff';
        drawStep6StaticCanvas(-1);
      });
      
      container.appendChild(row);
    });
    
    // 给步骤 6 的 canvas 绑定鼠标移动事件，实现反向高亮与平滑滚动
    const canvas = document.getElementById('step6-canvas');
    const newCanvas = canvas.cloneNode(true);
    canvas.parentNode.replaceChild(newCanvas, canvas);
    
    newCanvas.addEventListener('mousemove', (e) => {
      const { x, y } = getCanvasCoords(e, newCanvas);
      const currentSlideId = narrationData.slides[state.activeSlideIndex].slide_id;
      const mSlide = manifestData.slides.find(s => s.slide_id === currentSlideId);
      if (!mSlide) return;
      const maskBoxes = getSlideMaskBoxes(mSlide);
      
      let foundBoxIdx = -1;
      // 倒序检查碰撞
      for (let i = maskBoxes.length - 1; i >= 0; i--) {
        const box = maskBoxes[i].box;
        if (x >= box[0] && x <= box[2] && y >= box[1] && y <= box[3]) {
          foundBoxIdx = i;
          break;
        }
      }
      
      // 高亮 Canvas
      drawStep6StaticCanvas(foundBoxIdx);
      
      // 反向高亮右侧列表卡片并滚动到可视区域
      slide.beats.forEach((beat, bIdx) => {
        const el = document.getElementById(`step6-beat-card-${bIdx}`);
        if (!el) return;
        
        if (foundBoxIdx !== -1 && isBeatLinkedToMaskBox(beat, maskBoxes[foundBoxIdx])) {
          el.classList.add('highlight-glow');
          el.style.backgroundColor = '#fffde0';
          el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } else {
          el.classList.remove('highlight-glow');
          el.style.backgroundColor = '#fff';
        }
      });
    });
    
    newCanvas.addEventListener('mouseleave', () => {
      drawStep6StaticCanvas(-1);
      slide.beats.forEach((beat, bIdx) => {
        const el = document.getElementById(`step6-beat-card-${bIdx}`);
        if (el) {
          el.classList.remove('highlight-glow');
          el.style.backgroundColor = '#fff';
        }
      });
    });
  }
}

function updateNarrationBeatText(idx, val) {
  const slide = narrationData.slides[state.activeSlideIndex];
  if (slide && slide.beats[idx]) {
    slide.beats[idx].spoken_text = val;
  }
}

function drawStep6StaticCanvas(highlightIdx) {
  const canvas = document.getElementById('step6-canvas');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, 1920, 1080);
  
  const currentSlideId = narrationData.slides[state.activeSlideIndex].slide_id;
  const mSlide = manifestData.slides.find(s => s.slide_id === currentSlideId);
  if (!mSlide) return;
  
  getSlideMaskBoxes(mSlide).forEach((item, idx) => {
    const [x1, y1, x2, y2] = item.box;
    const isHighlighted = idx === highlightIdx;
    
    ctx.lineWidth = isHighlighted ? 3 : 2;
    ctx.strokeStyle = isHighlighted ? '#e5b922' : '#777777';
    ctx.lineJoin = 'miter';
    
    // 绘制工整圆角框
    ctx.beginPath();
    ctx.roundRect(x1, y1, x2 - x1, y2 - y1, 8);
    ctx.stroke();
    
    if (isHighlighted) {
      // 绘制雅致浅黄色半透明高亮遮罩
      ctx.fillStyle = 'rgba(249, 214, 92, 0.08)';
      ctx.fill();
    } else {
      ctx.fillStyle = 'rgba(17, 17, 17, 0.01)';
      ctx.fill();
    }
    
    // 气泡：正圆
    ctx.beginPath();
    ctx.arc(x1, y1, 14, 0, Math.PI * 2);
    ctx.fillStyle = isHighlighted ? '#FFF9DB' : '#f3f4f6';
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = '#111111';
    ctx.stroke();
    
    ctx.fillStyle = '#111111';
    ctx.font = '500 15px Inter, Noto Sans SC';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(idx + 1, x1, y1);
  });
}

function saveStep6CurrentState() {
  // 辅助防错
  const slide = narrationData.slides[state.activeSlideIndex];
  if (slide) {
    const list = document.getElementById('step6-beats-list');
    if (list) {
      const textareas = list.querySelectorAll('textarea');
      textareas.forEach((ta, idx) => {
        if (slide.beats[idx]) {
          slide.beats[idx].spoken_text = ta.value;
        }
      });
    }
  }
}

async function saveStep6Narration() {
  saveStep6CurrentState();
  showToast('💾 正在保存并校验旁白信息...');
  const res = await API.put(`/api/projects/${state.currentProject.id}/steps/6/result`, narrationData);
  if (res.success) {
    showToast('🎉 演讲旁白修改保存成功！');
  }
}

// ==================== 步骤 7: 语音合成 ====================

async function loadStep7Data() {
  // 检查是否已经合成过音频
  const [res, narrationRes] = await Promise.all([
    API.get(`/api/projects/${state.currentProject.id}/steps/3/images`),
    API.get(`/api/projects/${state.currentProject.id}/steps/6/result`).catch(() => ({ success: false }))
  ]);
  const narrationSlides = narrationRes.success ? (narrationRes.beats?.slides || []) : [];
  if (res.success) {
    const container = document.getElementById('step7-audio-list');
    container.innerHTML = '';
    
    res.images.forEach(img => {
      const row = document.createElement('div');
      row.className = 'sketch-dashed step7-audio-card';
      
      const audioUrl = `/api/projects/${state.currentProject.id}/slides/${img.slide_id}/audio`;
      const script = getStep7NarrationText(img.slide_id, narrationSlides);
      
      row.innerHTML = `
        <div class="step7-audio-main">
          <div class="step7-audio-title">${escHtml(img.slide_id)}</div>
          <div class="step7-audio-script">${script ? escHtml(script) : '暂无演讲稿，请先在上一步保存演讲稿。'}</div>
        </div>
        <audio controls src="${audioUrl}" class="step7-audio-player"></audio>
      `;
      container.appendChild(row);
    });
    
    // 如果有图片状态，展示列表，默认隐藏 loading 状态
    document.getElementById('step7-result-box').style.display = 'block';
  }
}

function getStep7NarrationText(slideId, narrationSlides) {
  const slide = narrationSlides.find(item => item.slide_id === slideId);
  if (!slide || !Array.isArray(slide.beats)) return '';
  return slide.beats
    .map(beat => String(beat?.spoken_text || '').trim())
    .filter(Boolean)
    .join('\n');
}

async function runStep7TTS() {
  document.getElementById('step7-loading').style.display = 'block';
  document.getElementById('step7-btn-synthesize').disabled = true;
  showToast('🔊 正在调用 MiniMax TTS 服务并绑定 Reveal 关键帧时间轴...');
  
  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/7/synthesize`);
    if (res.success) {
      showToast('🎉 合成并绑定时间轴完成！');
      loadStep7Data();
    }
  } catch(e) {
  } finally {
    document.getElementById('step7-loading').style.display = 'none';
    document.getElementById('step7-btn-synthesize').disabled = false;
  }
}

// ==================== 步骤 8: 视频合成与渲染 ====================

async function loadStep8Data() {
  // 检查是否有渲染出的 MP4
  const videoUrl = `/api/projects/${state.currentProject.id}/video`;
  try {
    const response = await fetch(videoUrl, { method: 'HEAD' });
    if (response.ok) {
      showStep8VideoResult(videoUrl);
    } else {
      document.getElementById('step8-result-box').style.display = 'none';
      document.getElementById('step8-btn-render').style.display = 'inline-flex';
    }
  } catch (e) {
    document.getElementById('step8-result-box').style.display = 'none';
  }
}

async function runStep8Render() {
  document.getElementById('step8-loading').style.display = 'block';
  document.getElementById('step8-btn-render').disabled = true;
  showToast('🎬 Remotion 渲染进程已启动，请稍候片刻...');
  
  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/8/render`);
    if (res.success) {
      showToast('🎉 视频渲染成功！');
      const videoUrl = `/api/projects/${state.currentProject.id}/video`;
      showStep8VideoResult(videoUrl);
    }
  } catch(e) {
  } finally {
    document.getElementById('step8-loading').style.display = 'none';
    document.getElementById('step8-btn-render').disabled = false;
  }
}

function showStep8VideoResult(videoUrl) {
  document.getElementById('step8-btn-render').style.display = 'none';
  const player = document.getElementById('step8-video-player');
  player.src = videoUrl + `?t=${Date.now()}`;
  
  const dlBtn = document.getElementById('step8-btn-download');
  dlBtn.href = videoUrl;
  
  document.getElementById('step8-result-box').style.display = 'block';
}
