import React from 'react';
import {Composition} from 'remotion';
import {ArticleVideo} from './Video';

export const Root: React.FC = () => {
  return (
    <Composition
      id="ArticleVideo"
      component={ArticleVideo}
      durationInFrames={30 * 180}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={{
        manifestPath: '../../runs/demo/run_manifest.yaml',
      }}
    />
  );
};

