// IP Character Manager - Step 3 IP 形象管理前端逻辑
// 依赖全局 API / state / showToast / escHtml

(function () {
  "use strict";

  const MAX_CHARACTERS = 2;
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
    modal.style.display = "block";
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
      '<label class="storyboard-config-field">' +
      "<span>外观描述（服饰 / 配色 / 表情 / 风格）</span>" +
      '<textarea class="ip-character-input ip-char-desc" rows="3" placeholder="例如：穿着蓝色校服的卡通女孩，大眼睛，微笑，扁平化插画风格...">' + escHtml(char.description || "") + "</textarea>" +
      "</label>" +
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
    const description = (card.querySelector(".ip-char-desc") || {}).value;
    const positionSelect = card.querySelector(".ip-char-position");
    const position = positionSelect ? positionSelect.value || null : null;
    const fileInput = card.querySelector(".ip-char-file");
    const file = fileInput && fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;

    if (!name || !name.trim()) {
      showToast("请填写角色名称");
      return;
    }

    const payload = { name: name.trim(), description: (description || "").trim(), position: position };
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

    try {
      const res = await API.put("/api/projects/" + projectId + "/ip-characters/config", {
        enabled: enabled,
        page_scope: page_scope,
        selected_slide_ids: selected_slide_ids,
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

  function init() {
    const btnOpen = document.getElementById("step3-btn-ip-character");
    const btnCancel = document.getElementById("btn-ip-character-cancel");
    const btnSaveConfig = document.getElementById("btn-ip-character-save-config");
    const btnAdd = document.getElementById("ip-character-btn-add");

    if (btnOpen) btnOpen.addEventListener("click", openModal);
    if (btnCancel) btnCancel.addEventListener("click", closeModal);
    if (btnSaveConfig) btnSaveConfig.addEventListener("click", saveConfig);
    if (btnAdd) btnAdd.addEventListener("click", addNewCharacter);

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
