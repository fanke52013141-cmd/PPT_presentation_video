import React from 'react';
import {loadFont as loadNotoSansSC} from '@remotion/google-fonts/NotoSansSC';
import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

const {fontFamily: loadedNotoSansSCFamily} = loadNotoSansSC('normal', {
  weights: ['500'],
  subsets: ['chinese-simplified', 'latin'],
});

type LayerBox = {
  x: number;
  y: number;
  w: number;
  h: number;
};

export type SceneLayer = {
  id: string;
  type: 'png';
  asset: string;
  cutout_asset?: string;
  role?:
    | 'background'
    | 'title'
    | 'subtitle'
    | 'content_body'
    | 'diagram'
    | 'annotation'
    | 'summary'
    | 'decoration'
    | 'full_slide'
    | 'cover_layer'
    | 'fog_layer'
    | 'reveal_crop';
  target_group_id?: string;
  visible_text?: string;
  animation_role?: string;
  content_index?: number;
  box: LayerBox;
  z_index: number;
};

export type Scene = {
  slide_id: string;
  canvas: {
    width: number;
    height: number;
    background: string;
    background_asset?: string;
  };
  layers: SceneLayer[];
};

export type TimelineSegment = {
  id: string;
  start: number;
  end: number;
  text: string;
};

export type AnimationAction =
  | 'fade_in'
  | 'fade_up'
  | 'soft_zoom_in'
  | 'slide_in_left'
  | 'highlight'
  | 'cover_fade_out'
  | 'cover_wipe_left_to_right'
  | 'cover_wipe_right_to_left'
  | 'cover_wipe_top_to_bottom'
  | 'cover_wipe_bottom_to_top'
  | 'fog_diagonal_erase'
  | 'wipe_left_to_right'
  | 'wipe_right_to_left'
  | 'wipe_top_to_bottom'
  | 'wipe_bottom_to_top'
  | 'scratch_reveal'
  | 'brush_wipe_left_to_right'
  | 'crop_fade_up'
  | 'crop_slide_in_left'
  | 'crop_soft_zoom_in'
  | 'sticker_pop'
  | 'stamp_in'
  | 'paper_drop';

export type AnimationEvent = {
  id?: string;
  at: number;
  target: string;
  target_group_id?: string;
  action: AnimationAction;
  duration: number;
  easing?: string;
  params?: Record<string, unknown>;
};

export type Slide = {
  slide_id: string;
  duration_sec: number;
  start_sec: number;
  scene: Scene;
  audio_file?: string;
  audio_timeline?: {
    audio_start_sec?: number;
    segments: TimelineSegment[];
  };
  animation_timeline?: {
    events: AnimationEvent[];
  };
};

export type ArticleVideoProps = {
  fps?: number;
  width?: number;
  height?: number;
  total_duration_sec: number;
  subtitle_style?: SubtitleStyle;
  slides: Slide[];
};

export type SubtitleStyle = {
  font_key?: string;
  font_family?: string;
  font_size?: number;
  font_weight?: number;
  bottom?: number;
  horizontal_margin?: number;
  color?: string;
  // 方案 B：TikTok 式整页分页 + 逐字高亮
  highlight_color?: string;
  paging_window_ms?: number;
  token_highlight?: boolean;
  max_lines?: number;
  line_height?: number;
};

const SUBTITLE_GAP_HOLD_SEC = 0.35;

const hasReadableSubtitleText = (text: string): boolean => /[0-9A-Za-z\u3400-\u9fff]/.test(text);

// ============================================================================
// 方案 B：TikTok 式整页分页 + 逐字高亮
//
// 这里自研了一个与 @remotion/captions.createTikTokStyleCaptions 等价的实现，
// 对中文做了优化（官方实现依赖前导空格检测句子边界，中文不友好）。
//
// 数据流：
//   audio_timeline.segments[]（句子级）
//     ↓ buildCaptionPages
//   CaptionPage[]（每页含完整文本 + tokens[] 时间戳）
//     ↓ pageAtTime / highlightedTokenCount
//   当前帧应显示的 page 与高亮 token 数
//
// 同一句子的所有 token 永远在同一页，从根本上避免"句子中途被切断"。
// ============================================================================

type CaptionToken = {
  text: string;
  fromMs: number;
  toMs: number;
};

type CaptionPage = {
  text: string;
  startMs: number;
  durationMs: number;
  tokens: CaptionToken[];
};

