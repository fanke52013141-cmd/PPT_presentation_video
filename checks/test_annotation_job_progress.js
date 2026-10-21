// Real workspace polling with controlled timers and transport failures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
const timers = new Map();
let sequence = 0;
const box = {
  console, Date, Math, Map, Set, Promise,
  window: {}, state: {}, escHtml: String, showToast() {},
  setTimeout(fn) { timers.set(++sequence, fn); return sequence; },
  clearTimeout(id) { timers.delete(id); },
  setUiTaskState(node, status, text) { node.dataset.state = status; node.textContent = text; },
  document: {
    querySelectorAll: () => [],
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, {
        style: {}, dataset: {}, classList: {toggle() {}},
        setAttribute() {}, removeAttribute() {}, querySelectorAll: () => [],
      });
      return nodes.get(id);
    },
  },
  API: {},
};
vm.createContext(box);
vm.runInContext(fs.readFileSync('static/annotations_core.js', 'utf8'), box);
vm.runInContext(fs.readFileSync('static/annotations_workspace.js', 'utf8'), box);
const run = code => vm.runInContext(code, box);
const ws = run('ANNOTATIONS_WS');
async function tick() {
  const [id, fn] = timers.entries().next().value;
  timers.delete(id);
  await fn();
}

(async () => {
  ws.projectId = 'p';
  ws.page = {slide_id: 's', items: []};
  ws.activeJob = {projectId: 'p', slideId: 's', jobId: 'job', operation: 'plan', startedAt: Date.now() - 6000};
  box.API.get = async () => { throw new Error('offline'); };
  run('pollAnnotationJob("job", "plan", "p", "s")');
  await tick();
  assert.equal(ws.activeJob.jobId, 'job', 'network loss must retain ownership and prevent duplicate submissions');
  assert.match(nodes.get('annotation-job-status').textContent, /重新获取/);
  assert.equal(timers.size, 1);
  box.API.get = async () => ({status: 'running', progress: 5});
  await tick();
  assert.match(nodes.get('annotation-job-status').textContent, /已用时/);
  assert.ok(!nodes.get('annotation-job-status').textContent.includes('%'));
  const posts = [];
  box.API.post = async url => { posts.push(url); return {cancelled: true}; };
  await run('cancelCurrentAnnotationJob()');
  await run('cancelCurrentAnnotationJob()');
  assert.equal(posts.length, 1);
  assert.equal(posts[0], '/api/projects/p/annotations/jobs/job/cancel');
  assert.ok(ws.activeJob, 'a cancel request is not a terminal server state');
  box.API.get = async () => ({status: 'cancelled'});
  await tick();
  assert.equal(ws.activeJob, null);
  assert.equal(nodes.get('annotation-btn-cancel-job').hidden, true);
  assert.match(nodes.get('annotation-job-status').textContent, /已取消/);
  assert.equal(nodes.get('annotation-btn-ai-plan').disabled, false);

  let release;
  ws.activeJob = {jobId: 'old'};
  box.API.get = () => new Promise(resolve => { release = resolve; });
  run('pollAnnotationJob("old", "plan", "p", "s")');
  const pending = tick();
  run('stopAnnotationJobPolling()'); // Leave and reopen the same project.
  ws.activeJob = {jobId: 'new'};
  const before = nodes.get('annotation-job-status').textContent;
  release({status: 'failed', error: 'old failure'});
  await pending;
  assert.equal(ws.activeJob.jobId, 'new');
  assert.equal(nodes.get('annotation-job-status').textContent, before);
  assert.equal(timers.size, 0);
  console.log('annotation job progress checks passed');
})().catch(error => { console.error(error); process.exit(1); });
