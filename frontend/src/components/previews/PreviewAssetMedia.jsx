"use client";

import { Button, Stack, Text } from "@chakra-ui/react";
import Script from "next/script";
import { useEffect, useState } from "react";
import { api, errorMessage, mediaUrl } from "@/utils/api";
import PreviewImageAsset from "./PreviewImageAsset";
import PreviewVideoAsset from "./PreviewVideoAsset";

function modelNumber(value) {
  const number = Number.parseFloat(value);
  return Number.isFinite(number) ? number : 1;
}

export default function PreviewAssetMedia({ asset, compact = false, modelOptions = {} }) {
  const [scriptError, setScriptError] = useState(false);
  const [media, setMedia] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!attempt && asset.url_expires_at * 1000 > Date.now()) return;
    const controller = new AbortController();
    api.get("/assets/" + asset.id + "/media-url/", { signal: controller.signal })
      .then(({ data }) => {
        const url = new URL(mediaUrl(data.url));
        if (attempt) url.searchParams.set("preview", String(attempt));
        if (!controller.signal.aborted) setMedia({ key: asset.url, url: url.href, expires: data.url_expires_at, error: "" });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setMedia({ key: asset.url, error: errorMessage(error, "Unable to refresh this preview.") });
      });
    return () => controller.abort();
  }, [asset.id, asset.url, asset.url_expires_at, attempt]);

  function mediaFailed() {
    if (media?.key !== asset.url || media.expires * 1000 <= Date.now()) setAttempt((value) => value + 1);
    else setMedia({ key: asset.url, error: "Unable to load this file. Retry the preview or upload a valid replacement." });
  }
  if (media?.key === asset.url && media.error) return <Stack><Text role="alert">{media.error}</Text><Button size="sm" onClick={() => setAttempt((value) => value + 1)}>Retry preview</Button></Stack>;
  const src = mediaUrl(media?.key === asset.url ? media.url : asset.url);
  if (["png", "jpg"].includes(asset.file_type)) {
    return <PreviewImageAsset assetURL={src} assetName={asset.name} h="100%" w="100%" onError={mediaFailed} />;
  }
  if (asset.file_type === "mp4") {
    return <PreviewVideoAsset key={asset.id} assetURL={src} assetName={asset.name} h="100%" w="100%" controls={!compact} onError={mediaFailed} />;
  }
  if (asset.file_type !== "glb") return <Text>Preview unavailable for this file type.</Text>;
  if (scriptError) return <Text role="alert">Unable to load the 3D viewer. Reload the page to retry.</Text>;
  return (
    <>
      <Script id="model-viewer" type="module"
        src="https://ajax.googleapis.com/ajax/libs/model-viewer/4.0.0/model-viewer.min.js"
        onError={() => setScriptError(true)} />
      <model-viewer alt={asset.name} src={src} with-credentials="" onError={mediaFailed} camera-controls="" auto-rotate={compact ? undefined : ""}
        touch-action="pan-y" environment-image="neutral"
        exposure={modelNumber(modelOptions.exposure)}
        shadow-intensity={modelNumber(modelOptions.shadowIntensity)}
        shadow-softness={modelNumber(modelOptions.shadowSoftness)}
        style={{ display: "block", width: "100%", height: "100%", borderRadius: "10px", backgroundColor: modelOptions.backgroundColor || "transparent" }} />
    </>
  );
}