// 句子级 segment → 字级 token
// - 中文按字切（每字一 token）
// - 拉丁/数字按词切
// - 标点单独成 token，权重 0（不占时间）
// - 空白单独成 token，权重 0
const splitSentenceToTokens = (
  text: string,
  startMs: number,
  endMs: number,
): CaptionToken[] => {
  const durationMs = Math.max(0, endMs - startMs);
  const pieces = text.match(/[\u4e00-\u9fff]|[A-Za-z0-9]+|\s+|[^\s\u4e00-\u9fffA-Za-z0-9]/g) || [text];
  // 权重：CJK=1，拉丁词=字母数，标点=0.3（让标点有微小时长以稳定显示），空白=0
  const weights = pieces.map((piece) => {
    if (/\s/.test(piece)) return 0;
    if (/[\u4e00-\u9fff]/.test(piece)) return 1;
    if (/[A-Za-z0-9]/.test(piece)) return piece.length;
    return 0.3;
  });
  const total = weights.reduce((a, b) => a + b, 0);
  if (total <= 0) {
    // 整句无可见字符时，全部时间挂在第一个 piece 上
    return pieces.map((piece) => ({text: piece, fromMs: startMs, toMs: endMs}));
  }
  let cursor = startMs;
  return pieces.map((piece, i) => {
    const dur = (durationMs * weights[i]) / total;
    const token: CaptionToken = {
      text: piece,
      fromMs: cursor,
      toMs: cursor + dur,
    };
    cursor += dur;
    return token;
  });
};

// 把句子级 segments 转成分页 CaptionPage[]
// 同一句子的所有 token 一定在同一页；相邻句子的 gap 大于 pagingWindowMs 时分页
const buildCaptionPages = (
  segments: TimelineSegment[],
  pagingWindowMs: number,
  tokenize: boolean,
): CaptionPage[] => {
  const readable = segments.filter((segment) => hasReadableSubtitleText(segment.text || ''));
  if (readable.length === 0) return [];

  const pages: CaptionPage[] = [];
  let currentTokens: CaptionToken[] = [];
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
  };

  readable.forEach((segment, index) => {
    const segStartMs = segment.start * 1000;
    const segEndMs = segment.end * 1000;
    // 与上一句的 gap 超过窗口，则开新页
    const shouldStartNewPage =
      currentTokens.length > 0 && segStartMs - currentEndMs > pagingWindowMs;
    if (shouldStartNewPage) {
      flush();
    }
    if (currentTokens.length === 0) {
      currentStartMs = segStartMs;
    }
    if (tokenize) {
      const tokens = splitSentenceToTokens(segment.text, segStartMs, segEndMs);
      currentTokens.push(...tokens);
    } else {
      // 不切 token：整句作为一个 token
      currentTokens.push({text: segment.text, fromMs: segStartMs, toMs: segEndMs});
    }
    currentText += segment.text;
    currentEndMs = Math.max(currentEndMs, segEndMs);
    if (index === readable.length - 1) {
      flush();
    }
  });

  return pages;
};

