const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'static/storyboard.js'), 'utf8');
const foundation = fs.readFileSync(path.join(root, 'static/ui_foundation.js'), 'utf8');
const nodes = new Map();
const state = { currentProject: { id: 'test' }, slides: [], activeSlideIndex: 0 };
let savedSlides;
const scope = {
  state,
  document: { getElementById: id => {
    if (!nodes.has(id)) nodes.set(id, { style: {}, value: '', innerHTML: '', disabled: true });
    return nodes.get(id);
  } },
  FileReader: class {
    readAsText(file) { this.result = file.text; this.onload(); }
  },
  escHtml: value => String(value).replace(/[&<>"']/g, char => `&#${char.charCodeAt(0)};`),
  saveCurrentSlideInputToState() {},
  async saveStep2Contract(options) {
    assert.equal(options.skipCurrentSlideSync, true);
    savedSlides = JSON.parse(JSON.stringify(state.slides));
    return { success: true, validation: { valid: true } };
  },
  async loadStep2Data() {},
  showToast() {},
};
vm.createContext(scope);
vm.runInContext(foundation.slice(foundation.indexOf('function narrationDedupeKey('), foundation.indexOf('function autoResizeTextarea(')), scope);
vm.runInContext(source.slice(source.indexOf('const STEP2_BATCH_TEMPLATE'), source.indexOf('function closeStep2GenerationModal(')), scope);
const read = data => {
  scope.handleStep2BatchImportFile({ target: { files: [{ text: typeof data === 'string' ? data : JSON.stringify(data) }] } });
  return nodes.get('step2-batch-import-preview').innerHTML;
};
const pending = () => vm.runInContext('step2BatchImportPending', scope);

async function main() {
  const template = JSON.parse(vm.runInContext('STEP2_BATCH_TEMPLATE', scope));
  read('\uFEFF' + JSON.stringify(template));
  assert.equal(pending().length, 2);
  await scope.submitStep2BatchImport('overwrite');
  const templateSlides = savedSlides;
  for (const [index, slide] of templateSlides.entries()) {
    assert.equal(slide.visual_groups.length, 3);
    assert.equal(slide.narration_beats.length, 3);
    assert.equal(slide.narration_beats[0].group_id, slide.visual_groups[0].id);
    assert.equal(slide.narration_beats.map(beat => beat.spoken_text).join(''), template[index].narration);
    for (const beat of slide.narration_beats) {
      const group = slide.visual_groups.find(group => group.id === beat.group_id);
      assert.equal(beat.content_unit_id, group.content_unit_id);
    }
  }
  assert.equal(templateSlides[0].visual_groups[1].visual_type, 'text');
  assert.equal(templateSlides[0].visual_groups[2].visual_type, 'picture');
  assert.equal(templateSlides[0].visual_groups[2].display_text, '');
  assert.match(templateSlides[0].visual_groups[2].visual_anchor, /流程图/);

  // Legacy narration-only pages must stay unbound, so backend normalization retains them.
  read([{ main_title: '简式标题', narration: '完整演讲稿保留。' }]);
  await scope.submitStep2BatchImport('append');
  assert.deepEqual(savedSlides.slice(0, 2), templateSlides);
  const simpleSlide = savedSlides[2];
  assert.deepEqual(simpleSlide.visual_groups, []);
  assert.equal(simpleSlide.narration_beats[0].spoken_text, '完整演讲稿保留。');
  assert.equal(new Set(savedSlides.map(slide => slide.slide_id)).size, 3);

  read([{ main_title: '旧文字模板', segments: [{ screen_text: '旧文字', speech_segment: '旧的片段。' }] }]);
  await scope.submitStep2BatchImport('overwrite');
  assert.equal(savedSlides[0].visual_groups[1].visual_type, 'text');
  assert.equal(savedSlides[0].narration_beats[0].spoken_text, '旧的片段。');

  for (const type of ['picture', 'illustration', 'image', 'diagram', 'chart', 'visual', 'graphic', 'text_and_illustration']) {
    read([{ main_title: '类型兼容', segments: [{ type, screen_text: '图形描述', speech_segment: '图形说明。' }] }]);
    assert.equal(pending()[0].segments[0].visual_type, 'picture');
  }
  assert.match(read([{ main_title: '错误类型', segments: [{ type: 'unknown', screen_text: '内容', speech_segment: '说明。' }] }]), /visual_type 不支持/);
  assert.equal(pending(), null);
  assert.equal(nodes.get('btn-step2-batch-import-overwrite').disabled, true);

  const mismatch = JSON.parse(JSON.stringify(template));
  mismatch[0].narration += '不能丢失的额外演讲稿。';
  assert.match(read(mismatch), /narration 必须/);
  assert.equal(pending(), null);
  assert.match(read([{ main_title: '重复', segments: [
    { screen_text: '元素一', speech_segment: '重复说明。' },
    { screen_text: '元素二', speech_segment: '重复说明！' },
  ] }]), /重复演讲片段/);
  assert.equal(pending(), null);

  const incomplete = JSON.parse(JSON.stringify(template));
  delete incomplete[0].segments[1].visual_description;
  assert.match(read(incomplete), /visual_description/);
  assert.equal(pending(), null);
  read(template);
  scope.openStep2BatchImportModal();
  assert.equal(pending(), null);
  const contract = {
    version: 'visual_contract_v1',
    presentation_policy: {
      subtitle_policy: 'no_slides_have_subtitle',
      visual_narration_mapping: 'one_visual_element_to_one_narration_beat_v1',
    },
    slides: [...templateSlides, simpleSlide],
  };
  if (process.argv.includes('--contract')) process.stdout.write(JSON.stringify(contract));
  else console.log('Manual storyboard template/import regression checks passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
