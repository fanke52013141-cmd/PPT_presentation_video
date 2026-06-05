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

type ElementBox = {
  x: number;
  y: number;
  w: number;
  h: number;
};

export type SceneElement = {
  id: string;
  type: 'text' | 'image' | 'shape' | 'line' | 'group';
  text?: string;
  asset?: string;
  style_token?: string;
  animation_role?: string;
  semantic_role?: string;
  content_index?: number;
  box: ElementBox;
  z_index: number;
  style?: Record<string, unknown>;
};

export type Scene = {
  slide_id: string;
  canvas: {
    width: number;
    height: number;
    background: string;
    background_asset?: string;
  };
  elements: SceneElement[];
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
  action: 'fade_in' | 'fade_up' | 'soft_zoom_in' | 'slide_in_left' | 'highlight' | 'line_draw';
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

const textStyle = (element: SceneElement): React.CSSProperties => {
  const token = element.style_token;
  if (token === 'main_title') {
    return {
      fontSize: 58,
      fontWeight: 700,
      lineHeight: 1.1,
      color: '#1E3A5F',
      fontFamily: 'Microsoft YaHei, Source Han Sans SC, Noto Sans CJK SC, sans-serif',
    };
  }
  if (token === 'subtitle') {
    return {
      fontSize: 24,
      fontWeight: 500,
      lineHeight: 1.25,
      color: '#5C574F',
      fontFamily: 'Microsoft YaHei, Source Han Sans SC, Noto Sans CJK SC, sans-serif',
    };
  }
  if (token === 'content_point_title') {
    return {
      fontSize: 31,
      fontWeight: 700,
      lineHeight: 1.18,
      color: '#151515',
      fontFamily: 'Microsoft YaHei, Source Han Sans SC, Noto Sans CJK SC, sans-serif',
    };
  }
  if (token === 'content_point_body') {
    return {
      fontSize: 24,
      fontWeight: 400,
      lineHeight: 1.35,
      color: '#5C574F',
      fontFamily: 'Microsoft YaHei, Source Han Sans SC, Noto Sans CJK SC, sans-serif',
    };
  }
  return {
    fontSize: 28,
    fontWeight: 400,
    lineHeight: 1.45,
    color: '#151515',
    fontFamily: 'Microsoft YaHei, Source Han Sans SC, Noto Sans CJK SC, sans-serif',
  };
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
    return {...base, opacity: 1, boxShadow: `0 0 ${20 * glow}px rgba(230,126,67,${0.28 * glow})`};
  }
  return {...base, opacity: progress};
};

const ShapeView: React.FC<{element: SceneElement; style: React.CSSProperties}> = ({element, style}) => {
  const role = element.semantic_role;
  if (role === 'content_highlight') {
    return (
      <div
        style={{
          ...style,
          borderRadius: 8,
          background: '#EEE7DB',
          border: '1px solid rgba(184,175,160,0.38)',
          boxShadow: '0 8px 18px rgba(92,87,79,0.08)',
        }}
      />
    );
  }
  if (role === 'content_shape') {
    return (
      <div
        style={{
          ...style,
          borderRadius: '50%',
          background: String(element.style?.fill ?? '#2FA39A'),
        }}
      />
    );
  }
  return <div style={{...style, borderRadius: 8, background: '#EEE7DB'}} />;
};

const ElementView: React.FC<{element: SceneElement; events?: AnimationEvent[]}> = ({element, events}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const base: React.CSSProperties = {
    position: 'absolute',
    left: element.box.x,
    top: element.box.y,
    width: element.box.w,
    height: element.box.h,
    zIndex: element.z_index,
    overflow: 'hidden',
  };
  const style = animatedStyle(frame, fps, getEvent(events, element.id), base);

  if (element.type === 'text') {
    return (
      <div style={{...style, ...textStyle(element), overflow: 'visible', whiteSpace: 'pre-wrap'}}>
        {element.text}
      </div>
    );
  }

  if (element.type === 'image' && element.asset) {
    return (
      <Img
        src={toAssetSrc(element.asset) ?? ''}
        style={{
          ...style,
          width: element.box.w,
          height: element.box.h,
          objectFit: 'contain',
        }}
      />
    );
  }

  if (element.type === 'shape') {
    return <ShapeView element={element} style={style} />;
  }

  return null;
};

const SlideView: React.FC<{slide: Slide}> = ({slide}) => {
  const segments = slide.audio_timeline?.segments ?? [];
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const seconds = frame / fps;
  const activeSubtitle = segments.find((segment) => seconds >= segment.start && seconds < segment.end);
  const background = toAssetSrc(slide.scene.canvas.background_asset);

  return (
    <AbsoluteFill style={{background: slide.scene.canvas.background}}>
      {background ? <Img src={background} style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'}} /> : null}
      {slide.scene.elements
        .slice()
        .sort((a, b) => a.z_index - b.z_index)
        .map((element) => (
          <ElementView key={element.id} element={element} events={slide.animation_timeline?.events} />
        ))}
      {activeSubtitle ? (
        <div
          style={{
            position: 'absolute',
            left: 72,
            right: 72,
            bottom: 8,
            height: 82,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxSizing: 'border-box',
            padding: '0 20px',
            color: '#FFFFFF',
            fontSize: 30,
            fontWeight: 500,
            lineHeight: 1.18,
            textAlign: 'center',
            fontFamily: 'Microsoft YaHei, Source Han Sans SC, Noto Sans CJK SC, sans-serif',
            textShadow: '0 2px 8px rgba(0,0,0,0.22)',
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
    <AbsoluteFill style={{background: '#F6F2EC'}}>
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
