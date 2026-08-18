// IP Character Manager - Step 3 IP 形象管理前端逻辑
// 依赖全局 API / state / showToast / escHtml

(function () {
  "use strict";

  const MAX_CHARACTERS = 2;
  const DEFAULT_PROMPT_TEMPLATE =
    "<IPCharacterRequirements>\n" +
    "【IP 形象融入要求】\n" +
    "请把以下 IP 形象角色自然融入本页画面，保持每个角色的外观、配色与风格高度一致：\n" +
    "{characters}\n" +
    "约束（与生图固定规则同等重要，不得违反）：\n" +
    "1. 每个已列出的角色都必须出现在画面中，不得省略或替换。\n" +
    "2. 多个角色互不重叠，也不得遮挡标题、正文文字、图表或关键标签；角色与其它视觉元素之间保留清晰间隙。\n" +
    "3. 角色必须位于画面内容区（y<930），不得进入底部字幕安全区，不得覆盖页面上方主标题区。\n" +
    "4. 若某个角色标注了放置位置，请尽量放在该位置；仅当该位置会遮挡关键文字或与其它元素冲突时才可调整。\n" +
    "5. 请确保 IP 形象与页面其它视觉元素和谐共存，整体保持专业、美观的排版。\n" +
    "</IPCharacterRequirements>";
  const FALLBACK_POSITIONS = [
    { value: "", label: "不限制" },
    { value: "left_top", label: "左上角" },
    { value: "left_bottom", label: "左下角" },
    { value: "right_top", label: "右上角" },
    { value: "right_bottom", label: "右下角" },
    { value: "center", label: "居中" },
  ];

  let ipManifest = null;

  function getProjectId() {
    return (window.state && window.state.currentProject && window.state.currentProject.id) || null;
  }

  function getPositions() {
    return (ipManifest && ipManifest.positions) || FALLBACK_POSITIONS;
  }

  function openModal() {
    const modal = document.getElementById("modal-ip-character");
    if (!modal) return;
    // 必须用 flex，与 .modal-overlay 的 display:flex 保持一致，
    // 否则 align-items/justify-content 居中会失效。
    modal.style.display = "flex";
    loadConfig();
  }

  function closeModal() {
    const modal = document.getElementById("modal-ip-character");
    if (modal) modal.style.display = "none";
  }

  async function loadConfig() {
    const projectId = getProjectId();
    if (!projectId) {
      showToast("请先选择一个项目");
      return;
    }
    try {
      const res = await API.get("/api/projects/" + projectId + "/ip-characters");
      ipManifest = res.data || {};
      renderConfig();
    } catch (e) {
      console.error("[IPCharacter] load failed:", e);
      ipManifest = { enabled: false, page_scope: "all", selected_slide_ids: [], characters: [], positions: FALLBACK_POSITIONS };
      renderConfig();
    }
  }

  function renderConfig() {
    if (!ipManifest) return;
    const enabledCheckbox = document.getElementById("ip-character-enabled");
    const scopeSelect = document.getElementById("ip-character-page-scope");
    const selectedRow = document.getElementById("ip-character-selected-row");
    const selectedInput = document.getElementById("ip-character-selected-ids");

    if (enabledCheckbox) enabledCheckbox.checked = !!ipManifest.enabled;
    if (scopeSelect) scopeSelect.value = ipManifest.page_scope || "all";
    if (selectedRow) selectedRow.style.display = ipManifest.page_scope === "selected" ? "" : "none";
    if (selectedInput) selectedInput.value = (ipManifest.selected_slide_ids || []).join(",");
    const templateInput = document.getElementById("ip-character-prompt-template");
    if (templateInput) templateInput.value = ipManifest.prompt_template || "";

    renderCharacterList();
    updateAddButtonState();
  }

  function updateAddButtonState() {
    const addBtn = document.getElementById("ip-character-btn-add");
    if (!addBtn) return;
    const count = (ipManifest && ipManifest.characters ? ipManifest.characters.length : 0);
    addBtn.disabled = count >= MAX_CHARACTERS;
    addBtn.style.opacity = count >= MAX_CHARACTERS ? "0.5" : "1";
  }

  function renderCharacterList() {
    const container = document.getElementById("ip-character-list");
    if (!container) return;
    const characters = (ipManifest && ipManifest.characters) || [];
    if (characters.length === 0) {
      container.innerHTML = '<div class="ip-character-empty">暂无 IP 形象角色，点击下方"+ 添加角色"按钮创建。</div>';
      return;
    }
    container.innerHTML = characters.map(renderCharacterCard).join("");
    bindCardEvents();
  }

  function renderCharacterCard(char) {
    const positions = getPositions();
    const options = positions
      .map(function (p) {
        const val = p.value === null || p.value === undefined ? "" : p.value;
        const sel = (char.position || "") === val ? " selected" : "";
        return '<option value="' + escHtml(val) + '"' + sel + ">" + escHtml(p.label) + "</option>";
      })
      .join("");

    const imgPreview = char.image_url
      ? '<img src="' + char.image_url + "?t=" + Date.now() + '" alt="' + escHtml(char.name || "") + '" class="ip-character-img">'
      : '<span class="ip-character-no-image">未上传参考图</span>';

    return (
      '<div class="ip-character-card" data-id="' + escHtml(char.id || "") + '">' +
      '<div class="ip-character-card-header">' +
      "<strong>" + escHtml(char.name || "未命名角色") + "</strong>" +
      '<button class="danger ip-character-btn-delete" type="button" data-id="' + escHtml(char.id || "") + '">删除</button>' +
      "</div>" +
      '<div class="ip-character-fields">' +
      '<label class="storyboard-config-field">' +
      "<span>名称</span>" +
      '<input type="text" class="ip-character-input ip-char-name" value="' + escHtml(char.name || "") + '" placeholder="角色名称">' +
      "</label>" +
      '<label class="storyboard-config-field">' +
      "<span>位置预设</span>" +
      '<select class="ip-character-input ip-char-position">' + options + "</select>" +
      "</label>" +
      "</div>" +
      '<p class="ip-character-reference-hint">该角色的外观、配色、风格将通过下方参考图传给图像模型。</p>' +
      '<div class="ip-character-upload-row">' +
      '<div class="ip-character-preview">' + imgPreview + "</div>" +
      '<label class="btn secondary ip-character-upload-label">' +
      "上传/更换参考图" +
      '<input type="file" accept="image/*" class="ip-char-file" style="display:none;">' +
      "</label>" +
      "</div>" +
      '<button class="success ip-character-btn-save" type="button" data-id="' + escHtml(char.id || "") + '" style="margin-top:0.6rem;width:100%;">保存该角色</button>' +
      "</div>"
    );
  }

  function bindCardEvents() {
    document.querySelectorAll(".ip-character-btn-delete").forEach(function (btn) {
      btn.onclick = async function () {
        const id = btn.getAttribute("data-id");
        if (!confirm("确定删除该 IP 形象角色？关联的参考图也会一并移除。")) return;
        await deleteCharacter(id);
      };
    });

    document.querySelectorAll(".ip-character-btn-save").forEach(function (btn) {
      btn.onclick = async function () {
        const card = btn.closest(".ip-character-card");
        if (card) await saveCharacter(card);
      };
    });

    document.querySelectorAll(".ip-char-file").forEach(function (input) {
      input.onchange = function () {
        const card = input.closest(".ip-character-card");
        if (!card || !input.files[0]) return;
        const preview = card.querySelector(".ip-character-preview");
        const reader = new FileReader();
        reader.onload = function (e) {
          preview.innerHTML = '<img src="' + e.target.result + '" class="ip-character-img">';
        };
        reader.readAsDataURL(input.files[0]);
      };
    });

    const scopeSelect = document.getElementById("ip-character-page-scope");
    if (scopeSelect) {
      scopeSelect.onchange = function () {
        const selectedRow = document.getElementById("ip-character-selected-row");
        if (selectedRow) selectedRow.style.display = scopeSelect.value === "selected" ? "" : "none";
      };
    }
  }

  async function saveCharacter(card) {
    const projectId = getProjectId();
    if (!projectId) {
      showToast("请先选择一个项目");
      return;
    }
    const id = card.getAttribute("data-id") || "";
    const name = (card.querySelector(".ip-char-name") || {}).value;
    const positionSelect = card.querySelector(".ip-char-position");
    const position = positionSelect ? positionSelect.value || null : null;
    const fileInput = card.querySelector(".ip-char-file");
    const file = fileInput && fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;

    if (!name || !name.trim()) {
      showToast("请填写角色名称");
      return;
    }

    const payload = { name: name.trim(), position: position };
    if (id && !id.startsWith("new_")) payload.id = id;

    const formData = new FormData();
    formData.append("data", JSON.stringify(payload));
    if (file) formData.append("file", file);

    try {
      const res = await API.post("/api/projects/" + projectId + "/ip-characters", formData);
      ipManifest = res.data || ipManifest;
      renderConfig();
      showToast("IP 形象角色已保存");
    } catch (e) {
      console.error("[IPCharacter] save failed:", e);
    }
  }

  async function deleteCharacter(id) {
    if (!id || id.startsWith("new_")) {
      // Local-only card: just remove from DOM
      const card = document.querySelector('.ip-character-card[data-id="' + id + '"]');
      if (card) card.remove();
      if (document.querySelectorAll(".ip-character-card").length === 0) {
        document.getElementById("ip-character-list").innerHTML =
          '<div class="ip-character-empty">暂无 IP 形象角色，点击下方"+ 添加角色"按钮创建。</div>';
      }
      updateAddButtonState();
      return;
    }
    const projectId = getProjectId();
    if (!projectId) return;
    try {
      const res = await API.delete("/api/projects/" + projectId + "/ip-characters/" + id);
      ipManifest = res.data || ipManifest;
      renderConfig();
      showToast("IP 形象角色已删除");
    } catch (e) {
      console.error("[IPCharacter] delete failed:", e);
    }
  }

  async function saveConfig() {
    const projectId = getProjectId();
    if (!projectId) {
      showToast("请先选择一个项目");
      return;
    }
    const enabledCheckbox = document.getElementById("ip-character-enabled");
    const scopeSelect = document.getElementById("ip-character-page-scope");
    const selectedInput = document.getElementById("ip-character-selected-ids");

    const enabled = enabledCheckbox ? enabledCheckbox.checked : false;
    const page_scope = scopeSelect ? scopeSelect.value : "all";
    const selectedRaw = selectedInput ? (selectedInput.value || "").trim() : "";
    const selected_slide_ids = selectedRaw
      ? selectedRaw.split(",").map(function (s) { return s.trim(); }).filter(Boolean)
      : [];
    const templateInput = document.getElementById("ip-character-prompt-template");
    const prompt_template = templateInput ? templateInput.value.trim() : "";

    try {
      const res = await API.put("/api/projects/" + projectId + "/ip-characters/config", {
        enabled: enabled,
        page_scope: page_scope,
        selected_slide_ids: selected_slide_ids,
        prompt_template: prompt_template,
      });
      ipManifest = res.data || ipManifest;
      renderConfig();
      showToast("IP 形象全局设置已保存");
    } catch (e) {
      console.error("[IPCharacter] saveConfig failed:", e);
    }
  }

  function addNewCharacter() {
    const container = document.getElementById("ip-character-list");
    if (!container) return;
    const characters = (ipManifest && ipManifest.characters) || [];
    if (characters.length >= MAX_CHARACTERS) {
      showToast("最多支持 " + MAX_CHARACTERS + " 个 IP 形象角色");
      return;
    }
    const empty = container.querySelector(".ip-character-empty");
    if (empty) empty.remove();

    const tempId = "new_" + Date.now();
    const blankChar = { id: tempId, name: "", description: "", position: null, image_url: null };
    container.insertAdjacentHTML("beforeend", renderCharacterCard(blankChar));
    bindCardEvents();
    updateAddButtonState();
  }

  function resetPromptTemplate() {
    const templateInput = document.getElementById("ip-character-prompt-template");
    if (!templateInput) return;
    templateInput.value = DEFAULT_PROMPT_TEMPLATE;
    showToast("已恢复默认 IP 融入提示词模板，点击「保存设置」生效");
  }

  function init() {
    const btnOpen = document.getElementById("step3-btn-ip-character");
    const btnCancel = document.getElementById("btn-ip-character-cancel");
    const btnSaveConfig = document.getElementById("btn-ip-character-save-config");
    const btnAdd = document.getElementById("ip-character-btn-add");
    const btnResetTemplate = document.getElementById("btn-ip-character-reset-template");

    if (btnOpen) btnOpen.addEventListener("click", openModal);
    if (btnCancel) btnCancel.addEventListener("click", closeModal);
    if (btnSaveConfig) btnSaveConfig.addEventListener("click", saveConfig);
    if (btnAdd) btnAdd.addEventListener("click", addNewCharacter);
    if (btnResetTemplate) btnResetTemplate.addEventListener("click", resetPromptTemplate);

    const modal = document.getElementById("modal-ip-character");
    if (modal) {
      modal.addEventListener("click", function (e) {
        if (e.target === modal) closeModal();
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
