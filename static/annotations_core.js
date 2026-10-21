// 勾画标注模块的纯逻辑核心:坐标/文本索引换算、消歧、撤销栈、操作构造。
// UMD 形式(同 flow.js):浏览器挂 window.AnnotationsCore,Node 侧可 require,
// 供 checks/test_annotation_workspace.js 直接单测;不依赖 DOM。

(function attachAnnotationsCore(root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  root.AnnotationsCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function createAnnotationsCore() {
  // ------------------------------------------------------------ 文本索引

  // 服务端字符范围统一为 Unicode 码点;浏览器 selection 是 UTF-16 码元索引,
  // 必须显式转换(组合字符/emoji 会造成两者错位)。
  function utf16LengthToCodepointCount(text, utf16Length) {
    let codepoints = 0;
    let utf16Seen = 0;
    const bounded = Math.max(0, Math.min(Math.floor(utf16Length), text.length));
    while (utf16Seen < bounded) {
      const codeUnit = text.charCodeAt(utf16Seen);
      // 丢弃后半代理:它是前一个码点的一部分,不再计数
      if (codeUnit >= 0xdc00 && codeUnit <= 0xdfff) {
        utf16Seen += 1;
        continue;
      }
      codepoints += 1;
      utf16Seen += 1;
    }
    return codepoints;
  }

  function utf16IndexToCodepointIndex(text, utf16Index) {
    let bounded = Math.max(0, Math.min(Math.floor(Number(utf16Index) || 0), text.length));
    // 边界落在码点中间(低代理位)时回退到该码点起始,避免多数一个码点
    while (bounded > 0) {
      const unit = text.charCodeAt(bounded);
      if (unit >= 0xdc00 && unit <= 0xdfff) {
        bounded -= 1;
      } else {
        break;
      }
    }
    return utf16LengthToCodepointCount(text, bounded);
  }

  function codepointIndexToUtf16Index(text, codepointIndex) {
    let codepoints = 0;
    let utf16Index = 0;
    while (utf16Index < text.length && codepoints < codepointIndex) {
      const codeUnit = text.charCodeAt(utf16Index);
      utf16Index += 1;
      if (!(codeUnit >= 0xdc00 && codeUnit <= 0xdfff)) {
        codepoints += 1;
      }
    }
    // 码点计数停在高位代理之后时补跳其低代理,返回下一码点的真实起始
    while (utf16Index < text.length) {
      const unit = text.charCodeAt(utf16Index);
      if (unit >= 0xdc00 && unit <= 0xdfff) {
        utf16Index += 1;
      } else {
        break;
      }
    }
    return utf16Index;
  }

  function codepointSlice(text, start, end) {
    const utf16Start = codepointIndexToUtf16Index(text, Math.max(0, start));
    const utf16End = codepointIndexToUtf16Index(text, Math.max(0, Math.max(start, end)));
    return text.slice(utf16Start, utf16End);
  }

  // 出现次序消歧:返回 quote 在全文中的第几次出现(1 起);找不到返回 0。
  // 仅作辅助展示,不代替服务端码点范围校验。
  function occurrenceIndexOf(text, quote, rangeStart) {
    if (!quote) return 0;
    let occurrence = 0;
    let from = 0;
    for (;;) {
      const found = text.indexOf(quote, from);
      if (found < 0) return 0;
      occurrence += 1;
      const codepointStart = utf16IndexToCodepointIndex(text, found);
      if (codepointStart === rangeStart) return occurrence;
      from = found + quote.length;
    }
  }

  // ------------------------------------------------------------ 几何

  // 画布坐标系的矩形选区 → 规范化 4 点多边形(顺时针,整数,夹在画布内)。
  function rectangleToPolygon(start, end, canvas = { width: 1920, height: 1080 }) {
    const clamp = (value, bound) => Math.max(0, Math.min(Math.round(Number(value) || 0), bound));
    const x1 = clamp(Math.min(start.x, end.x), canvas.width);
    const y1 = clamp(Math.min(start.y, end.y), canvas.height);
    const x2 = clamp(Math.max(start.x, end.x), canvas.width);
    const y2 = clamp(Math.max(start.y, end.y), canvas.height);
    if (x2 - x1 < 1 || y2 - y1 < 1) return null;
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]];
  }

  function polygonBounds(polygons) {
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const polygon of polygons || []) {
      for (const [x, y] of polygon) {
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
      }
    }
    if (!Number.isFinite(minX)) return null;
    return { left: minX, top: minY, width: maxX - minX, height: maxY - minY };
  }

  function pointInPolygon(point, polygon) {
    let inside = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
      const [xi, yi] = polygon[i];
      const [xj, yj] = polygon[j];
      const intersects = (yi > point.y) !== (yj > point.y)
        && point.x < ((xj - xi) * (point.y - yi)) / (yj - yi) + xi;
      if (intersects) inside = !inside;
    }
    return inside;
  }

  // ------------------------------------------------------------ 撤销/重做

  // 按页隔离的操作历史。快照 = 条目数组的浅拷贝 JSON(条目均为可序列化
  // 数据);undo/redo 作用于本页编辑,包括删条目;自动保存成功不清空历史。
  function createPageHistory(limit = 60) {
    let undoStack = [];
    let redoStack = [];
    return {
      push(snapshot) {
        undoStack.push(JSON.stringify(snapshot));
        if (undoStack.length > limit) undoStack.shift();
        redoStack = [];
      },
      undo(current) {
        if (!undoStack.length) return null;
        redoStack.push(JSON.stringify(current));
        return JSON.parse(undoStack.pop());
      },
      redo(current) {
        if (!redoStack.length) return null;
        undoStack.push(JSON.stringify(current));
        return JSON.parse(redoStack.pop());
      },
      canUndo() { return undoStack.length > 0; },
      canRedo() { return redoStack.length > 0; },
      remapIds(ids) {
        const rewrite = value => JSON.stringify(JSON.parse(value).map(item => (
          ids.has(item.annotation_id) ? { ...item, annotation_id: ids.get(item.annotation_id) } : item
        )));
        undoStack = undoStack.map(rewrite);
        redoStack = redoStack.map(rewrite);
      },
      reset() { undoStack = []; redoStack = []; },
    };
  }

  // ------------------------------------------------------------ 状态展示

  const STATUS_LABELS = Object.freeze({
    content: Object.freeze({ draft: '待确认', confirmed: '已确认', disabled: '已禁用' }),
    spatial: Object.freeze({ valid: '几何有效', needs_review: '几何待复核', stale: '几何已失效' }),
    temporal: Object.freeze({
      awaiting_audio: '等待音频',
      word_aligned: '字词对齐',
      sentence_fallback: '句级降级',
      manual: '手工定时',
      failed: '对齐失败',
      stale: '时间已失效',
    }),
    styleType: Object.freeze({ ellipse: '手写圈', underline: '横线', highlighter: '荧光笔' }),
  });

  function annotationCardLabel(item, index) {
    const number = String(index + 1).padStart(2, '0');
    const styleLabel = STATUS_LABELS.styleType[item?.style?.type] || '未知样式';
    const contentLabel = STATUS_LABELS.content[item?.status?.content] || '未知状态';
    return `${number} · ${styleLabel} · ${contentLabel}`;
  }

  // UI"笔迹浓度"百分比(0–100)与内部 0–1 互转
  function opacityToPercent(opacity) {
    const value = Number(opacity);
    if (!Number.isFinite(value)) return 85;
    return Math.round(Math.max(0, Math.min(1, value)) * 100);
  }

  function percentToOpacity(percent) {
    const value = Number(percent);
    if (!Number.isFinite(value)) return 0.85;
    return Math.round(Math.max(0, Math.min(100, value)) / 100 * 100) / 100;
  }

  // ------------------------------------------------------------ 操作构造

  let clientOpSeq = 0;

  function buildAddOperation(item) {
    const operation = { op: 'add', item };
    // 幂等键:同一逻辑操作重试(网络响应丢失后重发)时保持不变,
    // 服务端忽略未知字段;本地条目额外携带 __local_id 供保存前合并。
    clientOpSeq += 1;
    operation.client_op_id = `op_${Date.now().toString(36)}_${clientOpSeq}_${Math.random().toString(36).slice(2, 8)}`;
    const localId = item && typeof item.annotation_id === 'string' ? item.annotation_id : '';
    if (localId.startsWith('local_')) operation.__local_id = localId;
    return operation;
  }

  function buildUpdateOperation(annotationId, patch) {
    return { op: 'update', annotation_id: annotationId, patch };
  }

  function buildDeleteOperation(annotationId) {
    return { op: 'delete', annotation_id: annotationId };
  }

  function replayPendingOperations(items, operations) {
    let result = JSON.parse(JSON.stringify(items || []));
    for (const op of operations || []) {
      if (op.op === 'delete') result = result.filter(item => item.annotation_id !== op.annotation_id);
      else if (op.op === 'add') {
        const id = op.__local_id || op.item.annotation_id;
        if (id && !result.some(item => item.annotation_id === id)) {
          result.push({ ...JSON.parse(JSON.stringify(op.item)), annotation_id: id });
        }
      } else if (op.op === 'update') {
        result = result.map(item => {
          if (item.annotation_id !== op.annotation_id) return item;
          const updated = { ...item };
          for (const [key, value] of Object.entries(op.patch || {})) {
            updated[key] = value && typeof value === 'object' && !Array.isArray(value)
              ? { ...item[key], ...value } : value;
          }
          return updated;
        });
      }
    }
    return result;
  }

  function buildRegionTarget(polygon) {
    return {
      kind: 'region',
      layout_revision: null,
      token_ids: [],
      polygons: [polygon],
      quote: null,
      granularity: 'region',
      mask_group_ids: [],
    };
  }

  function buildTextTarget(candidate, polygons) {
    return {
      kind: 'text',
      layout_revision: candidate.layout_revision,
      token_ids: [candidate.token_id],
      polygons,
      quote: candidate.text,
      granularity: candidate.granularity || 'word',
      mask_group_ids: [],
    };
  }

  function buildAnchor(beatId, spokenText, utf16Start, utf16End) {
    const start = utf16IndexToCodepointIndex(spokenText, utf16Start);
    const end = utf16IndexToCodepointIndex(spokenText, utf16End);
    return {
      beat_id: beatId,
      offset_unit: 'unicode_codepoint',
      range: [start, end],
      quote: codepointSlice(spokenText, start, end),
      occurrence: occurrenceIndexOf(spokenText, codepointSlice(spokenText, start, end), start) || 1,
      context_before: codepointSlice(spokenText, Math.max(0, start - 8), start),
      context_after: codepointSlice(spokenText, end, Math.min(end + 8, utf16LengthToCodepointCount(spokenText, spokenText.length))),
    };
  }

  // ------------------------------------------------------------ 冲突分类

  function classifyPatchFailure(status, body) {
    if (status === 409) {
      const currentRevision = Number(body?.detail?.current_revision);
      return {
        kind: 'revision_conflict',
        currentRevision: Number.isFinite(currentRevision) ? currentRevision : null,
        message: '页面已被其他窗口修改,请重载后重试。',
      };
    }
    if (status === 422 && Array.isArray(body?.detail?.issues)) {
      return {
        kind: 'validation_failed',
        issues: body.detail.issues,
        message: '保存被拒绝:存在非法内容。',
      };
    }
    return { kind: 'error', message: '保存失败,请重试。' };
  }

  // ------------------------------------------------------------ 幂等与本地操作合并

  function stableJson(value) {
    return JSON.stringify(value === undefined ? null : value);
  }

  // 判断一条操作在服务端条目列表里是否已经生效(用于网络响应丢失后的
  // 重发去重)。add/restore 按目标内容匹配;delete/update 按条目是否存在判断。
  function operationAlreadyApplied(operation, items) {
    if (!operation || typeof operation !== 'object') return false;
    const list = Array.isArray(items) ? items : [];
    if (operation.op === 'delete' || operation.op === 'update') {
      const id = operation.annotation_id;
      return !list.some(item => item && item.annotation_id === id);
    }
    if (operation.op === 'add' || operation.op === 'restore') {
      const target = operation.item && operation.item.target;
      if (!target) return false;
      return list.some(item => {
        const other = (item && item.target) || {};
        if ((other.kind || '') !== (target.kind || '')) return false;
        if ((other.granularity || '') !== (target.granularity || '')) return false;
        if (stableJson(other.polygons ?? null) !== stableJson(target.polygons ?? null)) return false;
        if (stableJson(other.token_ids ?? null) !== stableJson(target.token_ids ?? null)) return false;
        if (stableJson(other.quote ?? null) !== stableJson(target.quote ?? null)) return false;
        return true;
      });
    }
    return false;
  }

  function dedupeOperationsAgainstPage(operations, items) {
    const applied = [];
    const remaining = [];
    (Array.isArray(operations) ? operations : []).forEach(operation => {
      if (operationAlreadyApplied(operation, items)) applied.push(operation);
      else remaining.push(operation);
    });
    return { applied, remaining };
  }

  // 保存前合并本地(未保存)条目的操作:update/delete 引用 local_ 前缀 id 时,
  // 服务端并不认识该 id;把 patch 就地合并进同批(或失败暂存区)的 add 操作,
  // delete 则撤下对应 add。避免整批 422(unknown_id)。
  function coalesceLocalOperations(operations, failedOps, localItemsById, onLocalDelete) {
    const mergedFailed = Array.isArray(failedOps) ? failedOps.map(op => ({ ...op })) : [];
    const result = [];
    (Array.isArray(operations) ? operations : []).forEach(op => {
      if (!op || typeof op !== 'object') return;
      const localId = typeof op.annotation_id === 'string' && op.annotation_id.startsWith('local_')
        ? op.annotation_id : '';
      if (!localId) {
        result.push(op);
        return;
      }
      if (op.op === 'update') {
        const host = result.find(candidate => candidate.op === 'add' && candidate.__local_id === localId)
          || mergedFailed.find(candidate => candidate.op === 'add' && candidate.__local_id === localId);
        if (host) {
          host.item = { ...(host.item || {}), ...(op.patch || {}) };
        }
        return;
      }
      if (op.op === 'delete') {
        const batchIndex = result.findIndex(candidate => candidate.op === 'add' && candidate.__local_id === localId);
        if (batchIndex >= 0) {
          result.splice(batchIndex, 1);
        } else {
          const failedIndex = mergedFailed.findIndex(candidate => candidate.op === 'add' && candidate.__local_id === localId);
          if (failedIndex >= 0) mergedFailed.splice(failedIndex, 1);
        }
        if (typeof onLocalDelete === 'function') onLocalDelete(localId);
        return;
      }
      result.push(op);
    });
    return { operations: result, failedOps: mergedFailed };
  }

  return Object.freeze({
    utf16LengthToCodepointCount,
    utf16IndexToCodepointIndex,
    codepointIndexToUtf16Index,
    codepointSlice,
    occurrenceIndexOf,
    rectangleToPolygon,
    polygonBounds,
    pointInPolygon,
    createPageHistory,
    STATUS_LABELS,
    annotationCardLabel,
    opacityToPercent,
    percentToOpacity,
    buildAddOperation,
    replayPendingOperations,
    buildUpdateOperation,
    buildDeleteOperation,
    buildRegionTarget,
    buildTextTarget,
    buildAnchor,
    classifyPatchFailure,
    operationAlreadyApplied,
    dedupeOperationsAgainstPage,
    coalesceLocalOperations,
  });
});
