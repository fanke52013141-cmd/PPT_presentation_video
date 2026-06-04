import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';

type ElementBox = {
  x: number;
  y: number;
  w: number;
  h: number;
};

type SceneElement = {
  id: string;
  type: 'text' | 'image' | 'shape' | 'line' | 'group';
  text?: string;
  asset?: string;
  style_token?: string;
  box: ElementBox;
  z_index: number;
};

type Scene = {
  slide_id: string;
  canvas: {
    width: number;
    height: number;
    background: string;
  };
  elements: SceneElement[];
};

const demoScene: Scene = {
  slide_id: 'demo',
  canvas: {width: 1920, height: 1080, background: '#F7F8FA'},
  elements: [
    {
      id: 'title',
      type: 'text',
      text: '为什么 AI 突然变聪明了？',
      style_token: 'title_lg',
      box: {x: 120, y: 96, w: 1180, h: 110},
      z_index: 10,
    },
    {
      id: 'subtitle',
      type: 'text',
      text: '从规模、数据和反馈说起',
      style_token: 'subtitle',
      box: {x: 120, y: 220, w: 900, h: 64},
      z_index: 10,
    },
    {
      id: 'diagram',
      type: 'shape',
      box: {x: 1120, y: 260, w: 520, h: 420},
      z_index: 3,
    },
  ],
};

const textStyle = (token?: string): React.CSSProperties => {
  if (token === 'title_lg') {
    return {fontSize: 64, fontWeight: 700, lineHeight: 1.14, color: '#111827'};
  }
  if (token === 'subtitle') {
    return {fontSize: 30, fontWeight: 500, lineHeight: 1.35, color: '#4B5563'};
  }
  return {fontSize: 28, lineHeight: 1.5, color: '#111827'};
};

const ElementView: React.FC<{element: SceneElement}> = ({element}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const entrance = spring({frame, fps, config: {damping: 18, stiffness: 120}});
  const opacity = interpolate(frame, [0, 18], [0, 1], {extrapolateRight: 'clamp'});
  const style: React.CSSProperties = {
    position: 'absolute',
    left: element.box.x,
    top: element.box.y,
    width: element.box.w,
    height: element.box.h,
    zIndex: element.z_index,
    opacity,
    transform: `translateY(${(1 - entrance) * 24}px)`,
  };

  if (element.type === 'text') {
    return <div style={{...style, ...textStyle(element.style_token)}}>{element.text}</div>;
  }

  if (element.type === 'shape') {
    return (
      <div
        style={{
          ...style,
          borderRadius: 24,
          background: 'linear-gradient(135deg, #DBEAFE, #CCFBF1)',
          border: '2px solid #D1D5DB',
        }}
      />
    );
  }

  if (element.type === 'image' && element.asset) {
    return <img src={element.asset} style={{...style, objectFit: 'contain'}} />;
  }

  return null;
};

export const ArticleVideo: React.FC<{manifestPath: string}> = () => {
  const scene = demoScene;
  return (
    <AbsoluteFill style={{background: scene.canvas.background, fontFamily: 'Microsoft YaHei, Inter, sans-serif'}}>
      {scene.elements.map((element) => (
        <ElementView key={element.id} element={element} />
      ))}
    </AbsoluteFill>
  );
};