// 找当前时间所在的 page（找不到时回退到上一个，gap ≤ 350ms 内仍显示）
const pageAtTime = (pages: CaptionPage[], audioSeconds: number): CaptionPage | undefined => {
  if (audioSeconds < 0 || pages.length === 0) return undefined;
  const ms = audioSeconds * 1000;
  let previous: CaptionPage | undefined;
  for (const page of pages) {
    if (ms >= page.startMs && ms < page.startMs + page.durationMs) {
      return page;
    }
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
};

// 计算当前 page 应高亮的 token 数量（已朗读的 token）
const highlightedTokenCount = (page: CaptionPage, audioSeconds: number): number => {
  const ms = audioSeconds * 1000;
  let count = 0;
  for (const token of page.tokens) {
    if (ms >= token.toMs - 1) {
      // token 已读完
      count++;
    } else if (ms >= token.fromMs) {
      // token 正在读：算作高亮（让用户看到正在朗读的词进入高亮状态）
      count++;
      break;
    } else {
      break;
    }
  }
  return count;
};

// 旧逻辑保留作为 fallback（无 segments 时使用）
const subtitleAtTime = (segments: TimelineSegment[], audioSeconds: number): TimelineSegment | undefined => {
  if (audioSeconds < 0) {
    return undefined;
  }
  const readable = segments.filter((segment) => hasReadableSubtitleText(segment.text || ''));
  let previous: TimelineSegment | undefined;
  for (const segment of readable) {
    if (audioSeconds >= segment.start && audioSeconds < segment.end) {
      return segment;
    }
    if (segment.end <= audioSeconds) {
      previous = segment;
      continue;
    }
    if (segment.start > audioSeconds) {
      return previous && audioSeconds - previous.end <= SUBTITLE_GAP_HOLD_SEC ? previous : undefined;
    }
  }
  return previous && audioSeconds - previous.end <= SUBTITLE_GAP_HOLD_SEC ? previous : undefined;
};

const subtitleFontFamily = (fontKey?: string, configuredFamily?: string, fontWeight?: number): string => {
  const key = fontKey || 'noto_sans_sc';
  const configured = configuredFamily ? `"${configuredFamily}", ` : '';
  const sansFallback = '"Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif';
  const serifFallback = '"Noto Serif CJK SC", SimSun, "Songti SC", serif';
  const handwrittenFallback = '"Microsoft YaHei", KaiTi, cursive';
  const families: Record<string, string> = {
    noto_sans_sc: `${configured}"${loadedNotoSansSCFamily}", ${sansFallback}`,
    noto_serif_sc: `${configured}"Noto Serif SC", ${serifFallback}`,
    ma_shan_zheng: `${configured}"Ma Shan Zheng", ${handwrittenFallback}`,
    zcool_xiaowei: `${configured}"ZCOOL XiaoWei", ${serifFallback}`,
    zcool_qingke: `${configured}"ZCOOL QingKe HuangYou", ${sansFallback}`,
    zcool_kuaile: `${configured}"ZCOOL KuaiLe", ${sansFallback}`,
    long_cang: `${configured}"Long Cang", ${handwrittenFallback}`,
    liu_jian_mao_cao: `${configured}"Liu Jian Mao Cao", ${handwrittenFallback}`,
    zhi_mang_xing: `${configured}"Zhi Mang Xing", ${handwrittenFallback}`,
    lxgw_marker_gothic: `${configured}"LXGW Marker Gothic", ${sansFallback}`,
    lxgw_wenkai_tc: `${configured}"LXGW WenKai TC", "Microsoft JhengHei", ${sansFallback}`,
    lxgw_wenkai: `${configured}"LXGW WenKai", KaiTi, ${sansFallback}`,
    noto_sans_tc: `${configured}"Noto Sans TC", "Microsoft JhengHei", ${sansFallback}`,
    noto_serif_tc: `${configured}"Noto Serif TC", MingLiU, serif`,
  };
  return families[key] || `${configured}${sansFallback}`;
};

const toAssetSrc = (value?: string): string | undefined => {
  if (!value) {
    return undefined;
  }
  const normalized = value.replace(/\\/g, '/');
  if (normalized.startsWith('file:///') || normalized.startsWith('http://') || normalized.startsWith('https://')) {
    return normalized;
  }
  if (/^[A-Za-z]:\//.test(normalized)) {
    return `file:///${normalized}`;
  }
  return staticFile(normalized);
};

const getEvents = (events: AnimationEvent[] | undefined, id: string): AnimationEvent[] => {
  return (events ?? []).filter((event) => event.target === id).sort((a, b) => a.at - b.at);
};

const eventProgress = (frame: number, fps: number, event: AnimationEvent): number => {
  const start = event.at * fps;
  const duration = Math.max(1, event.duration * fps);
  return interpolate(frame, [start, start + duration], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
};

const numericParam = (event: AnimationEvent, key: string, fallback: number): number => {
  const value = event.params?.[key];
  return typeof value === 'number' ? value : fallback;
};

const maskGradient = (angle: number, progress: number, feather: number): string => {
  const sweep = -35 + progress * 170;
  return `linear-gradient(${angle}deg, transparent ${sweep - feather}%, transparent ${sweep}%, black ${sweep + feather}%)`;
};

const revealStyle = (
  frame: number,
  fps: number,
  events: AnimationEvent[],
  base: React.CSSProperties
): React.CSSProperties => {
  const revealEvent = events.find((event) =>
    [
      'cover_fade_out',
      'cover_wipe_left_to_right',
      'cover_wipe_right_to_left',
      'cover_wipe_top_to_bottom',
      'cover_wipe_bottom_to_top',
      'fog_diagonal_erase',
      'wipe_left_to_right',
      'wipe_right_to_left',
      'wipe_top_to_bottom',
      'wipe_bottom_to_top',
      'scratch_reveal',
      'brush_wipe_left_to_right',
    ].includes(event.action)
  );
  if (!revealEvent) {
    return base;
  }

  const progress = eventProgress(frame, fps, revealEvent);
  if (revealEvent.action === 'cover_fade_out') {
    return {...base, opacity: 1 - progress};
  }

  if (revealEvent.action === 'cover_wipe_left_to_right') {
    return {
      ...base,
      clipPath: `inset(0 0 0 ${progress * 100}%)`,
    };
  }

  if (revealEvent.action === 'cover_wipe_right_to_left') {
    return {
      ...base,
      clipPath: `inset(0 ${progress * 100}% 0 0)`,
    };
  }

  if (revealEvent.action === 'cover_wipe_top_to_bottom') {
    return {
      ...base,
      clipPath: `inset(${progress * 100}% 0 0 0)`,
    };
  }

  if (revealEvent.action === 'cover_wipe_bottom_to_top') {
    return {
      ...base,
      clipPath: `inset(0 0 ${progress * 100}% 0)`,
    };
  }

  if (revealEvent.action === 'wipe_left_to_right') {
    return {
      ...base,
      clipPath: `inset(0 ${100 - progress * 100}% 0 0)`,
    };
  }

  if (revealEvent.action === 'wipe_right_to_left') {
    return {
      ...base,
      clipPath: `inset(0 0 0 ${100 - progress * 100}%)`,
    };
  }

  if (revealEvent.action === 'wipe_top_to_bottom') {
    return {
      ...base,
      clipPath: `inset(0 0 ${100 - progress * 100}% 0)`,
    };
  }

  if (revealEvent.action === 'wipe_bottom_to_top') {
    return {
      ...base,
      clipPath: `inset(${100 - progress * 100}% 0 0 0)`,
    };
  }

  const feather = numericParam(revealEvent, 'feather', 16);
  const angle = revealEvent.action === 'brush_wipe_left_to_right'
    ? 90
    : numericParam(revealEvent, 'angle', revealEvent.action === 'scratch_reveal' ? 100 : 135);
  const maskImage = maskGradient(angle, progress, feather);
  return {
    ...base,
    WebkitMaskImage: maskImage,
    maskImage,
  } as React.CSSProperties;
};

const animatedStyle = (
  frame: number,
  fps: number,
  events: AnimationEvent[],
  base: React.CSSProperties
): React.CSSProperties => {
  if (events.length === 0) {
    return base;
  }

  let style: React.CSSProperties = revealStyle(frame, fps, events, base);
  const entryEvent = events.find((event) =>
    [
      'fade_in',
      'fade_up',
      'soft_zoom_in',
      'slide_in_left',
      'crop_fade_up',
      'crop_slide_in_left',
      'crop_soft_zoom_in',
      'sticker_pop',
      'stamp_in',
      'paper_drop',
    ].includes(event.action)
  );

  if (entryEvent) {
    const start = entryEvent.at * fps;
    const progress = eventProgress(frame, fps, entryEvent);
    const springProgress = spring({
      frame: Math.max(0, frame - start),
      fps,
      config: {damping: 18, stiffness: 110, mass: 0.8},
    });

    if (entryEvent.action === 'crop_fade_up') {
      style = {...style, opacity: progress};
    } else if (entryEvent.action === 'fade_up') {
      style = {...style, opacity: progress, transform: `translateY(${(1 - springProgress) * 24}px)`};
    } else if (entryEvent.action === 'slide_in_left' || entryEvent.action === 'crop_slide_in_left') {
      style = {...style, opacity: progress, transform: `translateX(${(1 - springProgress) * -28}px)`};
    } else if (entryEvent.action === 'soft_zoom_in' || entryEvent.action === 'crop_soft_zoom_in') {
      style = {...style, opacity: progress, transform: `scale(${0.97 + springProgress * 0.03})`};
    } else if (entryEvent.action === 'sticker_pop') {
      const rotation = numericParam(entryEvent, 'rotation', -4);
      style = {
        ...style,
        opacity: progress,
        transformOrigin: '50% 50%',
        transform: `scale(${0.72 + springProgress * 0.28}) rotate(${rotation * (1 - springProgress)}deg)`,
        filter: `drop-shadow(0 ${10 * (1 - springProgress)}px ${14 * (1 - springProgress)}px rgba(0,0,0,0.22))`,
      };
    } else if (entryEvent.action === 'stamp_in') {
      const rotation = numericParam(entryEvent, 'rotation', 2);
      style = {
        ...style,
        opacity: progress,
        transformOrigin: '50% 50%',
        transform: `scale(${1.55 - springProgress * 0.55}) rotate(${rotation * (1 - springProgress)}deg)`,
      };
    } else if (entryEvent.action === 'paper_drop') {
      const rotation = numericParam(entryEvent, 'rotation', -3);
      style = {
        ...style,
        opacity: progress,
        transformOrigin: '50% 20%',
        transform: `translateY(${(1 - springProgress) * -48}px) rotate(${rotation * (1 - springProgress)}deg)`,
        filter: `drop-shadow(0 ${8 * (1 - springProgress)}px ${12 * (1 - springProgress)}px rgba(0,0,0,0.18))`,
      };
    } else {
      style = {...style, opacity: progress};
    }
  }

  const highlightEvents = events.filter((event) => event.action === 'highlight');
  if (highlightEvents.length === 0) {
    return style;
  }

  const glow = Math.max(
    ...highlightEvents.map((event) => {
      const start = event.at * fps;
      const duration = Math.max(1, event.duration * fps);
      return interpolate(frame, [start, start + duration * 0.5, start + duration], [0, 1, 0], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      });
    })
  );
  return {
    ...style,
    filter: `drop-shadow(0 0 ${18 * glow}px rgba(249,214,92,${0.38 * glow}))`,
  };
};

const LayerView: React.FC<{layer: SceneLayer; events?: AnimationEvent[]}> = ({layer, events}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const base: React.CSSProperties = {
    position: 'absolute',
    left: layer.box.x,
    top: layer.box.y,
    width: layer.box.w,
    height: layer.box.h,
    zIndex: layer.z_index,
    overflow: 'hidden',
  };
  const style = animatedStyle(frame, fps, getEvents(events, layer.id), base);

  return (
    <Img
      src={toAssetSrc(layer.asset) ?? ''}
      style={{
        ...style,
        width: layer.box.w,
        height: layer.box.h,
        objectFit: 'contain',
      }}
    />
  );
};

const SubtitleView: React.FC<{
  page: CaptionPage;
  highlightCount: number;
  subtitleStyle?: SubtitleStyle;
  fontFamily: string;
}> = ({page, highlightCount, subtitleStyle, fontFamily}) => {
  const baseColor = subtitleStyle?.color ?? '#111111';
  const highlightColor = subtitleStyle?.highlight_color ?? '#1E3A8A';
  const fontSize = subtitleStyle?.font_size ?? 38;
  const baseFontWeight = subtitleStyle?.font_weight ?? 500;
  const maxLines = subtitleStyle?.max_lines ?? 2;
  const lineHeight = subtitleStyle?.line_height ?? 1.4;
  const horizontalMargin = subtitleStyle?.horizontal_margin ?? 180;
  const bottom = subtitleStyle?.bottom ?? 18;
  const enableHighlight = subtitleStyle?.token_highlight !== false;
  const highlightFontWeight = Math.min(700, baseFontWeight + 100);

  return (
    <div
      style={{
        position: 'absolute',
        left: horizontalMargin,
        right: horizontalMargin,
        bottom,
        zIndex: 10000,
        // 给 maxLines 行预留空间，避免内容居中导致位置抖动
        minHeight: Math.ceil(fontSize * lineHeight) * maxLines,
        // 使用 -webkit-box 实现 line-clamp 多行裁切，alignItems 走 flex 容器外层处理
        display: '-webkit-box',
        WebkitBoxOrient: 'vertical',
        WebkitLineClamp: maxLines,
        justifyContent: 'center',
        boxSizing: 'border-box',
        padding: '0 24px',
        color: baseColor,
        background: 'transparent',
        fontSize,
        fontWeight: baseFontWeight,
        lineHeight,
        textAlign: 'center',
        // 关键 CSS：保留空格、允许自然换行、词内不切断、限制最多 maxLines 行
        whiteSpace: 'pre-wrap',
        wordBreak: 'keep-all',
        overflowWrap: 'normal',
        fontFamily,
        overflow: 'hidden',
      }}
    >
      {page.tokens.map((token, i) => {
        const isHighlighted = enableHighlight && i < highlightCount;
        return (
          <span
            key={i}
            style={{
              color: isHighlighted ? highlightColor : baseColor,
              fontWeight: isHighlighted ? highlightFontWeight : baseFontWeight,
            }}
          >
            {token.text}
          </span>
        );
      })}
    </div>
  );
};

const SlideView: React.FC<{slide: Slide; subtitleStyle?: SubtitleStyle}> = ({slide, subtitleStyle}) => {
  const segments = slide.audio_timeline?.segments ?? [];
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const seconds = frame / fps;
  const audioStartSec = slide.audio_timeline?.audio_start_sec ?? 0;
  const audioSeconds = seconds - audioStartSec;

  // 方案 B：用 page + token 高亮替代单 segment 显示
  const tokenize = subtitleStyle?.token_highlight !== false;
  const pagingWindowMs = subtitleStyle?.paging_window_ms ?? 1300;
  const pages = React.useMemo(
    () => buildCaptionPages(segments, pagingWindowMs, tokenize),
    [segments, pagingWindowMs, tokenize],
  );
  const activePage = pageAtTime(pages, audioSeconds);
  const highlightCount = activePage ? highlightedTokenCount(activePage, audioSeconds) : 0;

  // Fallback：无 segments 或 buildCaptionPages 返回空时回到旧逻辑
  const fallbackSubtitle = pages.length === 0 ? subtitleAtTime(segments, audioSeconds) : undefined;

  const background = toAssetSrc(slide.scene.canvas.background_asset);
  const layers = slide.scene.layers ?? [];
  const subtitleFont = subtitleFontFamily(
    subtitleStyle?.font_key,
    subtitleStyle?.font_family,
    subtitleStyle?.font_weight,
  );
  const horizontalMargin = subtitleStyle?.horizontal_margin ?? 180;
  const fallbackColor = subtitleStyle?.color ?? '#111111';
  const fallbackFontSize = subtitleStyle?.font_size ?? 38;
  const fallbackFontWeight = subtitleStyle?.font_weight ?? 500;
  const fallbackLineHeight = subtitleStyle?.line_height ?? 1.4;
  const fallbackMaxLines = subtitleStyle?.max_lines ?? 2;

  return (
    <AbsoluteFill style={{background: slide.scene.canvas.background || '#FEFDF9'}}>
      {background ? <Img src={background} style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'}} /> : null}
      {layers
        .slice()
        .sort((a, b) => a.z_index - b.z_index)
        .map((layer) => (
          <LayerView key={layer.id} layer={layer} events={slide.animation_timeline?.events} />
        ))}
      {activePage ? (
        <SubtitleView
          page={activePage}
          highlightCount={highlightCount}
          subtitleStyle={subtitleStyle}
          fontFamily={subtitleFont}
        />
      ) : fallbackSubtitle ? (
        <div
          style={{
            position: 'absolute',
            left: horizontalMargin,
            right: horizontalMargin,
            bottom: subtitleStyle?.bottom ?? 18,
            zIndex: 10000,
            minHeight: Math.ceil(fallbackFontSize * fallbackLineHeight) * fallbackMaxLines,
            display: '-webkit-box',
            WebkitBoxOrient: 'vertical',
            WebkitLineClamp: fallbackMaxLines,
            justifyContent: 'center',
            boxSizing: 'border-box',
            padding: '0 24px',
            color: fallbackColor,
            background: 'transparent',
            fontSize: fallbackFontSize,
            fontWeight: fallbackFontWeight,
            lineHeight: fallbackLineHeight,
            textAlign: 'center',
            whiteSpace: 'pre-wrap',
            wordBreak: 'keep-all',
            overflowWrap: 'normal',
            fontFamily: subtitleFont,
            overflow: 'hidden',
          }}
        >
          {fallbackSubtitle.text}
        </div>
      ) : null}
      {slide.audio_file ? (
        <Sequence from={Math.max(0, Math.round(audioStartSec * fps))}>
          <Audio src={toAssetSrc(slide.audio_file) ?? ''} />
        </Sequence>
      ) : null}
    </AbsoluteFill>
  );
};

export const ArticleVideo: React.FC<ArticleVideoProps> = ({slides, subtitle_style}) => {
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{background: '#FEFDF9'}}>
      {slides.map((slide) => (
        <Sequence
          key={slide.slide_id}
          from={Math.round(slide.start_sec * fps)}
          durationInFrames={Math.max(1, Math.round(slide.duration_sec * fps))}
        >
          <SlideView slide={slide} subtitleStyle={subtitle_style} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
