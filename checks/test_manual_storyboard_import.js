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
let downloaded;
const scope = {
  state,
  Blob,
  URL: { createObjectURL(blob) { downloaded = { blob }; return 'blob:test'; }, revokeObjectURL() {} },
  document: { body: { appendChild() {}, removeChild() {} }, createElement() {
    return { click() { downloaded.filename = this.download; } };
  }, getElementById: id => {
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
  assert.equal(Object.hasOwn(template[0], 'title_speech_segment'), false);
  assert.equal(template[0].segments[0].role, 'title');
  assert.equal(template[0].segments.map(seg => seg.speech_segment).join(''), template[0].narration);
  scope.downloadStep2BatchTemplate();
  const guide = await downloaded.blob.text();
  assert.equal(downloaded.filename, '手动分镜模板.txt');
  assert.match(guide, /narration 是本页唯一的完整演讲稿/);
  assert.match(guide, /最终只输出一个标准 JSON 数组/);
  assert.match(guide, /不编造数据/);
  assert.ok(guide.endsWith(vm.runInContext('STEP2_BATCH_TEMPLATE', scope)));
  assert.match(read(guide), /不是 JSON 数组/);
  assert.equal(pending(), null);
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

  // Append standard pages without overwriting existing pages or reusing IDs.
  read([template[0]]);
  await scope.submitStep2BatchImport('append');
  assert.deepEqual(savedSlides.slice(0, 2), templateSlides);
  assert.equal(savedSlides.length, 3);
  assert.equal(new Set(savedSlides.map(slide => slide.slide_id)).size, 3);

  // Old import shapes and aliases are explicitly rejected.
  for (const legacy of [
    [{ main_title: '旧简式', narration: '旧演讲稿。' }],
    [{ main_title: '旧文字格式', segments: [{ screen_text: '文字', speech_segment: '片段。' }] }],
    [{ main_title: '旧标题字段', title_speech_segment: '开场。', narration: '开场。正文。',
      segments: [{ visual_type: 'picture', visual_description: '图形', speech_segment: '正文。' }] }],
  ]) {
    assert.match(read(legacy), /标准格式|标题片段/);
    assert.equal(pending(), null);
    assert.equal(nodes.get('btn-step2-batch-import-overwrite').disabled, true);
  }
  for (const type of ['illustration', 'image', 'diagram', 'chart', 'visual', 'graphic', 'text_and_illustration', '文字', 'unknown']) {
    const invalidType = JSON.parse(JSON.stringify(template));
    invalidType[0].segments[2].visual_type = type;
    assert.match(read(invalidType), /字段不符合标准格式/);
    assert.equal(pending(), null);
  }
  const typeAlias = JSON.parse(JSON.stringify(template));
  typeAlias[0].segments[2].type = 'picture';
  delete typeAlias[0].segments[2].visual_type;
  assert.match(read(typeAlias), /字段不符合标准格式/);
  const missingNarration = JSON.parse(JSON.stringify(template));
  delete missingNarration[0].narration;
  assert.match(read(missingNarration), /整页 narration/);
  assert.equal(pending(), null);
  const pictureTextFallback = JSON.parse(JSON.stringify(template));
  pictureTextFallback[0].segments[2].screen_text = pictureTextFallback[0].segments[2].visual_description;
  delete pictureTextFallback[0].segments[2].visual_description;
  assert.match(read(pictureTextFallback), /字段不符合标准格式/);
  assert.equal(pending(), null);

  const mismatch = JSON.parse(JSON.stringify(template));
  mismatch[0].narration += '不能丢失的额外演讲稿。';
  assert.match(read(mismatch), /narration 必须/);
  assert.equal(pending(), null);
  const duplicate = JSON.parse(JSON.stringify(template));
  duplicate[0].segments[2].speech_segment = duplicate[0].segments[1].speech_segment;
  duplicate[0].narration = duplicate[0].segments.map(seg => seg.speech_segment).join('');
  assert.match(read(duplicate), /重复演讲片段/);
  assert.equal(pending(), null);

  const incomplete = JSON.parse(JSON.stringify(template));
  delete incomplete[0].segments[2].visual_description;
  assert.match(read(incomplete), /visual_description/);
  assert.equal(pending(), null);
  const extraFields = JSON.parse(JSON.stringify(template));
  extraFields[0].instructions = '不要导入的说明';
  assert.match(read(extraFields), /标准格式仅使用/);
  assert.equal(pending(), null);
  const noTitle = JSON.parse(JSON.stringify(template));
  noTitle[0].segments.shift();
  assert.match(read(noTitle), /标题片段/);
  assert.equal(pending(), null);
  const secondTitle = JSON.parse(JSON.stringify(template));
  secondTitle[0].segments[1] = { role: 'title', speech_segment: '第二个标题片段。' };
  assert.match(read(secondTitle), /只能在首位/);
  const emptyTitle = JSON.parse(JSON.stringify(template));
  emptyTitle[0].segments[0].speech_segment = '';
  assert.match(read(emptyTitle), /填写 speech_segment/);
  const titleOnly = JSON.parse(JSON.stringify(template));
  titleOnly[0].segments = [titleOnly[0].segments[0]];
  assert.match(read(titleOnly), /至少一个 content_body/);
  const missingType = JSON.parse(JSON.stringify(template));
  delete missingType[0].segments[1].visual_type;
  assert.match(read(missingType), /字段不符合标准格式/);
  const fenced = '```json\n' + JSON.stringify(template) + '\n```';
  assert.match(read(fenced), /不是 JSON 数组/);
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
    slides: templateSlides,
  };
  if (process.argv.includes('--contract')) process.stdout.write(JSON.stringify(contract));
  else console.log('Manual storyboard template/import regression checks passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
