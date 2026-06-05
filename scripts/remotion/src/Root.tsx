import React from 'react';
import {Composition, getInputProps} from 'remotion';
import {ArticleVideo, ArticleVideoProps} from './Video';

const fallbackProps: ArticleVideoProps = {
  fps: 30,
  width: 1920,
  height: 1080,
  total_duration_sec: 10,
  slides: [],
};

export const Root: React.FC = () => {
  const inputProps = {...fallbackProps, ...(getInputProps() as Partial<ArticleVideoProps>)};
  const fps = inputProps.fps ?? 30;
  const width = inputProps.width ?? 1920;
  const height = inputProps.height ?? 1080;
  const durationInFrames = Math.max(1, Math.ceil(inputProps.total_duration_sec * fps));

  return (
    <Composition
      id="ArticleVideo"
      component={ArticleVideo}
      durationInFrames={durationInFrames}
      fps={fps}
      width={width}
      height={height}
      defaultProps={inputProps}
    />
  );
};
