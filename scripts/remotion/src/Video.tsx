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
  role?: 'background' | 'title' | 'subtitle' | 'content_body' | 'diagram' | 'annotation' | 'summary' | 'decoration' | 'full_slide';
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

export type AnimationEvent = {
  at: number;
  target: string;
  action: 'fade_in' | 'fade_up' | 'soft_zoom_in' | 'slide_in_left' | 'highlight';
  duration: number;
};

export type Slide = {
  slide_id: string;
  duration_sec: number;
  start_sec: number;
  scene: Scene;
  audio_file?: string;
  audio_timeline?: {
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

const getEvent = (events: AnimationEvent[] | undefined, id: string): AnimationEvent | undefined => {
  return events?.find((event) => event.target === id);
};

const animatedStyle = (
  frame: number,
  fps: number,
  event: AnimationEvent | undefined,
  base: React.CSSProperties
): React.CSSProperties => {
  if (!event) {
    return base;
  }

  const start = event.at * fps;
  const duration = Math.max(1, event.duration * fps);
  const progress = interpolate(frame, [start, start + duration], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const springProgress = spring({
    frame: Math.max(0, frame - start),
    fps,
    config: {damping: 18, stiffness: 110, mass: 0.8},
  });

  if (event.action === 'fade_up') {
    return {...base, opacity: progress, transform: `translateY(${(1 - springProgress) * 28}px)`};
  }
  if (event.action === 'slide_in_left') {
    return {...base, opacity: progress, transform: `translateX(${(1 - springProgress) * -34}px)`};
  }
  if (event.action === 'soft_zoom_in') {
    return {...base, opacity: progress, transform: `scale(${0.96 + springProgress * 0.04})`};
  }
  if (event.action === 'highlight') {
    const glow = interpolate(frame, [start, start + duration * 0.5, start + duration], [0, 1, 0], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    return {
      ...base,
      opacity: 1,
      filter: `drop-shadow(0 0 ${18 * glow}px rgba(249,214,92,${0.38 * glow}))`,
    };
  }
  return {...base, opacity: progress};
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
    overflow: 'visible',
  };
  const style = animatedStyle(frame, fps, getEvent(events, layer.id), base);

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
  const activeSubtitle = segments.find((segment) => seconds >= segment.start && seconds < segment.end);
  const background = toAssetSrc(slide.scene.canvas.background_asset);
  const layers = slide.scene.layers ?? [];

  return (
    <AbsoluteFill style={{background: slide.scene.canvas.background || '#FFFDF7'}}>
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
            bottom: 28,
            height: 82,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxSizing: 'border-box',
            padding: '0 36px',
            color: '#111111',
            background: 'rgba(255, 253, 247, 0.82)',
            borderRadius: 24,
            fontSize: 38,
            fontWeight: 500,
            lineHeight: 1.15,
            textAlign: 'center',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            fontFamily: 'LXGW WenKai, KaiTi, Microsoft YaHei, sans-serif',
          }}
        >
          {activeSubtitle.text}
        </div>
      ) : null}
      {slide.audio_file ? <Audio src={toAssetSrc(slide.audio_file) ?? ''} /> : null}
    </AbsoluteFill>
  );
};

export const ArticleVideo: React.FC<ArticleVideoProps> = ({slides}) => {
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{background: '#FFFDF7'}}>
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
