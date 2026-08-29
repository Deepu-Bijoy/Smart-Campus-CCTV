import React from 'react';

interface VideoPlayerProps {
  src: string;
  poster?: string;
  autoplay?: boolean;
}

export const VideoPlayer: React.FC<VideoPlayerProps> = ({ src, poster, autoplay = false }) => {
  const videoUrl = src.startsWith('http') ? src : `http://127.0.0.1:8000/${src.replace(/^\/+/, '')}`;

  return (
    <div className="relative bg-black rounded-xl overflow-hidden shadow-2xl border border-dark-border aspect-video">
      <video
        src={videoUrl}
        poster={poster}
        controls
        autoPlay={autoplay}
        className="w-full h-full object-contain"
      />
    </div>
  );
};
