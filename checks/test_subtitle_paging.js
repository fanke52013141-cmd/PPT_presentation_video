// test_subtitle_paging.js
// 守护方案 B 字幕分页与逐字高亮算法规范。
// 算法在 scripts/remotion/src/Video.tsx 中实现，这里用纯 JS 复刻同一规范，
// 任何对算法的修改都应同步更新本测试，确保 Video.tsx 行为可预测。

const assert = require('node:assert/strict');

// ===== 算法规范复刻（与 Video.tsx 保持一致） =====

const SUBTITLE_GAP_HOLD_SEC = 0.35;
const hasReadableSubtitleText = (text) => /[0-9A-Za-z\u3400-\u9fff]/.test(text || '');

function splitSentenceToTokens(text, startMs, endMs) {
  const durationMs = Math.max(0, endMs - startMs);
  const pieces = text.match(/[\u4e00-\u9fff]|[A-Za-z0-9]+|\s+|[^\s\u4e00-\u9fffA-Za-z0-9]/g) || [text];
  const weights = pieces.map((piece) => {
    if (/\s/.test(piece)) return 0;
    if (/[\u4e00-\u9fff]/.test(piece)) return 1;
    if (/[A-Za-z0-9]/.test(piece)) return piece.length;
    return 0.3;
  });
  const total = weights.reduce((a, b) => a + b, 0);
  if (total <= 0) {
    return pieces.map((piece) => ({text: piece, fromMs: startMs, toMs: endMs}));
  }
  let cursor = startMs;
  return pieces.map((piece, i) => {
    const dur = (durationMs * weights[i]) / total;
    const token = {text: piece, fromMs: cursor, toMs: cursor + dur};
    cursor += dur;
    return token;
  });
}

const subtitleTextUnits = (text) => Array.from(text).reduce((total, character) => {
  if (/\s/.test(character)) return total;
  if (/[A-Za-z0-9]/.test(character)) return total + 0.55;
  return total + 1;
}, 0);

function splitSegmentForCapacity(segment, maxTextUnits) {
  if (subtitleTextUnits(segment.text) <= maxTextUnits) return [segment];
  const tokens = splitSentenceToTokens(segment.text, segment.start * 1000, segment.end * 1000);
  const chunks = [];
  let chunkTokens = [];
  let chunkUnits = 0;
  const flush = () => {
    if (chunkTokens.length === 0) return;
    chunks.push({
      id: `${segment.id}_page_${chunks.length + 1}`,
      start: chunkTokens[0].fromMs / 1000,
      end: chunkTokens[chunkTokens.length - 1].toMs / 1000,
      text: chunkTokens.map((token) => token.text).join(''),
    });
    chunkTokens = [];
    chunkUnits = 0;
  };
  tokens.forEach((token) => {
    const units = subtitleTextUnits(token.text);
    if (chunkTokens.length > 0 && chunkUnits + units > maxTextUnits) flush();
    chunkTokens.push(token);
    chunkUnits += units;
  });
  flush();
  return chunks;
}

function buildCaptionPages(segments, pagingWindowMs, tokenize, maxTextUnits = 72, maxPageDurationMs = 6500) {
  const readable = segments
    .filter((s) => hasReadableSubtitleText(s.text || ''))
    .flatMap((segment) => splitSegmentForCapacity(segment, maxTextUnits));
  if (readable.length === 0) return [];
  const pages = [];
  let currentTokens = [];
  let currentStartMs = 0;
  let currentEndMs = 0;
  let currentText = '';
  const flush = () => {
    if (currentTokens.length === 0) return;
    pages.push({
      text: currentText,
      startMs: currentStartMs,
      durationMs: currentEndMs - currentStartMs,
      tokens: currentTokens,
    });
    currentTokens = [];
    currentText = '';
    currentEndMs = 0;
  };
  readable.forEach((segment, index) => {
    const segStartMs = segment.start * 1000;
    const segEndMs = segment.end * 1000;
    const separator = /[A-Za-z0-9]$/.test(currentText) && /^[A-Za-z0-9]/.test(segment.text) ? ' ' : '';
    const combinedText = `${currentText}${separator}${segment.text}`;
    const shouldStartNewPage = currentTokens.length > 0 && (
      segStartMs - currentEndMs > pagingWindowMs
      || subtitleTextUnits(combinedText) > maxTextUnits
      || segEndMs - currentStartMs > maxPageDurationMs
    );
    if (shouldStartNewPage) flush();
    if (currentTokens.length === 0) currentStartMs = segStartMs;
    const currentSeparator = /[A-Za-z0-9]$/.test(currentText) && /^[A-Za-z0-9]/.test(segment.text) ? ' ' : '';
    if (currentSeparator) currentTokens.push({text: currentSeparator, fromMs: segStartMs, toMs: segStartMs});
    if (tokenize) {
      currentTokens.push(...splitSentenceToTokens(segment.text, segStartMs, segEndMs));
    } else {
      currentTokens.push({text: segment.text, fromMs: segStartMs, toMs: segEndMs});
    }
    currentText += `${currentSeparator}${segment.text}`;
    currentEndMs = Math.max(currentEndMs, segEndMs);
    if (index === readable.length - 1) flush();
  });
  return pages;
}

