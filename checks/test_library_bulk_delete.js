const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/courses.js'), 'utf8');
const begin = source.indexOf('  function collectVideoRecords(');
const end = source.indexOf('  function projectProgress(', begin);

function fixture() {
  const projects = [{ id: 'one', name: '测试一' }, { id: 'two', name: '测试二' }];
  const scope = {
    bulk: { active: true, selected: new Set(['one', 'two']), account: 'default', busy: false, message: '', failures: [], session: 0 },
    treeData: { standalone_projects: projects },
    libraryFilter: { type: 'standalone', id: null },
    librarySearchQuery: '',
    account: 'default',
    requests: [],
    confirmed: true,
    document: { getElementById: () => ({ classList: { add() {}, remove() {} } }) },
    render() {},
    async load() {},
  };
  scope.currentLibraryAccount = () => scope.account;
  scope.showCustomConfirm = async (...args) => { scope.confirmation = args; return scope.confirmed; };
  scope.API = { fetch: async (url, options) => { scope.requests.push({ url, options }); } };
  vm.createContext(scope);
  vm.runInContext(source.slice(begin, end), scope);
  scope.updateBulkSelectionUI = () => {};
  return scope;
}

(async () => {
  const filters = fixture();
  const records = filters.collectVideoRecords([{ id: 'course', unchaptered_projects: [{ id: 'course-video', name: '测试课程' }] }], filters.treeData.standalone_projects);
  assert.deepEqual(Array.from(filters.filterVideoRecords(records), record => record.project.id), ['one', 'two'], 'batch mode must exclude course projects');
  filters.librarySearchQuery = '测试二';
  assert.deepEqual(Array.from(filters.bulkVisibleProjects(), project => project.id), ['two'], 'search limits select-all and deletion targets');
  await filters.deleteBulkProjects();
  assert.equal(filters.requests.length, 1);
  assert.equal(filters.requests[0].url, '/api/projects/two');

  const cancelled = fixture();
  cancelled.confirmed = false;
  await cancelled.deleteBulkProjects();
  assert.equal(cancelled.requests.length, 0, 'cancel must never delete');
  assert.equal(cancelled.bulk.busy, false);
  assert.equal(cancelled.bulk.selected.size, 2);

  const partial = fixture();
  partial.API.fetch = async (url, options) => {
    partial.requests.push({ url, options });
    if (url.endsWith('/two')) throw new Error('项目仍有正在进行的渲染任务');
  };
  await partial.deleteBulkProjects();
  assert.deepEqual([...partial.bulk.selected], ['two'], 'failed projects stay selected for retry');
  assert.deepEqual(partial.treeData.standalone_projects.map(project => project.id), ['two']);
  assert.equal(partial.bulk.message, '已删除 1 项，1 项未删除');
  assert.match(partial.bulk.failures[0].reason, /渲染任务/);
  assert.equal(partial.confirmation[4].danger, true);
  assert.equal(partial.bulk.busy, false);

  const switched = fixture();
  switched.API.fetch = async url => { switched.requests.push(url); switched.account = 'another'; switched.resetBulkSelection(); };
  await switched.deleteBulkProjects();
  assert.equal(switched.requests.length, 1, 'account switch must stop remaining deletes');
  assert.equal(switched.bulk.active, false);
  assert.equal(switched.bulk.selected.size, 0);

  const switchedBeforeConfirm = fixture();
  switchedBeforeConfirm.showCustomConfirm = async () => { switchedBeforeConfirm.account = 'another'; return true; };
  await switchedBeforeConfirm.deleteBulkProjects();
  assert.equal(switchedBeforeConfirm.requests.length, 0, 'confirmation cannot apply to a different account');

  const duplicate = fixture();
  let resolveConfirm;
  duplicate.showCustomConfirm = () => new Promise(resolve => { resolveConfirm = resolve; });
  const first = duplicate.deleteBulkProjects();
  await duplicate.deleteBulkProjects();
  resolveConfirm(true);
  await first;
  assert.equal(duplicate.requests.length, 2, 'repeated submission cannot duplicate deletion requests');
  assert.equal(duplicate.bulk.message, '已删除 2 项');
  console.log('library bulk deletion checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
