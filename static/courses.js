/**
 * 课程项目管理：树形视图（课程 → 章节 → 视频）
 *
 * 功能：
 * - 递归渲染三级树结构（课程卡片 / 章节行 / 视频行）
 * - 折叠/展开（记忆到 localStorage）
 * - 快速新建（自动聚焦重命名，Enter确认/Esc默认名）
 * - 双击节点重命名
 * - 拖拽排序 + 跨层级移动
 * - 兼容旧项目（独立项目也用卡片样式，通过图标区分）
 *
 * 注意：顶部标题和按钮由 index.html 提供，本组件只负责 #project-list 内的树主体。
 */

const CourseTree = (() => {
  const STORAGE_KEY = 'courseTree.expanded';
  let treeData = null;
  let expandedNodes = new Set();
  // 记录"新建视频"的目标父级（由课程/章节的 +视频 按钮设置，
  // createProject() 在确认创建后会读取并移动项目）
  let pendingProjectParent = null;

  // ===== 图标（Feather 风格 SVG，与项目整体一致）=====
  const ICON = {
    chevronDown: '<svg class="icon" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"></polyline></svg>',
    chevronRight: '<svg class="icon" viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"></polyline></svg>',
    layers: '<svg class="icon" viewBox="0 0 24 24"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>',
    list: '<svg class="icon" viewBox="0 0 24 24"><line x1="8" y1="6" x2="21" y2="6"></line><line x1="8" y1="12" x2="21" y2="12"></line><line x1="8" y1="18" x2="21" y2="18"></line><line x1="3" y1="6" x2="3.01" y2="6"></line><line x1="3" y1="12" x2="3.01" y2="12"></line><line x1="3" y1="18" x2="3.01" y2="18"></line></svg>',
    film: '<svg class="icon" viewBox="0 0 24 24"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect><line x1="7" y1="2" x2="7" y2="22"></line><line x1="17" y1="2" x2="17" y2="22"></line><line x1="2" y1="12" x2="22" y2="12"></line><line x1="2" y1="7" x2="7" y2="7"></line><line x1="2" y1="17" x2="7" y2="17"></line><line x1="17" y1="17" x2="22" y2="17"></line><line x1="17" y1="7" x2="22" y2="7"></line></svg>',
    edit: '<svg class="icon" viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>',
    trash: '<svg class="icon" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>',
    plus: '<svg class="icon" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>',
    play: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><polygon points="10 8 16 12 10 16 10 8" fill="currentColor" stroke="none"></polygon></svg>',
  };

  // ===== 初始化 =====

  function init() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) expandedNodes = new Set(JSON.parse(saved));
    } catch (e) {
      // ignore
    }
    // 绑定首页"新建课程"按钮（防止重复绑定）
    const btnCreateCourse = document.getElementById('btn-create-course');
    if (btnCreateCourse && !btnCreateCourse.__courseBound) {
      btnCreateCourse.__courseBound = true;
      btnCreateCourse.addEventListener('click', () => createCourseQuick());
    }

    // 绑定空白区拖拽（把视频拖出变独立项目）
    const pageHome = document.getElementById('page-home');
    if (pageHome && !pageHome.__dragoutBound) {
      pageHome.__dragoutBound = true;
      pageHome.addEventListener('dragover', handleBlankDragOver);
      pageHome.addEventListener('drop', handleBlankDrop);
    }
  }

  function saveExpanded() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...expandedNodes]));
    } catch (e) {
      // ignore
    }
  }

  function isExpanded(id) {
    return expandedNodes.has(id);
  }

  function toggleExpanded(id) {
    if (expandedNodes.has(id)) {
      expandedNodes.delete(id);
    } else {
      expandedNodes.add(id);
    }
    saveExpanded();
  }

  // ===== 数据加载 =====

  async function load() {
    try {
      treeData = await API.get('/api/courses/tree');
      render();
    } catch (e) {
      console.error('CourseTree load error:', e);
      const container = document.getElementById('project-list');
      if (container) {
        container.innerHTML = '<div style="padding:2rem;color:#A63D3D;">课程树加载失败，请刷新重试。</div>';
      }
    }
  }

  // ===== 渲染 =====

  function render() {
    const container = document.getElementById('project-list');
    if (!container || !treeData) return;

    container.className = 'course-tree-container';
    container.innerHTML = '';

    const treeEl = document.createElement('div');
    treeEl.className = 'course-tree-body';

    const courseList = treeData.courses || [];
    const standaloneList = treeData.standalone_projects || [];

    // 课程卡片
    courseList.forEach(course => {
      treeEl.appendChild(renderCourseNode(course));
    });

    // 独立项目：每个都用和课程一样的卡片样式
    standaloneList.forEach(project => {
      treeEl.appendChild(renderStandaloneProjectCard(project));
    });

    // 空状态
    if (courseList.length === 0 && standaloneList.length === 0) {
      treeEl.innerHTML = `
        <div class="course-tree-empty">
          <p style="font-size:1.2rem;margin-bottom:1rem;color:#6E737C;">还没有任何课程或项目，快去新建一个吧！</p>
          <button type="button" class="success" onclick="document.getElementById('btn-create-course').click()">立即新建</button>
        </div>
      `;
    }

    container.appendChild(treeEl);
  }

  // 课程卡片
  function renderCourseNode(course) {
    const nodeId = `course-${course.id}`;
    const expanded = isExpanded(nodeId);

    const node = document.createElement('div');
    node.className = 'course-card-item';
    node.dataset.courseId = course.id;
    node.draggable = true;

    const chapterCount = course.chapters ? course.chapters.length : 0;
    const projectCount = course.project_count || 0;
    const unchapteredCount = (course.unchaptered_projects || []).length;

    node.innerHTML = `
      <div class="course-card-header">
        <span class="tree-toggle" data-toggle="${nodeId}">${expanded ? ICON.chevronDown : ICON.chevronRight}</span>
        ${ICON.layers}
        <span class="course-name" data-course-name="${course.id}">${escHtml(course.name)}</span>
        <span class="course-meta">${chapterCount} 章 · ${projectCount} 视频</span>
        <div class="course-actions">
          <button class="icon-action-btn" data-action="add-chapter" data-course-id="${course.id}" title="新建章节">${ICON.plus}<span class="action-label">章节</span></button>
          <button class="icon-action-btn" data-action="add-project" data-course-id="${course.id}" title="新建视频">${ICON.plus}<span class="action-label">视频</span></button>
          <button class="icon-action-btn" data-action="edit-course" data-course-id="${course.id}" title="重命名">${ICON.edit}<span class="action-label">修改</span></button>
          <button class="icon-action-btn danger" data-action="delete-course" data-course-id="${course.id}" title="删除课程">${ICON.trash}<span class="action-label">删除</span></button>
        </div>
      </div>
    `;

    // 事件绑定
    node.querySelector('[data-toggle]').addEventListener('click', (e) => {
      e.stopPropagation();
      toggleExpanded(nodeId);
      render();
    });
    node.querySelector('.course-name').addEventListener('dblclick', () => startRenameCourse(course.id));
    node.querySelector('[data-action="add-chapter"]').addEventListener('click', () => createChapterQuick(course.id));
    node.querySelector('[data-action="add-project"]').addEventListener('click', () => createProjectInCourse(course.id));
    node.querySelector('[data-action="edit-course"]').addEventListener('click', () => startRenameCourse(course.id));
    node.querySelector('[data-action="delete-course"]').addEventListener('click', () => deleteCourseConfirm(course));

    // 拖拽
    node.addEventListener('dragstart', (e) => handleDragStart(e, 'course'));
    node.addEventListener('dragend', handleDragEnd);
    node.addEventListener('dragover', (e) => handleNodeDragOver(e, 'course', true));
    node.addEventListener('drop', (e) => handleNodeDrop(e, 'course', true));

    // 子节点容器（章节 + 未归类视频，扁平展示）
    if (expanded) {
      const childrenEl = document.createElement('div');
      childrenEl.className = 'course-card-children';

      (course.chapters || []).forEach(chapter => {
        childrenEl.appendChild(renderChapterNode(chapter));
      });

      // 课程下未归类视频（直接跟在章节后面，无额外分组标签）
      (course.unchaptered_projects || []).forEach(p => {
        childrenEl.appendChild(renderProjectLeaf(p));
      });

      if (chapterCount === 0 && unchapteredCount === 0) {
        childrenEl.innerHTML = '<div class="empty-hint">暂无章节或视频，点上方 + 添加</div>';
      }

      node.appendChild(childrenEl);
    }

    return node;
  }

  // 章节行
  function renderChapterNode(chapter) {
    const nodeId = `chapter-${chapter.id}`;
    const expanded = isExpanded(nodeId);

    const node = document.createElement('div');
    node.className = 'chapter-node';
    node.dataset.chapterId = chapter.id;
    node.draggable = true;

    const projectCount = chapter.projects ? chapter.projects.length : 0;

    node.innerHTML = `
      <div class="chapter-node-header">
        <span class="tree-toggle" data-toggle="${nodeId}">${expanded ? ICON.chevronDown : ICON.chevronRight}</span>
        ${ICON.list}
        <span class="chapter-name" data-chapter-name="${chapter.id}">${escHtml(chapter.name)}</span>
        <span class="chapter-meta">${projectCount} 视频</span>
        <div class="chapter-actions">
          <button class="icon-action-btn" data-action="add-project-chapter" data-chapter-id="${chapter.id}" title="新建视频">${ICON.plus}<span class="action-label">视频</span></button>
          <button class="icon-action-btn" data-action="edit-chapter" data-chapter-id="${chapter.id}" title="重命名">${ICON.edit}<span class="action-label">修改</span></button>
          <button class="icon-action-btn danger" data-action="delete-chapter" data-chapter-id="${chapter.id}" title="删除章节">${ICON.trash}<span class="action-label">删除</span></button>
        </div>
      </div>
    `;

    node.querySelector('[data-toggle]').addEventListener('click', (e) => {
      e.stopPropagation();
      toggleExpanded(nodeId);
      render();
    });
    node.querySelector('.chapter-name').addEventListener('dblclick', () => startRenameChapter(chapter.id));
    node.querySelector('[data-action="add-project-chapter"]').addEventListener('click', () => createProjectInChapter(chapter.id));
    node.querySelector('[data-action="edit-chapter"]').addEventListener('click', () => startRenameChapter(chapter.id));
    node.querySelector('[data-action="delete-chapter"]').addEventListener('click', () => deleteChapterConfirm(chapter));

    node.addEventListener('dragstart', (e) => handleDragStart(e, 'chapter'));
    node.addEventListener('dragend', handleDragEnd);
    node.addEventListener('dragover', (e) => handleNodeDragOver(e, 'chapter', true));
    node.addEventListener('drop', (e) => handleNodeDrop(e, 'chapter', true));

    if (expanded) {
      const childrenEl = document.createElement('div');
      childrenEl.className = 'chapter-node-children';
      (chapter.projects || []).forEach(p => {
        childrenEl.appendChild(renderProjectLeaf(p));
      });
      if ((chapter.projects || []).length === 0) {
        childrenEl.innerHTML = '<div class="empty-hint">暂无视频项目</div>';
      }
      node.appendChild(childrenEl);
    }

    return node;
  }

  // 视频叶子行
  function renderProjectLeaf(project) {
    const leaf = document.createElement('div');
    leaf.className = 'project-leaf';
    leaf.dataset.projectId = project.id;
    leaf.draggable = true;

    const stepInfo = getStepInfo(project);

    leaf.innerHTML = `
      ${ICON.film}
      <span class="project-name" data-project-id="${project.id}">${escHtml(project.name)}</span>
      <span class="project-step-badge">${stepInfo.label}</span>
      <div class="project-actions">
        <button class="icon-action-btn" data-action="edit-project" data-project-id="${project.id}" title="修改设定">${ICON.edit}<span class="action-label">修改</span></button>
        <button class="icon-action-btn success" data-action="open-project" data-project-id="${project.id}" title="继续设计">${ICON.play}<span class="action-label">继续</span></button>
        <button class="icon-action-btn danger" data-action="delete-project" data-project-id="${project.id}" title="删除">${ICON.trash}<span class="action-label">删除</span></button>
      </div>
    `;

    leaf.querySelector('[data-action="edit-project"]').addEventListener('click', (e) => { e.stopPropagation(); openEditProjectModal(project); });
    leaf.querySelector('[data-action="open-project"]').addEventListener('click', (e) => { e.stopPropagation(); enterWorkspace(project.id); });
    leaf.querySelector('[data-action="delete-project"]').addEventListener('click', (e) => { e.stopPropagation(); deleteProjectFromTree(project); });
    leaf.addEventListener('dblclick', () => enterWorkspace(project.id));
    leaf.addEventListener('dragstart', (e) => handleDragStart(e, 'project'));
    leaf.addEventListener('dragend', handleDragEnd);
    leaf.addEventListener('dragover', (e) => handleNodeDragOver(e, 'project', false));
    leaf.addEventListener('drop', (e) => handleNodeDrop(e, 'project', false));

    return leaf;
  }

  // 独立项目卡片（和课程卡片样式一致，用视频图标区分）
  function renderStandaloneProjectCard(project) {
    const stepInfo = getStepInfo(project);

    const node = document.createElement('div');
    node.className = 'course-card-item standalone-project';
    node.dataset.projectId = project.id;
    node.dataset.dragType = 'project';
    node.draggable = true;

    node.innerHTML = `
      <div class="course-card-header">
        ${ICON.film}
        <span class="course-name" data-project-id="${project.id}">${escHtml(project.name)}</span>
        <span class="course-meta">${stepInfo.label}</span>
        <div class="course-actions">
          <button class="icon-action-btn" data-action="edit-project" data-project-id="${project.id}" title="修改设定">${ICON.edit}<span class="action-label">修改</span></button>
          <button class="icon-action-btn success" data-action="open-project" data-project-id="${project.id}" title="继续设计">${ICON.play}<span class="action-label">继续</span></button>
          <button class="icon-action-btn danger" data-action="delete-project" data-project-id="${project.id}" title="删除">${ICON.trash}<span class="action-label">删除</span></button>
        </div>
      </div>
    `;

    // 点击头部进入工作台
    node.querySelector('.course-card-header').addEventListener('click', (e) => {
      if (e.target.closest('.icon-action-btn')) return;
      enterWorkspace(project.id);
    });
    node.querySelector('[data-action="edit-project"]').addEventListener('click', (e) => { e.stopPropagation(); openEditProjectModal(project); });
    node.querySelector('[data-action="open-project"]').addEventListener('click', (e) => { e.stopPropagation(); enterWorkspace(project.id); });
    node.querySelector('[data-action="delete-project"]').addEventListener('click', (e) => { e.stopPropagation(); deleteProjectFromTree(project); });

    node.addEventListener('dragstart', (e) => handleDragStart(e, 'project'));
    node.addEventListener('dragend', handleDragEnd);
    node.addEventListener('dragover', (e) => handleNodeDragOver(e, 'project', false));
    node.addEventListener('drop', (e) => handleNodeDrop(e, 'project', false));

    return node;
  }

  function getStepInfo(project) {
    try {
      const step = resolveProjectVisibleStep(project);
      const num = visibleStepNumber(step);
      const label = `第 ${num} 步 · ${visibleStepLabel(step)}`;
      return { num, label };
    } catch (e) {
      return { num: 1, label: '第 1 步 · 导入文章' };
    }
  }

  // ===== 快速新建（自动聚焦重命名）=====

  async function createCourseQuick() {
    try {
      const course = await API.post('/api/courses', {});
      if (!course || !course.id) return;
      expandedNodes.add(`course-${course.id}`);
      saveExpanded();
      await load();
      setTimeout(() => startRenameCourse(course.id, true), 100);
    } catch (e) {
      showToast('新建课程失败');
    }
  }

  async function createChapterQuick(courseId) {
    try {
      const chapter = await API.post(`/api/courses/${courseId}/chapters`, {});
      if (!chapter || !chapter.id) return;
      expandedNodes.add(`course-${courseId}`);
      expandedNodes.add(`chapter-${chapter.id}`);
      saveExpanded();
      await load();
      setTimeout(() => startRenameChapter(chapter.id, true), 100);
    } catch (e) {
      showToast('新建章节失败');
    }
  }

  // 新建视频到课程/章节：不再直接创建，而是记录目标父级，然后打开新建弹窗
  // 由 createProject() 在确认后读取 pendingProjectParent 完成挂载
  function createProjectInCourse(courseId) {
    pendingProjectParent = { course_id: courseId, chapter_id: null };
    openCreateProjectModal();
  }

  function createProjectInChapter(chapterId) {
    pendingProjectParent = { chapter_id: chapterId };
    openCreateProjectModal();
  }

  // 打开新建项目弹窗（复用 modal-create），清空表单
  function openCreateProjectModal() {
    const modal = document.getElementById('modal-create');
    if (!modal) { showToast('新建弹窗未就绪'); return; }
    document.getElementById('input-project-name').value = '';
    document.getElementById('input-project-desc').value = '';
    // 同步父级挂载目标给全局桥接函数读取
    window.__pendingProjectParent = pendingProjectParent;
    modal.style.display = 'flex';
  }

  // ===== 内联重命名 =====

  function startRenameCourse(courseId, isNew = false) {
    const nameEl = document.querySelector(`[data-course-name="${courseId}"]`);
    if (!nameEl) return;
    startInlineRename(nameEl, courseId, 'course', isNew);
  }

  function startRenameChapter(chapterId, isNew = false) {
    const nameEl = document.querySelector(`[data-chapter-name="${chapterId}"]`);
    if (!nameEl) return;
    startInlineRename(nameEl, chapterId, 'chapter', isNew);
  }

  function startInlineRename(nameEl, id, type, isNew) {
    const oldText = nameEl.textContent;
    const fontSize = window.getComputedStyle(nameEl).fontSize;

    nameEl.innerHTML = `<input type="text" class="inline-rename-input" value="${escHtml(oldText)}" style="font-size:${fontSize};" />`;
    const input = nameEl.querySelector('input');
    if (!input) return;

    input.focus();
    input.select();

    let committed = false;

    const commit = async () => {
      if (committed) return;
      committed = true;
      const newName = input.value.trim();
      if (!newName || newName === oldText) {
        nameEl.textContent = oldText;
        return;
      }
      try {
        const url = type === 'course' ? `/api/courses/${id}` : `/api/chapters/${id}`;
        await API.patch(url, { name: newName });
        nameEl.textContent = newName;
        showToast(type === 'course' ? '课程已重命名' : '章节已重命名');
      } catch (e) {
        nameEl.textContent = oldText;
      }
    };

    const cancel = () => {
      if (committed) return;
      committed = true;
      nameEl.textContent = oldText;
    };

    input.addEventListener('blur', commit);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
      else if (e.key === 'Escape') { e.preventDefault(); cancel(); }
    });
  }

  // ===== 删除 =====

  function deleteCourseConfirm(course) {
    showCustomConfirm(
      '删除课程确认',
      `确定删除课程"${course.name}"吗？课程下的章节会被删除，视频项目会变为独立项目。`,
      async () => {
        try {
          await API.delete(`/api/courses/${course.id}`);
          showToast('课程已删除');
          await load();
        } catch (e) { showToast('删除失败'); }
      }
    );
  }

  function deleteChapterConfirm(chapter) {
    showCustomConfirm(
      '删除章节确认',
      `确定删除章节"${chapter.name}"吗？章节下的视频项目会归到课程的未归类列表。`,
      async () => {
        try {
          await API.delete(`/api/chapters/${chapter.id}`);
          showToast('章节已删除');
          await load();
        } catch (e) { showToast('删除失败'); }
      }
    );
  }

  function deleteProjectFromTree(project) {
    showCustomConfirm(
      '删除项目确认',
      `确定永久删除视频项目"${project.name}"及其全部素材和视频吗？此操作无法撤销。`,
      async () => {
        try {
          await API.delete(`/api/projects/${project.id}`);
          showToast('项目已删除');
          await load();
        } catch (e) { showToast('删除失败'); }
      }
    );
  }

  // ===== 拖拽排序 + 移动（统一分发）=====
  // 支持矩阵：
  //   视频 → 视频：同容器排序（前/后指示线）；跨容器则顺势加入目标容器
  //   视频 → 章节 / 课程：嵌入到目标容器末尾
  //   视频 → 空白区：拖出变为独立项目
  //   章节 → 章节：同课程排序 或 跨课程移动（后端自动改名）
  //   章节 → 课程：移动到该课程
  //   课程 → 课程：排序

  let dragData = null;       // { type: 'project'|'chapter'|'course', id }
  let lastDropTarget = null; // 当前显示指示线的元素

  function clearDropFeedback() {
    document.querySelectorAll('.drop-indicator-before,.drop-indicator-after,.drop-embed,.dragging-node')
      .forEach(el => el.classList.remove('drop-indicator-before', 'drop-indicator-after', 'drop-embed', 'dragging-node'));
    lastDropTarget = null;
  }

  function handleDragStart(e, type) {
    const id = e.currentTarget.dataset[type + 'Id'];
    if (!id) { e.preventDefault(); return; }
    dragData = { type, id };
    e.dataTransfer.effectAllowed = 'move';
    try { e.dataTransfer.setData('text/plain', id); } catch (_) {}
    e.stopPropagation(); // 内层可拖元素优先（视频 > 章节 > 课程）
    e.currentTarget.classList.add('dragging-node');
    document.body.classList.add('course-drag-active');
  }

  function handleDragEnd() {
    dragData = null;
    document.body.classList.remove('course-drag-active');
    clearDropFeedback();
  }

  function isDropAllowed(srcType, targetType) {
    if (srcType === 'project') return ['project', 'chapter', 'course', 'blank'].includes(targetType);
    if (srcType === 'chapter') return targetType === 'chapter' || targetType === 'course';
    if (srcType === 'course') return targetType === 'course';
    return false;
  }

  function computeRawZone(e, rect, allowEmbed) {
    const y = e.clientY - rect.top;
    if (!allowEmbed) return y < rect.height / 2 ? 'before' : 'after';
    if (y < rect.height * 0.3) return 'before';
    if (y > rect.height * 0.7) return 'after';
    return 'embed';
  }

  function effectiveZone(srcType, targetType, rawZone) {
    if (srcType === 'project' && (targetType === 'chapter' || targetType === 'course')) return 'embed';
    if (rawZone === 'embed') return 'before'; // 同级元素不支持嵌入，回退为"插到前面"
    return rawZone;
  }

  function applyDropIndicator(targetEl, zone) {
    if (lastDropTarget && lastDropTarget !== targetEl) {
      lastDropTarget.classList.remove('drop-indicator-before', 'drop-indicator-after', 'drop-embed');
    }
    targetEl.classList.remove('drop-indicator-before', 'drop-indicator-after', 'drop-embed');
    if (zone === 'embed') targetEl.classList.add('drop-embed');
    else targetEl.classList.add(zone === 'after' ? 'drop-indicator-after' : 'drop-indicator-before');
    lastDropTarget = targetEl;
  }

  function handleNodeDragOver(e, targetType, allowEmbed) {
    if (!dragData) return;
    if (!isDropAllowed(dragData.type, targetType)) return; // 不阻止冒泡，交由上层合法目标接管
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    e.stopPropagation();
    const rect = e.currentTarget.getBoundingClientRect();
    const zone = effectiveZone(dragData.type, targetType, computeRawZone(e, rect, allowEmbed));
    applyDropIndicator(e.currentTarget, zone);
  }

  async function handleNodeDrop(e, targetType, allowEmbed) {
    if (!dragData) return;
    if (!isDropAllowed(dragData.type, targetType)) return; // 冒泡到上层
    e.preventDefault();
    e.stopPropagation();
    const rect = e.currentTarget.getBoundingClientRect();
    const zone = effectiveZone(dragData.type, targetType, computeRawZone(e, rect, allowEmbed));
    const src = dragData;
    dragData = null;
    document.body.classList.remove('course-drag-active');
    clearDropFeedback();
    try {
      await dispatchDrop(src, targetType, e.currentTarget, zone);
    } catch (err) {
      console.error('拖拽放置失败:', err);
    }
  }

  // 空白区：仅视频可拖出变独立
  function handleBlankDragOver(e) {
    if (!dragData || dragData.type !== 'project') return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (lastDropTarget) clearDropFeedback();
  }

  async function handleBlankDrop(e) {
    if (!dragData || dragData.type !== 'project') return;
    e.preventDefault();
    const src = dragData;
    dragData = null;
    document.body.classList.remove('course-drag-active');
    clearDropFeedback();
    try {
      await makeProjectStandalone(src.id);
      showToast('已移出，变为独立项目');
      await load();
    } catch (err) {
      showToast('移出失败');
    }
  }

  // ===== 基于 treeData 的查找（不受折叠状态影响）=====

  function findCourse(courseId) {
    return ((treeData && treeData.courses) || []).find(c => c.id === courseId) || null;
  }

  function findChapter(chapterId) {
    for (const c of ((treeData && treeData.courses) || [])) {
      const ch = (c.chapters || []).find(x => x.id === chapterId);
      if (ch) return { chapter: ch, course: c };
    }
    return null;
  }

  function findProjectContainer(projectId) {
    const standalone = (treeData && treeData.standalone_projects) || [];
    if (standalone.some(p => p.id === projectId)) {
      return { containerIds: standalone.map(p => p.id), courseId: null, chapterId: null };
    }
    for (const c of ((treeData && treeData.courses) || [])) {
      if ((c.unchaptered_projects || []).some(p => p.id === projectId)) {
        return { containerIds: (c.unchaptered_projects || []).map(p => p.id), courseId: c.id, chapterId: null };
      }
      for (const ch of (c.chapters || [])) {
        if ((ch.projects || []).some(p => p.id === projectId)) {
          return { containerIds: (ch.projects || []).map(p => p.id), courseId: c.id, chapterId: ch.id };
        }
      }
    }
    return null;
  }

  function insertRelative(ids, draggedId, targetId, zone) {
    const result = ids.filter(id => id !== draggedId);
    const idx = result.indexOf(targetId);
    if (idx === -1) result.push(draggedId);
    else if (zone === 'after') result.splice(idx + 1, 0, draggedId);
    else result.splice(idx, 0, draggedId);
    return result;
  }

  // ===== 放置分发 =====

  async function dispatchDrop(src, targetType, targetEl, zone) {
    if (src.type === 'project') {
      if (targetType === 'project') {
        if (src.id === targetEl.dataset.projectId) return;
        await reorderProjectsRelativeTo(src.id, targetEl.dataset.projectId, zone);
        showToast('已调整视频顺序');
      } else if (targetType === 'chapter') {
        await moveProjectIntoChapter(src.id, targetEl.dataset.chapterId);
        expandedNodes.add(`chapter-${targetEl.dataset.chapterId}`);
        saveExpanded();
        showToast('已移入章节');
      } else if (targetType === 'course') {
        await moveProjectToCourseUnchaptered(src.id, targetEl.dataset.courseId);
        expandedNodes.add(`course-${targetEl.dataset.courseId}`);
        saveExpanded();
        showToast('已移入课程');
      }
      await load();
      return;
    }
    if (src.type === 'chapter') {
      if (targetType === 'course') {
        await moveChapterToCourse(src.id, targetEl.dataset.courseId);
        expandedNodes.add(`course-${targetEl.dataset.courseId}`);
        saveExpanded();
        showToast('章节已移动到课程');
        await load();
        return;
      }
      if (targetType === 'chapter') {
        if (src.id === targetEl.dataset.chapterId) return;
        await reorderOrMoveChapter(src.id, targetEl.dataset.chapterId, zone);
        await load();
        return;
      }
    }
    if (src.type === 'course' && targetType === 'course') {
      if (src.id === targetEl.dataset.courseId) return;
      await reorderCoursesRelativeTo(src.id, targetEl.dataset.courseId, zone);
      showToast('课程顺序已更新');
      await load();
    }
  }

  // ===== 视频（项目）操作 =====

  async function reorderProjectsRelativeTo(draggedId, targetProjectId, zone) {
    const container = findProjectContainer(targetProjectId);
    if (!container) return;
    const ids = insertRelative(container.containerIds, draggedId, targetProjectId, zone);
    await API.patch('/api/projects/reorder', { ordered_ids: ids, course_id: container.courseId, chapter_id: container.chapterId });
  }

  async function moveProjectIntoChapter(projectId, chapterId) {
    const found = findChapter(chapterId);
    const existing = found ? (found.chapter.projects || []).map(p => p.id) : [];
    const ids = [...existing.filter(id => id !== projectId), projectId];
    await API.patch('/api/projects/reorder', { ordered_ids: ids, chapter_id: chapterId });
  }

  async function moveProjectToCourseUnchaptered(projectId, courseId) {
    const course = findCourse(courseId);
    const existing = course ? (course.unchaptered_projects || []).map(p => p.id) : [];
    const ids = [...existing.filter(id => id !== projectId), projectId];
    await API.patch('/api/projects/reorder', { ordered_ids: ids, course_id: courseId, chapter_id: null });
  }

  async function makeProjectStandalone(projectId) {
    const existing = ((treeData && treeData.standalone_projects) || []).map(p => p.id);
    const ids = [...existing.filter(id => id !== projectId), projectId];
    await API.patch('/api/projects/reorder', { ordered_ids: ids, course_id: null, chapter_id: null });
  }

  // ===== 章节操作 =====

  async function reorderOrMoveChapter(draggedId, targetChapterId, zone) {
    const dragFound = findChapter(draggedId);
    const targetFound = findChapter(targetChapterId);
    if (!dragFound || !targetFound) return;
    if (dragFound.course.id !== targetFound.course.id) {
      await API.post(`/api/chapters/${draggedId}/move`, { course_id: targetFound.course.id });
      showToast('章节已移动到目标课程');
      return;
    }
    const ids = insertRelative((targetFound.course.chapters || []).map(c => c.id), draggedId, targetChapterId, zone);
    await API.patch(`/api/chapters/reorder?course_id=${encodeURIComponent(targetFound.course.id)}`, { ordered_ids: ids });
    showToast('章节顺序已更新');
  }

  async function moveChapterToCourse(chapterId, courseId) {
    await API.post(`/api/chapters/${chapterId}/move`, { course_id: courseId });
  }

  // ===== 课程操作 =====

  async function reorderCoursesRelativeTo(draggedId, targetCourseId, zone) {
    const ids0 = ((treeData && treeData.courses) || []).map(c => c.id);
    const ids = insertRelative(ids0, draggedId, targetCourseId, zone);
    await API.patch('/api/courses/reorder', { ordered_ids: ids });
  }

  // ===== 公开 API =====

  return {
    init,
    load,
    render,
    createCourseQuick,
    createChapterQuick,
  };
})();

