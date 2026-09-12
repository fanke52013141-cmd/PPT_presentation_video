/**
 * 课程项目管理：树形视图（课程 → 章节 → 视频）
 *
 * 功能：
 * - 递归渲染三级树结构（课程卡片 / 章节行 / 视频行）
 * - 折叠/展开（记忆到 localStorage）
 * - 快速新建（自动聚焦重命名，Enter确认/Esc默认名）
 * - 双击节点重命名
 * - 拖拽排序 + 跨层级移动
 * - 独立视频项目（独立项目也用卡片样式，通过图标区分）
 *
 * 注意：顶部标题和按钮由 index.html 提供，本组件只负责 #project-list 内的树主体。
 */

const CourseTree = (() => {
  const STORAGE_KEY = 'courseTree.expanded';
  let treeData = null;
  let expandedNodes = new Set();
  // Persisted state always wins.  The homepage's initial tree only opens the
  // first course when this browser has never saved an explicit choice.
  let hasPersistedExpansionState = false;
  let hasAppliedDefaultExpansion = false;
  // 首页库的当前筛选只属于本次页面会话；真实课程树仍始终由
  // /api/courses/tree 提供，筛选不会改动课程、章节或项目的归属。
  let libraryFilter = { type: 'all', id: null };
  // 搜索同样只在浏览器内生效。它基于当前真实树的项目、课程和
  // 章节名称过滤，不请求或改写服务器数据。
  let librarySearchQuery = '';
  // 记录"新建视频"的目标父级（由课程/章节的 +视频 按钮设置，
  // createProject() 在确认创建后会读取并移动项目）
  let pendingProjectParent = null;

  // ===== 图标：与 Stitch 参考稿 1:1 的原始 SVG。
  // 不使用全局 .icon 类——那条规则 fill:none; stroke:currentColor 会覆盖
  // 实心图标的 fill，导致"更多"三个点变成空心描边。=====
  const ICON = {
    chevronDown: '<svg class="stitch-ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 9l-7 7-7-7"></path></svg>',
    chevronRight: '<svg class="stitch-ic" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"></path></svg>',
    grid: '<svg class="stitch-ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect height="6" rx="1.5" width="6" x="3" y="3"></rect><rect height="6" rx="1.5" width="6" x="15" y="3"></rect><rect height="6" rx="1.5" width="6" x="3" y="15"></rect><rect height="6" rx="1.5" width="6" x="15" y="15"></rect></svg>',
    book: '<svg class="stitch-ic" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path><path d="M8 7h8"></path><path d="M8 11h6"></path></svg>',
    folder: '<svg class="stitch-ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"><path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"></path></svg>',
    edit: '<svg class="stitch-ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"><path d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10"></path></svg>',
    trash: '<svg class="stitch-ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>',
    plus: '<svg class="stitch-ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"></path></svg>',
    plusCircle: '<svg class="stitch-ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"></circle><path d="M12 8v8m4-4H8"></path></svg>',
    circlePlusLarge: '<svg class="stitch-ic" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="9" stroke-width="1.8"></circle><path d="M12 8v8m4-4H8" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"></path></svg>',
    playTiny: '<svg class="stitch-ic" width="8" height="8" viewBox="0 0 24 24" fill="currentColor" style="margin-left:1px"><polygon points="6 4 20 12 6 20 6 4"></polygon></svg>',
    playMenu: '<svg class="stitch-ic" width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20 6 4"></polygon></svg>',
    more: '<svg class="stitch-ic" width="14" height="14" viewBox="0 0 20 20" fill="currentColor"><circle cx="5" cy="10" r="1.5"></circle><circle cx="10" cy="10" r="1.5"></circle><circle cx="15" cy="10" r="1.5"></circle></svg>',
    search: '<svg class="stitch-ic" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>',
  };

  // ===== 初始化 =====

  function init() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved !== null) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) {
          expandedNodes = new Set(parsed);
          hasPersistedExpansionState = true;
        }
      }
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

  function applyDefaultExpansion(courseList) {
    if (hasPersistedExpansionState || hasAppliedDefaultExpansion || !courseList.length) return;
    const firstCourse = courseList[0];
    expandedNodes.add(`course-${firstCourse.id}`);
    if (firstCourse.chapters?.length) {
      expandedNodes.add(`chapter-${firstCourse.chapters[0].id}`);
    }
    hasAppliedDefaultExpansion = true;
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

    normalizeLibraryFilter();
    container.className = 'course-tree-container home-library';
    container.innerHTML = '';

    const courseList = treeData.courses || [];
    const standaloneList = treeData.standalone_projects || [];
    applyDefaultExpansion(courseList);
    const videoRecords = collectVideoRecords(courseList, standaloneList);

    const layout = document.createElement('div');
    layout.className = 'home-library-layout stitch-home-layout flex h-full overflow-hidden';

    const navigation = document.createElement('aside');
    navigation.className = 'home-library-navigation stitch-home-sidebar w-72 bg-white border-r border-line-subtle flex flex-col justify-between shrink-0';
    navigation.setAttribute('aria-label', '课程与视频导航');

    const navigationBody = document.createElement('div');
    navigationBody.className = 'home-library-navigation-body stitch-sidebar-body flex-1 overflow-y-auto px-4 pt-3 pb-5 space-y-4';
    navigationBody.appendChild(renderAllVideosSelector());

    const treeEl = document.createElement('div');
    treeEl.className = 'course-tree-body home-library-tree stitch-course-tree space-y-1.5';
    treeEl.setAttribute('role', 'tree');

    const curriculumHeading = document.createElement('div');
    curriculumHeading.className = 'home-library-navigation-heading stitch-tree-section-heading flex items-center justify-between px-2 pt-1';
    const curriculumLabel = document.createElement('span');
    curriculumLabel.textContent = `课程体系 (${courseList.length})`;
    const createCourse = document.createElement('button');
    createCourse.type = 'button';
    createCourse.className = 'stitch-tree-add-course icon-btn-hover';
    createCourse.title = '添加课程';
    createCourse.setAttribute('aria-label', '添加课程');
    createCourse.innerHTML = ICON.plus;
    createCourse.addEventListener('click', createCourseQuick);
    curriculumHeading.append(curriculumLabel, createCourse);
    // Keep the two visual regions named separately for styling while the
    // sidebar itself remains one continuous scroll surface.  This is
    // layout-only; the existing tree nodes and event handlers remain unchanged.
    const curriculumGroup = document.createElement('div');
    curriculumGroup.className = 'stitch-curriculum-group';
    curriculumGroup.appendChild(curriculumHeading);
    courseList.forEach(course => curriculumGroup.appendChild(renderCourseNode(course)));
    treeEl.appendChild(curriculumGroup);

    const standaloneGroup = document.createElement('div');
    standaloneGroup.className = 'stitch-standalone-group';
    if (standaloneList.length > 0) {
      const standaloneHeading = document.createElement('div');
      standaloneHeading.className = 'course-tree-standalone-heading stitch-tree-section-heading';
      standaloneHeading.textContent = `独立视频 (${standaloneList.length})`;
      standaloneGroup.appendChild(standaloneHeading);
      standaloneList.forEach(project => standaloneGroup.appendChild(renderStandaloneProjectCard(project)));
    }
    treeEl.appendChild(standaloneGroup);
    navigationBody.appendChild(treeEl);
    navigation.appendChild(navigationBody);

    const navigationFooter = document.createElement('div');
    navigationFooter.className = 'home-library-navigation-footer stitch-sidebar-footer border-t border-line-subtle p-3';
    const footerCreate = document.createElement('button');
    footerCreate.type = 'button';
    footerCreate.className = 'stitch-sidebar-create-video w-full';
    footerCreate.innerHTML = `${ICON.circlePlusLarge}<span>新建视频</span>`;
    footerCreate.addEventListener('click', createStandaloneVideoFromLibrary);
    navigationFooter.appendChild(footerCreate);
    navigation.appendChild(navigationFooter);

    const main = document.createElement('section');
    main.className = 'home-library-main stitch-home-main flex-1 flex flex-col overflow-y-auto px-8 py-7 bg-surface-page';
    main.setAttribute('aria-live', 'polite');
    const mainHeader = document.createElement('div');
    mainHeader.className = 'home-library-main-header stitch-main-header flex flex-col gap-1.5 mb-7 pb-1';
    const heading = document.createElement('div');
    heading.className = 'home-library-main-heading stitch-main-heading flex items-center justify-between gap-4';
    const title = document.createElement('h2');
    title.className = 'home-library-main-title';
    title.textContent = libraryFilterTitle();
    const titleWrap = document.createElement('div');
    titleWrap.className = 'stitch-main-title-wrap flex items-baseline gap-2';
    titleWrap.append(title);
    heading.append(titleWrap, renderLibrarySearchTools());
    // 标题本身已完整表达当前筛选；不再重复渲染一行“全部视频”面包屑。
    mainHeader.append(heading);
    main.appendChild(mainHeader);

    const cards = document.createElement('div');
    cards.className = 'home-library-video-grid stitch-video-grid grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5 gap-5 pb-8';
    cards.id = 'home-library-video-results';
    // 入场动画只在每次页面加载后的首次渲染播放一次；搜索等重渲染不再闪动
    if (!container.dataset.animated) {
      cards.classList.add('first-paint');
      container.dataset.animated = '1';
      setTimeout(() => cards.classList.remove('first-paint'), 900);
    }
    const visibleRecords = filterVideoRecords(videoRecords);
    cards.appendChild(renderNewVideoCard());
    visibleRecords.forEach(record => cards.appendChild(renderLibraryVideoCard(record)));
    if (visibleRecords.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'course-tree-empty home-library-empty';
      const message = document.createElement('p');
      message.textContent = librarySearchQuery.trim()
        ? '没有找到匹配的视频、课程或章节。'
        : videoRecords.length
          ? '这个分类下还没有视频项目。'
          : '还没有任何课程或视频项目，先创建一个开始吧。';
      empty.appendChild(message);
      const action = document.createElement('button');
      action.type = 'button';
      action.className = 'success';
      action.textContent = librarySearchQuery.trim()
        ? '清除搜索'
        : videoRecords.length ? '查看全部视频' : '新建课程';
      action.addEventListener('click', () => {
        if (librarySearchQuery.trim()) clearLibrarySearch();
        else if (videoRecords.length) selectLibraryFilter({ type: 'all', id: null });
        else document.getElementById('btn-create-course')?.click();
      });
      empty.appendChild(action);
      cards.appendChild(empty);
    }
    main.appendChild(cards);

    layout.append(navigation, main);
    container.appendChild(layout);
  }

  function normalizeLibraryFilter() {
    if (libraryFilter.type === 'course' && !findCourse(libraryFilter.id)) {
      libraryFilter = { type: 'all', id: null };
    } else if (libraryFilter.type === 'chapter' && !findChapter(libraryFilter.id)) {
      libraryFilter = { type: 'all', id: null };
    }
  }

  function selectLibraryFilter(nextFilter) {
    libraryFilter = nextFilter;
    render();
  }

  function renderLibrarySearchTools() {
    const tools = document.createElement('div');
    tools.className = 'home-library-search-tools stitch-search-tools flex items-center space-x-3';
    tools.setAttribute('role', 'search');

    const label = document.createElement('label');
    label.className = 'home-library-search-label sr-only';
    label.htmlFor = 'home-library-search-input';
    label.textContent = '搜索视频库';

    const input = document.createElement('input');
    input.id = 'home-library-search-input';
    input.className = 'home-library-search-input stitch-search-input w-full h-9 pl-9 pr-4 rounded-lg bg-surface-card border border-line-border';
    input.type = 'search';
    input.placeholder = '搜索视频名称或标签';
    input.autocomplete = 'off';
    input.value = librarySearchQuery;
    input.setAttribute('aria-describedby', 'home-library-search-help');
    input.addEventListener('input', (event) => {
      const nextInput = event.currentTarget;
      const selectionStart = nextInput.selectionStart;
      const selectionEnd = nextInput.selectionEnd;
      librarySearchQuery = nextInput.value;
      render();

      // render() 会重建卡片和筛选树；恢复焦点，让连续输入仍是自然的
      // 本地搜索体验，而不必引入额外状态管理或服务端接口。
      const replacement = document.getElementById('home-library-search-input');
      if (replacement) {
        replacement.focus();
        if (selectionStart !== null && selectionEnd !== null) {
          replacement.setSelectionRange(selectionStart, selectionEnd);
        }
      }
    });

    const help = document.createElement('span');
    help.id = 'home-library-search-help';
    help.className = 'home-library-search-help';
    help.textContent = '按视频名称、课程或章节筛选';

    const searchIcon = document.createElement('span');
    searchIcon.className = 'stitch-search-icon';
    searchIcon.setAttribute('aria-hidden', 'true');
    searchIcon.innerHTML = ICON.search;
    const field = document.createElement('div');
    field.className = 'stitch-search-field relative w-64 group';
    field.append(searchIcon, input);
    tools.append(label, field, help);
    if (librarySearchQuery.trim()) {
      const clear = document.createElement('button');
      clear.type = 'button';
      clear.className = 'secondary home-library-search-clear';
      clear.textContent = '清除';
      clear.addEventListener('click', clearLibrarySearch);
      tools.appendChild(clear);
    }
    return tools;
  }

  function clearLibrarySearch() {
    librarySearchQuery = '';
    render();
    document.getElementById('home-library-search-input')?.focus();
  }

  function isLibraryFilterSelected(type, id = null) {
    return libraryFilter.type === type && libraryFilter.id === id;
  }

  function renderAllVideosSelector() {
    // 设计稿中"全部视频"行右侧是常显的"更多操作"菜单（新建视频/新建课程）
    const wrap = document.createElement('div');
    wrap.className = 'stitch-all-videos-wrap';

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'home-library-all-videos-selector stitch-all-videos-selector flex items-center justify-between px-3 py-2 rounded-xl';
    button.setAttribute('aria-pressed', String(isLibraryFilterSelected('all')));
    if (isLibraryFilterSelected('all')) button.classList.add('is-selected');
    button.innerHTML = `<span class="stitch-all-videos-leading">${ICON.grid}<span>全部视频</span></span>`;
    button.addEventListener('click', () => selectLibraryFilter({ type: 'all', id: null }));

    const overflowHost = document.createElement('div');
    overflowHost.innerHTML = renderTreeOverflowMenu('库操作', [
      { action: 'library-new-video', idAttribute: '', title: '新建视频', label: '新建视频', icon: ICON.plusCircle },
      { action: 'library-new-course', idAttribute: '', title: '新建课程', label: '新建课程', icon: ICON.plus },
    ]);
    const overflow = overflowHost.firstElementChild;
    overflow.classList.add('stitch-all-videos-overflow');
    overflow.querySelector('[data-action="library-new-video"]').addEventListener('click', (e) => {
      e.stopPropagation();
      createStandaloneVideoFromLibrary();
    });
    overflow.querySelector('[data-action="library-new-course"]').addEventListener('click', (e) => {
      e.stopPropagation();
      createCourseQuick();
    });

    wrap.append(button, overflow);
    bindTreeOverflow(wrap);
    return wrap;
  }

  function collectVideoRecords(courseList, standaloneList) {
    const records = [];
    courseList.forEach(course => {
      (course.chapters || []).forEach(chapter => {
        (chapter.projects || []).forEach(project => records.push({ project, course, chapter }));
      });
      (course.unchaptered_projects || []).forEach(project => records.push({ project, course, chapter: null }));
    });
    standaloneList.forEach(project => records.push({ project, course: null, chapter: null }));
    return records;
  }

  function filterVideoRecords(records) {
    let filtered = records;
    if (libraryFilter.type === 'course') {
      filtered = records.filter(record => record.course?.id === libraryFilter.id);
    } else if (libraryFilter.type === 'chapter') {
      filtered = records.filter(record => record.chapter?.id === libraryFilter.id);
    }

    const query = librarySearchQuery.trim().toLocaleLowerCase('zh-CN');
    if (!query) return filtered;
    return filtered.filter(record => [
      record.project?.name,
      record.course?.name,
      record.chapter?.name,
    ].some(value => String(value || '').toLocaleLowerCase('zh-CN').includes(query)));
  }

  function libraryFilterTitle() {
    if (libraryFilter.type === 'course') return findCourse(libraryFilter.id)?.name || '全部视频';
    if (libraryFilter.type === 'chapter') return findChapter(libraryFilter.id)?.chapter?.name || '全部视频';
    return '全部视频';
  }

  function libraryRecordLabel(record) {
    // 设计稿的卡片角标只显示课程名，独立视频显示"独立视频"
    if (!record.course) return '独立视频';
    return record.course.name;
  }

  function projectProgress(project) {
    try {
      const completedProgress = calculateVisibleProgress(project.step_status || {}, projectFlowContext(project));
      const completedSteps = Math.round(Math.max(0, Math.min(100, Number(completedProgress) || 0)) / 100 * 7);
      // A project at its current workflow step is visibly in progress even
      // when that step has not been confirmed yet. Keep the card indicator
      // faithful to the user-facing 1..7 stage model without changing state.
      const currentStep = Math.max(1, Math.min(7, Number(getStepInfo(project).num) || 1));
      return Math.round(Math.max(completedSteps, currentStep) / 7 * 100);
    } catch (_) {
      const step = getStepInfo(project).num;
      return Math.round(Math.max(1, Math.min(7, step)) / 7 * 100);
    }
  }

  function renderNewVideoCard() {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'home-library-video-card home-library-new-video-card stitch-new-video-card group relative border-2 border-dashed border-line-border rounded-xl p-5 flex flex-col items-center justify-center text-center min-h-[220px]';
    card.setAttribute('aria-label', '新建视频');

    const preview = document.createElement('span');
    preview.className = 'home-library-video-preview stitch-new-video-icon w-11 h-11 rounded-full';
    // 预览里包含常驻操作按钮，因此不能对整个区域标记 aria-hidden。
    preview.innerHTML = ICON.plus;

    const content = document.createElement('span');
    content.className = 'home-library-video-content stitch-new-video-content';
    const name = document.createElement('strong');
    name.className = 'home-library-video-name stitch-new-video-name';
    name.textContent = '新建视频';
    content.append(name);
    card.append(preview, content);
    card.addEventListener('click', createStandaloneVideoFromLibrary);
    return card;
  }

  function createStandaloneVideoFromLibrary() {
    // 课程/章节入口会预设目标父级；首页首卡明确对应独立视频，避免
    // 已取消的嵌套创建意外影响本次新建。
    pendingProjectParent = null;
    window.__pendingProjectParent = null;
    const createButton = document.getElementById('btn-create-project');
    if (!createButton) {
      showToast('新建视频弹窗未就绪');
      return;
    }
    createButton.click();
  }

  function renderLibraryVideoCard(record) {
    const { project } = record;
    const stepInfo = getStepInfo(project);
    const progress = projectProgress(project);
    const card = document.createElement('article');
    const previewVariant = libraryPreviewVariant(record);
    card.className = `home-library-video-card stitch-video-card group relative bg-surface-card border border-line-border rounded-xl overflow-hidden flex flex-col cursor-pointer animate-fadeInUp ${previewVariant.cardClass}`;
    card.tabIndex = 0;
    card.setAttribute('role', 'button');
    card.setAttribute('aria-label', `打开视频项目：${project.name}`);

    const preview = document.createElement('div');
    preview.className = `home-library-video-preview stitch-video-preview relative aspect-[16/9] w-full overflow-hidden flex items-center justify-center ${previewVariant.previewClass}`;
    // 此区域包含可操作按钮，不能把整个预览从辅助技术树中隐藏。
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'stitch-video-more icon-btn-hover';
    more.setAttribute('aria-label', `视频操作：${project.name || '未命名视频'}`);
    more.innerHTML = ICON.more;
    const menu = document.createElement('div');
    menu.className = 'stitch-video-menu';
    const openFromMenu = createProjectActionButton('继续', ICON.playMenu, 'open-project', project, () => enterWorkspace(project.id));
    const editFromMenu = createProjectActionButton('编辑', ICON.edit, 'edit-project', project, () => openEditProjectModal(project));
    const deleteFromMenu = createProjectActionButton('删除', ICON.trash, 'delete-project', project, () => deleteProjectFromTree(project), false, true);
    menu.append(openFromMenu, editFromMenu, deleteFromMenu);
    const openMenu = () => {
      document.querySelectorAll('.stitch-video-menu.is-open').forEach(open => {
        if (open !== menu) open.classList.remove('is-open');
      });
      menu.classList.add('is-open');
    };
    const closeMenu = () => menu.classList.remove('is-open');
    let closeTimer = null;
    const cancelClose = () => {
      if (closeTimer) window.clearTimeout(closeTimer);
      closeTimer = null;
    };
    const scheduleClose = () => {
      cancelClose();
      closeTimer = window.setTimeout(closeMenu, 90);
    };
    more.addEventListener('mouseenter', openMenu);
    more.addEventListener('focus', openMenu);
    more.addEventListener('mouseleave', scheduleClose);
    more.addEventListener('click', (event) => {
      event.stopPropagation();
      if (menu.classList.contains('is-open')) closeMenu(); else openMenu();
    });
    menu.addEventListener('mouseenter', cancelClose);
    menu.addEventListener('mouseleave', closeMenu);
    const play = document.createElement('span');
    play.className = 'stitch-video-play w-10 h-10 rounded-full';
    play.innerHTML = '<svg class="stitch-ic" width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20 6 4"></polygon></svg>';
    const pattern = document.createElement('span');
    pattern.className = 'stitch-video-pattern';
    preview.append(pattern, more, menu, play);
    if (isProjectComplete(project)) hydrateCompletedVideoCover(project, preview);

    const content = document.createElement('div');
    content.className = 'home-library-video-content stitch-video-content p-3.5 flex flex-col justify-between flex-1';
    const name = document.createElement('h3');
    name.className = 'home-library-video-name stitch-video-name';
    name.textContent = project.name || '未命名视频';

    const progressRow = document.createElement('div');
    progressRow.className = 'home-library-video-progress-row stitch-video-progress-row';
    const progressLabel = document.createElement('span');
    progressLabel.textContent = '进度';
    const progressValue = document.createElement('span');
    const completedSegments = Math.max(0, Math.min(7, Math.round(progress / 100 * 7)));
    progressValue.textContent = `${completedSegments} / 7`;
    progressRow.append(progressLabel, progressValue);
    const progressTrack = document.createElement('div');
    progressTrack.className = 'home-library-video-progress stitch-video-progress grid grid-cols-7 gap-1 h-1.5 w-full';
    progressTrack.setAttribute('role', 'progressbar');
    progressTrack.setAttribute('aria-label', `${project.name} 完成进度`);
    progressTrack.setAttribute('aria-valuemin', '0');
    progressTrack.setAttribute('aria-valuemax', '100');
    progressTrack.setAttribute('aria-valuenow', String(progress));
    for (let index = 0; index < 7; index += 1) {
      const segment = document.createElement('span');
      segment.className = `stitch-progress-segment rounded-full ${index < completedSegments ? 'is-complete bg-emerald-500 progress-bar-fill' : 'bg-neutral-200'}`;
      segment.title = `步骤 ${index + 1}${index < completedSegments ? '：已完成' : '：未完成'}`;
      progressTrack.appendChild(segment);
    }

    const progressBlock = document.createElement('div');
    progressBlock.className = 'stitch-video-progress-block mt-3 space-y-1.5';
    progressBlock.append(progressRow, progressTrack);
    content.append(name, progressBlock);
    card.append(preview, content);
    card.addEventListener('click', (event) => {
      if (!event.target.closest('button')) enterWorkspace(project.id);
    });
    card.addEventListener('keydown', (event) => {
      if (event.target !== card) return;
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        enterWorkspace(project.id);
      }
    });
    return card;
  }

  async function hydrateCompletedVideoCover(project, preview) {
    try {
      const result = await API.get(`/api/projects/${encodeURIComponent(project.id)}/steps/3/images`);
      const firstImage = (result?.images || []).find(image => image?.exists && image?.url);
      if (!firstImage || !preview.isConnected) return;

      const cover = new Image();
      cover.className = 'stitch-card-cover';
      cover.alt = '';
      cover.onload = () => {
        if (!preview.isConnected || !cover.naturalWidth || !cover.naturalHeight) return;
        const ratio = cover.naturalWidth / cover.naturalHeight;
        // 9:16 首帧在横向卡片中裁切后没有可读内容，继续使用默认封面。
        if (ratio >= .52 && ratio <= .60) return;
        preview.classList.add('has-generated-cover');
        if (ratio < 1) preview.classList.add('has-cropped-portrait-cover');
        preview.prepend(cover);
      };
      cover.src = firstImage.url;
    } catch (_) {
      // 卡片预览为非关键增强；接口暂不可用时保持默认封面。
    }
  }

  function isProjectComplete(project) {
    try {
      return Number(calculateVisibleProgress(project.step_status || {}, projectFlowContext(project))) >= 100;
    } catch (_) {
      return false;
    }
  }

  function libraryPreviewVariant(record) {
    const variants = [
      { previewClass: 'stitch-preview-coral', labelClass: 'stitch-label-coral', cardClass: 'stagger-1' },
      { previewClass: 'stitch-preview-blue', labelClass: 'stitch-label-blue', cardClass: 'stagger-2' },
      { previewClass: 'stitch-preview-violet', labelClass: 'stitch-label-violet', cardClass: 'stagger-3' },
      { previewClass: 'stitch-preview-green', labelClass: 'stitch-label-green', cardClass: 'stagger-4' },
      { previewClass: 'stitch-preview-neutral', labelClass: 'stitch-label-neutral', cardClass: 'stagger-5' },
      { previewClass: 'stitch-preview-warm', labelClass: 'stitch-label-neutral', cardClass: 'stagger-6' },
    ];
    const source = `${record.course?.id || 'standalone'}:${record.chapter?.id || ''}:${record.project?.id || ''}`;
    let hash = 0;
    for (let index = 0; index < source.length; index += 1) hash = ((hash << 5) - hash + source.charCodeAt(index)) | 0;
    return variants[Math.abs(hash) % variants.length];
  }

  function createProjectActionButton(label, icon, action, project, callback, primary = false, danger = false) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `icon-action-btn${primary ? ' success' : ''}${danger ? ' danger' : ''}`;
    button.dataset.action = action;
    button.dataset.projectId = project.id;
    button.title = label;
    button.setAttribute('aria-label', `${label}：${project.name || '未命名视频'}`);
    button.innerHTML = `${icon}<span class="action-label">${label}</span>`;
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      callback();
    });
    return button;
  }

  // ===== 树节点"更多操作"下拉菜单（⋯ 触发，点击空白处关闭）=====

  function renderTreeOverflowMenu(menuLabel, actions) {
    const items = actions.map(action => `
      <button type="button" class="tree-overflow-item${action.danger ? ' is-danger' : ''}" data-action="${escHtml(action.action)}" ${action.idAttribute} title="${escHtml(action.title)}">
        ${action.icon || ''}<span>${escHtml(action.label)}</span>
      </button>`).join('');
    return `
      <div class="tree-overflow" role="group" aria-label="${escHtml(menuLabel)}">
        <button type="button" class="tree-overflow-trigger icon-btn-hover" aria-haspopup="menu" aria-expanded="false" aria-label="${escHtml(menuLabel)}">
          ${ICON.more}
        </button>
        <div class="tree-overflow-menu" role="menu" aria-label="${escHtml(menuLabel)}">${items}</div>
      </div>
    `;
  }

  function bindTreeOverflow(rootEl) {
    rootEl.querySelectorAll('.tree-overflow').forEach(overflow => {
      const trigger = overflow.querySelector('.tree-overflow-trigger');
      const menu = overflow.querySelector('.tree-overflow-menu');
      if (!trigger || !menu || trigger.__treeOverflowBound) return;
      trigger.__treeOverflowBound = true;
      let menuPortalized = false;
      const restoreMenu = () => {
        if (!menuPortalized) return;
        overflow.appendChild(menu);
        menu.classList.remove('tree-overflow-menu--portal');
        menu.removeAttribute('style');
        menuPortalized = false;
      };
      const open = () => {
        document.querySelectorAll('.tree-overflow-menu.is-open').forEach(openMenu => {
          if (openMenu !== menu) {
            if (typeof openMenu.__closeTreeOverflow === 'function') {
              openMenu.__closeTreeOverflow();
            } else {
              openMenu.classList.remove('is-open');
            }
          }
        });
        document.querySelectorAll('.tree-overflow-trigger[aria-expanded="true"]').forEach(openTrigger => {
          if (openTrigger !== trigger) openTrigger.setAttribute('aria-expanded', 'false');
        });
        if (!menuPortalized) {
          const rect = trigger.getBoundingClientRect();
          document.body.appendChild(menu);
          menu.classList.add('tree-overflow-menu--portal');
          menu.style.top = `${Math.round(rect.bottom + 4)}px`;
          menu.style.left = `${Math.round(Math.max(8, rect.right - 198))}px`;
          menuPortalized = true;
        }
        menu.classList.add('is-open');
        trigger.setAttribute('aria-expanded', 'true');
      };
      const close = () => {
        menu.classList.remove('is-open');
        trigger.setAttribute('aria-expanded', 'false');
        restoreMenu();
      };
      menu.__closeTreeOverflow = close;
      let closeTimer = null;
      const cancelClose = () => {
        if (closeTimer) window.clearTimeout(closeTimer);
        closeTimer = null;
      };
      const scheduleClose = () => {
        cancelClose();
        // 菜单与触发器之间有视觉间距，留出进入菜单的时间，避免刚移过去就消失。
        closeTimer = window.setTimeout(close, 260);
      };
      overflow.addEventListener('mouseenter', () => { cancelClose(); open(); });
      overflow.addEventListener('mouseleave', scheduleClose);
      menu.addEventListener('mouseenter', cancelClose);
      menu.addEventListener('mouseleave', scheduleClose);
      trigger.addEventListener('click', (event) => {
        event.stopPropagation();
        const willOpen = !menu.classList.contains('is-open');
        if (willOpen) open(); else close();
      });
    });
    if (!document.__treeOverflowDismissBound) {
      document.__treeOverflowDismissBound = true;
      document.addEventListener('click', (event) => {
        if (event.target.closest('.tree-overflow')) return;
        document.querySelectorAll('.tree-overflow-menu.is-open').forEach(menu => {
          if (typeof menu.__closeTreeOverflow === 'function') menu.__closeTreeOverflow();
          else menu.classList.remove('is-open');
        });
        document.querySelectorAll('.tree-overflow-trigger[aria-expanded="true"]').forEach(trigger => {
          trigger.setAttribute('aria-expanded', 'false');
        });
      });
    }
  }

  // 课程卡片
  function renderCourseNode(course) {
    const nodeId = `course-${course.id}`;
    const expanded = isExpanded(nodeId);

    const node = document.createElement('div');
    node.className = 'course-card-item stitch-course-node group space-y-0.5';
    if (isLibraryFilterSelected('course', course.id)) node.classList.add('is-selected');
    node.dataset.courseId = course.id;
    node.draggable = true;
    node.setAttribute('role', 'treeitem');
    node.setAttribute('aria-expanded', String(expanded));

    const chapterCount = course.chapters ? course.chapters.length : 0;
    const projectCount = course.project_count || 0;
    const unchapteredCount = (course.unchaptered_projects || []).length;

    node.innerHTML = `
      <div class="course-card-header stitch-course-header group flex items-center justify-between px-2.5 py-1.5 rounded-lg">
        <button type="button" class="tree-toggle" data-toggle="${nodeId}" aria-label="${expanded ? '收起' : '展开'}课程 ${escHtml(course.name)}" aria-expanded="${expanded}">${expanded ? ICON.chevronDown : ICON.chevronRight}</button>
        ${ICON.book}
        <span class="course-name" data-course-name="${course.id}">${escHtml(course.name)}</span>
        ${renderTreeOverflowMenu('课程操作', [
          { action: 'add-chapter', idAttribute: `data-course-id="${course.id}"`, title: '新建章节', label: '新建章节', icon: ICON.plus },
          { action: 'add-project-course', idAttribute: `data-course-id="${course.id}"`, title: '新建视频', label: '新建视频', icon: ICON.plusCircle },
          { action: 'edit-course', idAttribute: `data-course-id="${course.id}"`, title: '重命名', label: '重命名', icon: ICON.edit },
          { action: 'delete-course', idAttribute: `data-course-id="${course.id}"`, title: '删除课程', label: '删除课程', icon: ICON.trash, danger: true },
        ])}
      </div>
    `;

    // 事件绑定
    node.querySelector('[data-toggle]').addEventListener('click', (e) => {
      e.stopPropagation();
      toggleExpanded(nodeId);
      render();
    });
    const courseHeader = node.querySelector('.course-card-header');
    courseHeader.addEventListener('click', (e) => {
      if (e.target.closest('button, input')) return;
      selectLibraryFilter({ type: 'course', id: course.id });
    });
    const courseName = node.querySelector('.course-name');
    courseName.tabIndex = 0;
    courseName.setAttribute('role', 'button');
    courseName.setAttribute('aria-label', `筛选课程：${course.name}`);
    courseName.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        e.stopPropagation();
        selectLibraryFilter({ type: 'course', id: course.id });
      }
    });
    courseName.addEventListener('dblclick', () => startRenameCourse(course.id));
    node.querySelector('[data-action="add-chapter"]').addEventListener('click', (e) => { e.stopPropagation(); createChapterQuick(course.id); });
    node.querySelector('[data-action="add-project-course"]').addEventListener('click', (e) => { e.stopPropagation(); createProjectInCourse(course.id); });
    node.querySelector('[data-action="edit-course"]').addEventListener('click', (e) => { e.stopPropagation(); startRenameCourse(course.id); });
    node.querySelector('[data-action="delete-course"]').addEventListener('click', (e) => { e.stopPropagation(); deleteCourseConfirm(course); });
    bindTreeOverflow(node);

    // 拖拽
    node.addEventListener('dragstart', (e) => handleDragStart(e, 'course'));
    node.addEventListener('dragend', handleDragEnd);
    node.addEventListener('dragover', (e) => handleNodeDragOver(e, 'course', true));
    node.addEventListener('drop', (e) => handleNodeDrop(e, 'course', true));

    // 子节点容器（章节 + 未归类视频，扁平展示）
    if (expanded) {
      const childrenEl = document.createElement('div');
      childrenEl.className = 'course-card-children stitch-course-children pl-3 space-y-1 mt-0.5';

      (course.chapters || []).forEach(chapter => {
        childrenEl.appendChild(renderChapterNode(chapter));
      });

      // 正式入口只允许课程 → 章节 → 视频。旧数据中的未归档视频仍然
      // 保留并可打开，但明确标出待归档，避免用户误以为它是推荐结构。
      const unchaptered = course.unchaptered_projects || [];
      if (unchaptered.length) {
        const legacyHeading = document.createElement('div');
        legacyHeading.className = 'course-tree-unchaptered-heading';
        legacyHeading.textContent = `待归档视频 · ${unchaptered.length}`;
        childrenEl.appendChild(legacyHeading);
        unchaptered.forEach(p => childrenEl.appendChild(renderProjectLeaf(p)));
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
    node.className = 'chapter-node stitch-chapter-node group space-y-0.5';
    if (isLibraryFilterSelected('chapter', chapter.id)) node.classList.add('is-selected');
    node.dataset.chapterId = chapter.id;
    node.draggable = true;
    node.setAttribute('role', 'treeitem');
    node.setAttribute('aria-expanded', String(expanded));

    const projectCount = chapter.projects ? chapter.projects.length : 0;

    node.innerHTML = `
      <div class="chapter-node-header stitch-chapter-header group flex items-center justify-between px-2 py-1 rounded-md">
        <button type="button" class="tree-toggle" data-toggle="${nodeId}" aria-label="${expanded ? '收起' : '展开'}章节 ${escHtml(chapter.name)}" aria-expanded="${expanded}">${expanded ? ICON.chevronDown : ICON.chevronRight}</button>
        ${ICON.folder}
        <span class="chapter-name" data-chapter-name="${chapter.id}">${escHtml(chapter.name)}</span>
        ${renderTreeOverflowMenu('章节操作', [
          { action: 'add-project-chapter', idAttribute: `data-chapter-id="${chapter.id}"`, title: '新建视频', label: '新建视频', icon: ICON.plusCircle },
          { action: 'edit-chapter', idAttribute: `data-chapter-id="${chapter.id}"`, title: '重命名', label: '重命名', icon: ICON.edit },
          { action: 'delete-chapter', idAttribute: `data-chapter-id="${chapter.id}"`, title: '删除章节', label: '删除章节', icon: ICON.trash, danger: true },
        ])}
      </div>
    `;

    node.querySelector('[data-toggle]').addEventListener('click', (e) => {
      e.stopPropagation();
      toggleExpanded(nodeId);
      render();
    });
    const chapterHeader = node.querySelector('.chapter-node-header');
    chapterHeader.addEventListener('click', (e) => {
      if (e.target.closest('button, input')) return;
      selectLibraryFilter({ type: 'chapter', id: chapter.id });
    });
    const chapterName = node.querySelector('.chapter-name');
    chapterName.tabIndex = 0;
    chapterName.setAttribute('role', 'button');
    chapterName.setAttribute('aria-label', `筛选章节：${chapter.name}`);
    chapterName.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        e.stopPropagation();
        selectLibraryFilter({ type: 'chapter', id: chapter.id });
      }
    });
    chapterName.addEventListener('dblclick', () => startRenameChapter(chapter.id));
    node.querySelector('[data-action="add-project-chapter"]').addEventListener('click', (e) => { e.stopPropagation(); createProjectInChapter(chapter.id); });
    node.querySelector('[data-action="edit-chapter"]').addEventListener('click', (e) => { e.stopPropagation(); startRenameChapter(chapter.id); });
    node.querySelector('[data-action="delete-chapter"]').addEventListener('click', (e) => { e.stopPropagation(); deleteChapterConfirm(chapter); });
    bindTreeOverflow(node);

    node.addEventListener('dragstart', (e) => handleDragStart(e, 'chapter'));
    node.addEventListener('dragend', handleDragEnd);
    node.addEventListener('dragover', (e) => handleNodeDragOver(e, 'chapter', true));
    node.addEventListener('drop', (e) => handleNodeDrop(e, 'chapter', true));

    if (expanded) {
      const childrenEl = document.createElement('div');
      childrenEl.className = 'chapter-node-children stitch-chapter-children pl-4 pr-1 space-y-0.5 border-l border-neutral-200 ml-3 py-0.5';
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

  // 视频叶子行：设计稿中仅展示播放图标与名称，操作统一在右侧卡片菜单
  function renderProjectLeaf(project) {
    const leaf = document.createElement('div');
    leaf.className = 'project-leaf stitch-project-leaf group flex items-center justify-between px-2 py-1 rounded';
    leaf.dataset.projectId = project.id;
    leaf.draggable = true;
    leaf.tabIndex = 0;
    leaf.setAttribute('role', 'treeitem');
    leaf.setAttribute('aria-label', `打开视频项目：${project.name}`);

    leaf.innerHTML = `
      <span class="project-leaf-play" aria-hidden="true">${ICON.playTiny}</span>
      <span class="project-name" data-project-id="${project.id}">${escHtml(project.name)}</span>
    `;

    leaf.addEventListener('click', (e) => {
      if (!e.target.closest('button')) enterWorkspace(project.id);
    });
    leaf.addEventListener('dblclick', () => enterWorkspace(project.id));
    leaf.addEventListener('keydown', (e) => {
      if (e.target !== leaf) return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        enterWorkspace(project.id);
      }
    });
    leaf.addEventListener('dragstart', (e) => handleDragStart(e, 'project'));
    leaf.addEventListener('dragend', handleDragEnd);
    leaf.addEventListener('dragover', (e) => handleNodeDragOver(e, 'project', false));
    leaf.addEventListener('drop', (e) => handleNodeDrop(e, 'project', false));

    return leaf;
  }

  // 独立项目行：与设计稿一致，仅播放图标 + 名称，操作在右侧卡片菜单
  function renderStandaloneProjectCard(project) {
    const node = document.createElement('div');
    node.className = 'course-card-item standalone-project stitch-standalone-project group';
    node.dataset.projectId = project.id;
    node.dataset.dragType = 'project';
    node.draggable = true;
    node.tabIndex = 0;
    node.setAttribute('role', 'treeitem');
    node.setAttribute('aria-label', `打开独立视频项目：${project.name}`);

    node.innerHTML = `
      <div class="course-card-header stitch-standalone-header group flex items-center justify-between px-2.5 py-1.5 rounded-lg">
        <span class="project-leaf-play" aria-hidden="true">${ICON.playTiny}</span>
        <span class="course-name" data-project-id="${project.id}">${escHtml(project.name)}</span>
      </div>
    `;

    // 点击头部进入工作台
    const standaloneHeader = node.querySelector('.course-card-header');
    standaloneHeader.addEventListener('click', (e) => {
      if (e.target.closest('.icon-action-btn')) return;
      enterWorkspace(project.id);
    });
    standaloneHeader.addEventListener('keydown', (e) => {
      if (e.target !== standaloneHeader && e.target !== node) return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        enterWorkspace(project.id);
      }
    });
    node.addEventListener('keydown', (e) => {
      if (e.target !== node) return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        enterWorkspace(project.id);
      }
    });

    node.addEventListener('dragstart', (e) => handleDragStart(e, 'project'));
    node.addEventListener('dragend', handleDragEnd);
    node.addEventListener('dragover', (e) => handleNodeDragOver(e, 'project', false));
    node.addEventListener('drop', (e) => handleNodeDrop(e, 'project', false));

    return node;
  }

  function formatLatestOutputTime(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    }).format(date).replace(/\//g, '-');
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
    const createButton = document.getElementById('btn-create-project');
    if (!createButton) { showToast('新建弹窗未就绪'); return; }
    // 触发统一的新建视频入口，确保创作配置会一并加载。
    window.__pendingProjectParent = pendingProjectParent;
    createButton.click();
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

window.CourseTree = CourseTree;

// 桥接：把原有的 loadProjects() 重定向到 CourseTree，
// 这样 event_bindings.js / projects.js / workspace_navigation.js
// 里的所有 loadProjects() 调用都会自动渲染课程树，无需改动现有文件。
window.loadProjects = function loadProjectsViaCourseTree() {
  try { CourseTree.init(); } catch (e) { /* ignore */ }
  return CourseTree.load();
};

// Project creation is implemented in projects.js. The course tree only sets
// window.__pendingProjectParent before opening its full form, so standalone
// and chapter-contained projects use identical configuration behavior.

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

