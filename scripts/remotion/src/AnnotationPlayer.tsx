import React from 'react';
import {createRoot, Root} from 'react-dom/client';
import {Player, PlayerRef} from '@remotion/player';
import {Html5Video} from 'remotion';
import {ArticleVideo, ArticleVideoProps} from './Video';

let root: Root | null = null;
let player: PlayerRef | null = null;
let renderPlayer: ((rate: number) => void) | null = null;
const api = {
  mount(node: HTMLElement, props: ArticleVideoProps, fps: number, duration: number, width: number, height: number) {
    api.stop();
    root = createRoot(node);
    renderPlayer = (rate) => root?.render(<Player component={ArticleVideo} inputProps={props}
      ref={(ref) => {player = ref;}}
      compositionWidth={width} compositionHeight={height} fps={fps}
      durationInFrames={Math.max(1, Math.ceil(duration * fps))}
      controls autoPlay={false} showVolumeControls playbackRate={rate}
      style={{width: '100%', maxHeight: '70vh'}} />);
    renderPlayer(1);
  },
  stop() {player?.pause(); root?.unmount(); root = null; player = null; renderPlayer = null;},
  frame() {return player?.getCurrentFrame() ?? 0;},
  rate(rate: number) {renderPlayer?.(rate);},
  pause() {player?.pause();},
  seek(frame: number) {player?.seekTo(frame);},
};
(window as unknown as {AnnotationPlayer: typeof api}).AnnotationPlayer = api;

// Output MP4s use the same Player controls as annotation previews.
const RecordedVideo: React.FC<{src: string}> = ({src}) => (
  <Html5Video src={src} style={{width: '100%', height: '100%', objectFit: 'contain'}} />
);
const outputPlayers = new Map<HTMLElement, Root>();
const outputApi = {
  mount(node: HTMLElement, src: string, duration: number, width: number, height: number) {
    const outputRoot = createRoot(node);
    outputPlayers.set(node, outputRoot);
    let ref: PlayerRef | null = null;
    const render = (rate: number) => outputRoot.render(
      <Player component={RecordedVideo} inputProps={{src}} ref={value => {ref = value;}}
        compositionWidth={width} compositionHeight={height} fps={30}
        durationInFrames={Math.max(1, Math.ceil(duration * 30))}
        controls autoPlay={false} showVolumeControls playbackRate={rate} style={{width: '100%'}} />
    );
    render(1);
    return {rate: render, pause: () => ref?.pause()};
  },
  cleanup() {
    for (const [node, outputRoot] of outputPlayers) {
      if (!node.isConnected) {outputRoot.unmount(); outputPlayers.delete(node);}
    }
  },
};
(window as unknown as {OutputVideoPlayer: typeof outputApi}).OutputVideoPlayer = outputApi;