// 桥接：把原有的 loadProjects() 重定向到 CourseTree，
// 这样 event_bindings.js / projects.js / workspace_navigation.js
// 里的所有 loadProjects() 调用都会自动渲染课程树，无需改动现有文件。
window.loadProjects = function loadProjectsViaCourseTree() {
  try { CourseTree.init(); } catch (e) { /* ignore */ }
  return CourseTree.load();
};

// 桥接：完全接管 createProject()，新建视频后停在课程与项目主页（不跳转工作台）。
// 如果是从课程/章节触发的创建（__pendingProjectParent 有值），创建后自动移动到父级。
(function overrideCreateProjectForTree() {
  if (typeof window.createProject !== 'function' || window.createProject.__treeOverridden) return;

  const overridden = async function createProjectStayHome() {
    const parent = window.__pendingProjectParent || null;

    // 读取表单
    const nameEl = document.getElementById('input-project-name');
    const descEl = document.getElementById('input-project-desc');
    const modeEl = document.getElementById('input-project-ai-mode');
    const name = (nameEl?.value || '').trim();
    const description = (descEl?.value || '').trim();
    const aiMode = (modeEl?.value || 'auto').trim();

    if (!name) { showToast('请输入项目名称'); return; }

    // 创建项目
    const result = await API.post('/api/projects', { name, description, ai_mode: aiMode });
    if (!result || !result.success) return;

    // 关闭弹窗
    document.getElementById('modal-create').style.display = 'none';
    showToast('视频创建成功');

    // 移动到父级（课程/章节）
    if (parent) {
      try {
        await API.post(`/api/projects/${result.project.id}/move`, parent);
      } catch (e) {
        showToast('视频移动失败，已创建为独立项目');
      }
      window.__pendingProjectParent = null;
    }

    // 刷新课程树，停在主页（不调用 enterWorkspace）
    await CourseTree.load();
  };

  overridden.__treeOverridden = true;
  window.createProject = overridden;
})();

