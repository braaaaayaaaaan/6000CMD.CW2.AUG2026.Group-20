"use client";

import { Badge, Button, Spinner, Stack, Text } from "@chakra-ui/react";
import { LuCircleCheck, LuCircleX, LuCircleAlert, LuClock3 } from "react-icons/lu";
import Script from "next/script";
import { useEffect, useState } from "react";
import { api, mediaUrl } from "@/utils/api";
import { assetProcessingDetail, assetProcessingMessage, isAssetProcessing, restrictModelResources } from "@/utils/assetFiles";
import PreviewImageAsset from "./PreviewImageAsset";
import PreviewVideoAsset from "./PreviewVideoAsset";

function modelNumber(value) {
  const number = Number.parseFloat(value);
  return Number.isFinite(number) ? number : 1;
}

export function AssetProcessingStatus({ asset, showDetail = false }) {
  const pending = isAssetProcessing(asset);
  const approved = asset.processing_status === "approved";
  const rejected = asset.processing_status === "rejected";
  const checking = asset.processing_status === "processing";
  const StatusIcon = pending ? LuClock3 : approved ? LuCircleCheck : rejected ? LuCircleX : LuCircleAlert;
  return (
    <Stack gap="2" align="start" minW="0">
      <Badge colorPalette={pending ? "blue" : approved ? "green" : rejected ? "red" : "orange"}
        rounded="full" px="2.5" py="1" role="status" aria-live="polite"
        css={{ '@media (prefers-reduced-motion: no-preference)': { transition: 'background-color 150ms ease, color 150ms ease' } }}>
        {checking ? <Spinner size="xs" css={{ '@media (prefers-reduced-motion: reduce)': { animation: 'none' } }} /> : <StatusIcon aria-hidden="true" />}
        {assetProcessingMessage(asset)}
      </Badge>
      {showDetail && assetProcessingDetail(asset) && <Text fontSize="sm" color="fg.muted" overflowWrap="anywhere">{assetProcessingDetail(asset)}</Text>}
    </Stack>
  );
}

export default function PreviewAssetMedia({
  asset,
  compact = false,
  modelOptions = {},
}) {
  const [scriptError, setScriptError] = useState(false);
  const [media, setMedia] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [modelSource, setModelSource] = useState("");
  const approved = asset.processing_status === "approved";
  const src = mediaUrl(media?.key === asset.url ? media.url : asset.url);
  useEffect(() => {
    if (!approved) return;
    if (!attempt && asset.url && asset.url_expires_at * 1000 > Date.now()) return;
    const controller = new AbortController();
    api
      .get("/assets/" + asset.id + "/media-url/", { signal: controller.signal })
      .then(({ data }) => {
        if (!data.url) throw new Error("No media link available");
        const url = new URL(mediaUrl(data.url));
        if (attempt) url.searchParams.set("preview", String(attempt));
        if (!controller.signal.aborted)
          setMedia({
            key: asset.url,
            url: url.href,
            expires: data.url_expires_at,
            error: "",
          });
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setMedia({
            key: asset.url,
            error: "Preview unavailable. You can still try downloading this file.",
          });
      });
    return () => controller.abort();
  }, [asset.id, asset.url, asset.url_expires_at, attempt, approved]);

  useEffect(() => {
    if (!approved || asset.file_type !== "glb" || !src) return;
    let active = true;
    let release;
    customElements.whenDefined("model-viewer").then(() => {
      if (!active) return;
      release = restrictModelResources(customElements.get("model-viewer"), src);
      setModelSource(src);
    }).catch(() => {
      if (active) setScriptError(true);
    });
    return () => {
      active = false;
      release?.();
    };
  }, [approved, asset.file_type, src]);

  function mediaFailed() {
    if (media?.key !== asset.url || media.expires * 1000 <= Date.now())
      setAttempt((value) => value + 1);
    else
      setMedia({
        key: asset.url,
        error:
          "Preview unavailable. You can still download this file.",
      });
  }
  if (!approved)
    return (
      <Stack p="3" h="full" justify="center" bg={compact ? "bg.muted" : undefined} rounded="md">
        {compact ? <Text fontSize="sm" color="fg.muted" textAlign="center">
          {isAssetProcessing(asset) ? "Preview available when ready" : "Preview unavailable"}
        </Text> : <AssetProcessingStatus asset={asset} showDetail />}
      </Stack>
    );
  if (media?.key === asset.url && media.error)
    return (
      <Stack>
        <Text role="alert">{media.error}</Text>
        <Button size="sm" onClick={() => setAttempt((value) => value + 1)}>
          Retry preview
        </Button>
      </Stack>
    );
  if (!src)
    return <Stack align="center" justify="center" h="full" role="status"><Spinner size="sm" /><Text fontSize="sm">Loading preview…</Text></Stack>;
  if (["png", "jpg"].includes(asset.file_type)) {
    return (
      <PreviewImageAsset
        assetURL={src}
        assetName={asset.name}
        h="100%"
        w="100%"
        onError={mediaFailed}
      />
    );
  }
  if (asset.file_type === "mp4") {
    return (
      <PreviewVideoAsset
        key={asset.id}
        assetURL={src}
        assetName={asset.name}
        h="100%"
        w="100%"
        controls={!compact}
        onError={mediaFailed}
      />
    );
  }
  if (asset.file_type !== "glb")
    return <Text>Preview unavailable for this file type.</Text>;
  if (scriptError)
    return (
      <Text role="alert">
        Preview unavailable. You can still download this file.
      </Text>
    );
  return (
    <>
      <Script
        id="model-viewer"
        type="module"
        src="https://ajax.googleapis.com/ajax/libs/model-viewer/4.0.0/model-viewer.min.js"
        onError={() => setScriptError(true)}
      />
      {modelSource === src && <model-viewer
        alt={asset.name}
        src={src}
        with-credentials=""
        onError={mediaFailed}
        camera-controls=""
        auto-rotate={compact ? undefined : ""}
        touch-action="pan-y"
        environment-image="neutral"
        exposure={modelNumber(modelOptions.exposure)}
        shadow-intensity={modelNumber(modelOptions.shadowIntensity)}
        shadow-softness={modelNumber(modelOptions.shadowSoftness)}
        style={{
          display: "block",
          width: "100%",
          height: "100%",
          borderRadius: "10px",
          backgroundColor: modelOptions.backgroundColor || "transparent",
        }}
      />}
    </>
  );
}
