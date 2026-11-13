import { useRef } from "react";

export default function PreviewVideoAsset({ assetName, assetURL, h, w, controls = true, onError }) {
  const playback = useRef({ src: assetURL, time: 0, playing: false });
  function remember(event) {
    const video = event.currentTarget;
    if (video.getAttribute("src") === playback.current.src && !video.error) {
      playback.current.time = video.currentTime;
      playback.current.playing = !video.paused;
    }
  }
  function restore(event) {
    const video = event.currentTarget;
    if (playback.current.src !== assetURL) {
      video.currentTime = Math.min(playback.current.time, video.duration || 0);
      if (playback.current.playing) void video.play().catch(() => {});
      playback.current.src = assetURL;
    }
  }
  return assetURL ? (
    <video src={assetURL} crossOrigin="use-credentials" aria-label={assetName || "Asset Video"} controls={controls} playsInline preload="metadata"
      onTimeUpdate={remember} onPlay={remember} onPause={remember} onLoadedMetadata={restore} onError={onError}
      style={{ display: "block", width: w, height: h, maxWidth: "100%", objectFit: "contain", borderRadius: "10px" }} />
  ) : null;
}
