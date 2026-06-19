import React from 'react';
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
  | 'cover_wipe_top_to_bottom'
  | 'fog_diagonal_erase'
  | 'crop_fade_up'
  | 'crop_slide_in_left'
  | 'crop_soft_zoom_in';

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
  slides: Slide[];
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

const revealStyle = (
  frame: number,
  fps: number,
  events: AnimationEvent[],
  base: React.CSSProperties
): React.CSSProperties => {
  const revealEvent = events.find((event) =>
    ['cover_fade_out', 'cover_wipe_left_to_right', 'cover_wipe_top_to_bottom', 'fog_diagonal_erase'].includes(event.action)
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

  if (revealEvent.action === 'cover_wipe_top_to_bottom') {
    return {
      ...base,
      clipPath: `inset(${progress * 100}% 0 0 0)`,
    };
  }

  const feather = numericParam(revealEvent, 'feather', 16);
  const angle = numericParam(revealEvent, 'angle', 135);
  const sweep = -35 + progress * 170;
  const maskImage = `linear-gradient(${angle}deg, transparent ${sweep - feather}%, transparent ${sweep}%, black ${sweep + feather}%)`;
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
    ['fade_in', 'fade_up', 'soft_zoom_in', 'slide_in_left', 'crop_fade_up', 'crop_slide_in_left', 'crop_soft_zoom_in'].includes(event.action)
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

const SlideView: React.FC<{slide: Slide}> = ({slide}) => {
  const segments = slide.audio_timeline?.segments ?? [];
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const seconds = frame / fps;
  const audioStartSec = slide.audio_timeline?.audio_start_sec ?? 0;
  const audioSeconds = seconds - audioStartSec;
  const activeSubtitle = audioSeconds >= 0
    ? segments.find((segment) => audioSeconds >= segment.start && audioSeconds < segment.end)
    : undefined;
  const background = toAssetSrc(slide.scene.canvas.background_asset);
  const layers = slide.scene.layers ?? [];

  return (
    <AbsoluteFill style={{background: slide.scene.canvas.background || '#FEFDF9'}}>
      {background ? <Img src={background} style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'}} /> : null}
      {layers
        .slice()
        .sort((a, b) => a.z_index - b.z_index)
        .map((layer) => (
          <LayerView key={layer.id} layer={layer} events={slide.animation_timeline?.events} />
        ))}
      {activeSubtitle ? (
        <div
          style={{
            position: 'absolute',
            left: 180,
            right: 180,
            bottom: 18,
            zIndex: 10000,
            minHeight: 54,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxSizing: 'border-box',
            padding: '0 24px',
            color: '#111111',
            background: 'transparent',
            fontSize: 38,
            fontWeight: 500,
            lineHeight: 1.15,
            textAlign: 'center',
            whiteSpace: 'normal',
            overflow: 'visible',
            overflowWrap: 'anywhere',
            fontFamily: 'LXGW WenKai, KaiTi, Microsoft YaHei, sans-serif',
          }}
        >
          {activeSubtitle.text}
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

export const ArticleVideo: React.FC<ArticleVideoProps> = ({slides}) => {
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{background: '#FEFDF9'}}>
      {slides.map((slide) => (
        <Sequence
          key={slide.slide_id}
          from={Math.round(slide.start_sec * fps)}
          durationInFrames={Math.max(1, Math.round(slide.duration_sec * fps))}
        >
          <SlideView slide={slide} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