// 修改项目设定（弹窗，不跳转工作台）
function openEditProjectModal(project) {
  const modal = document.getElementById('modal-edit-project');
  if (!modal) { showToast('修改弹窗未就绪'); return; }
  document.getElementById('edit-project-id').value = project.id;
  document.getElementById('edit-project-name').value = project.name || '';
  document.getElementById('edit-project-desc').value = project.description || '';
  const modeSelect = document.getElementById('edit-project-ai-mode');
  if (modeSelect) modeSelect.value = project.ai_mode || 'auto';
  modal.style.display = 'flex';
}

async function saveEditProject() {
  const id = document.getElementById('edit-project-id').value;
  const name = document.getElementById('edit-project-name').value.trim();
  const description = document.getElementById('edit-project-desc').value.trim();
  const aiMode = (document.getElementById('edit-project-ai-mode')?.value || 'auto').trim();

  if (!name) { showToast('项目名称不能为空'); return; }

  const result = await API.put(`/api/projects/${id}`, { name, description, ai_mode: aiMode });
  if (!result || !result.success) { showToast('修改失败'); return; }

  document.getElementById('modal-edit-project').style.display = 'none';
  showToast('项目设定已更新');
  await CourseTree.load();
}

window.openEditProjectModal = openEditProjectModal;
window.saveEditProject = saveEditProject;