function pageAtTime(pages, audioSeconds) {
  if (audioSeconds < 0 || pages.length === 0) return undefined;
  const ms = audioSeconds * 1000;
  let previous;
  for (const page of pages) {
    if (ms >= page.startMs && ms < page.startMs + page.durationMs) return page;
    if (page.startMs + page.durationMs <= ms) {
      previous = page;
      continue;
    }
    if (page.startMs > ms) {
      return previous && ms - (previous.startMs + previous.durationMs) <= SUBTITLE_GAP_HOLD_SEC * 1000
        ? previous
        : undefined;
    }
  }
  return previous && ms - (previous.startMs + previous.durationMs) <= SUBTITLE_GAP_HOLD_SEC * 1000
    ? previous
    : undefined;
}

function highlightedTokenCount(page, audioSeconds) {
  const ms = audioSeconds * 1000;
  let count = 0;
  for (const token of page.tokens) {
    if (ms >= token.toMs - 1) {
      count++;
    } else if (ms >= token.fromMs) {
      count++;
      break;
    } else {
      break;
    }
  }
  return count;
}

// ===== 测试用例 =====

// 用例 1：单句中文按字切分
{
  const tokens = splitSentenceToTokens('你好世界', 0, 4000);
  assert.equal(tokens.length, 4, '4 个汉字 → 4 个 token');
  assert.deepEqual(tokens.map((t) => t.text), ['你', '好', '世', '界']);
  // 每字 1000ms
  tokens.forEach((t, i) => {
    assert.ok(Math.abs(t.fromMs - i * 1000) < 1, `token ${i} fromMs`);
    assert.ok(Math.abs(t.toMs - (i + 1) * 1000) < 1, `token ${i} toMs`);
  });
}

// 用例 2：中英混合
{
  const tokens = splitSentenceToTokens('Token 是什么', 0, 4000);
  // Token(5) + 空白(0) + 是(1) + 什(1) + 么(1) = 8 权重，4000ms
  assert.deepEqual(tokens.map((t) => t.text), ['Token', ' ', '是', '什', '么']);
  // Token 占 5/8 * 4000 = 2500ms
  assert.ok(Math.abs(tokens[0].toMs - tokens[0].fromMs - 2500) < 1, 'Token 时长');
  // 空白权重 0 → 0 时长
  assert.equal(tokens[1].toMs - tokens[1].fromMs, 0, '空白时长为 0');
}

// 用例 3：标点单独成 token
{
  const tokens = splitSentenceToTokens('你好。', 0, 2000);
  assert.deepEqual(tokens.map((t) => t.text), ['你', '好', '。']);
  // 标点权重 0.3，总权重 2.3，标点时长 = 2000 * 0.3 / 2.3 ≈ 260ms
  const punctDur = tokens[2].toMs - tokens[2].fromMs;
  assert.ok(punctDur > 200 && punctDur < 300, `标点时长 ${punctDur} 应在 200-300ms 之间`);
}

// 用例 4：buildCaptionPages 同句一定在同一页
{
  const segments = [
    {id: 's1', start: 0, end: 2, text: '你好世界'},
    {id: 's2', start: 2.1, end: 4, text: '今天天气不错'},
  ];
  const pages = buildCaptionPages(segments, 1300, true);
  // 两句 gap 100ms < 1300ms，应合并一页
  assert.equal(pages.length, 1, '相邻句子 gap 小于窗口应合并');
  assert.equal(pages[0].text, '你好世界今天天气不错');
  assert.equal(pages[0].startMs, 0);
  assert.equal(pages[0].durationMs, 4000);
  // 10 个汉字 → 10 个 token
  assert.equal(pages[0].tokens.length, 10);
}

// 用例 5：gap 超过窗口时分页
{
  const segments = [
    {id: 's1', start: 0, end: 2, text: '你好'},
    {id: 's2', start: 5, end: 7, text: '世界'},  // gap 3 秒 > 1300ms
  ];
  const pages = buildCaptionPages(segments, 1300, true);
  assert.equal(pages.length, 2, 'gap 超过窗口应分页');
  assert.equal(pages[0].text, '你好');
  assert.equal(pages[1].text, '世界');
  assert.equal(pages[1].startMs, 5000);
}

// 用例 6：纯标点 segment 被过滤
{
  const segments = [
    {id: 's1', start: 0, end: 2, text: '你好'},
    {id: 's2', start: 2, end: 2.2, text: '。'},  // 纯标点
    {id: 's3', start: 2.2, end: 4, text: '世界'},
  ];
  const pages = buildCaptionPages(segments, 1300, true);
  assert.equal(pages.length, 1, '纯标点 segment 应被过滤');
  assert.equal(pages[0].text, '你好世界');
}

// 用例 7：pageAtTime 找当前页 + gap hold
{
  const segments = [
    {id: 's1', start: 0, end: 2, text: '你好'},
    {id: 's2', start: 5, end: 7, text: '世界'},
  ];
  const pages = buildCaptionPages(segments, 1300, true);
  // 在第一页内
  assert.ok(pageAtTime(pages, 1.0));
  // 在页间 gap 内 350ms 内：仍显示上一页
  assert.ok(pageAtTime(pages, 2.3), 'gap ≤ 350ms 应保留上一页');
  // gap > 350ms 后无显示
  assert.equal(pageAtTime(pages, 2.5), undefined, 'gap > 350ms 应无显示');
  // 在第二页内
  assert.ok(pageAtTime(pages, 6.0));
}

// 用例 8：highlightedTokenCount 跟随时间推进
{
  const segments = [{id: 's1', start: 0, end: 4, text: '你好世界'}];
  const pages = buildCaptionPages(segments, 1300, true);
  const page = pages[0];
  // t=0：第一个 token 正在朗读（fromMs=0），算高亮 1 个
  assert.equal(highlightedTokenCount(page, 0), 1, 't=0 高亮 1');
  // t=1：第一字读完，进入第二字
  assert.equal(highlightedTokenCount(page, 1.0), 2, 't=1s 高亮 2');
  // t=4：全部读完
  assert.equal(highlightedTokenCount(page, 4.0), 4, 't=4s 高亮 4');
}

// 用例 9：tokenize=false 时整句作为一个 token
{
  const segments = [{id: 's1', start: 0, end: 4, text: '你好世界'}];
  const pages = buildCaptionPages(segments, 1300, false);
  assert.equal(pages.length, 1);
  assert.equal(pages[0].tokens.length, 1, 'tokenize=false 时一句一 token');
  assert.equal(pages[0].tokens[0].text, '你好世界');
}

// 用例 10：空 segments 返回空 pages
{
  assert.deepEqual(buildCaptionPages([], 1300, true), []);
  assert.deepEqual(buildCaptionPages([{id: 's', start: 0, end: 1, text: ''}], 1300, true), []);
}

// 用例 11：连续长旁白即使没有句间空隙，也必须按容量分页且不得丢字
{
  const text = '这是一个用于验证长字幕分页完整性的连续句子，它没有足够大的时间间隔，但每一个字符都必须在某一页中出现。';
  const pages = buildCaptionPages([{id: 'long', start: 0, end: 12, text}], 1300, true, 18);
  assert.ok(pages.length > 1, '超出页面容量的单句必须拆页');
  assert.equal(pages.map((page) => page.text).join(''), text, '拆页不得丢失或重复字符');
  assert.ok(pages.every((page) => subtitleTextUnits(page.text) <= 18), '每页不得超过容量');
}

console.log('subtitle paging algorithm checks passed');
