import { fileTypeFromBlob } from "file-type";

const configuredLimit = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_MB);
export const MAX_UPLOAD_MB =
  Number.isFinite(configuredLimit) && configuredLimit > 0
    ? Math.min(configuredLimit, 100)
    : 100;
export const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;
export const ACCEPTED_FILES = [".jpg", ".jpeg", ".png", ".mp4", ".glb"];

// model-viewer's URL modifier is shared by all previews. Track active signed
// model URLs together so multiple previews cannot override each other's policy.
const modelSources = new Map();

export function restrictModelResources(viewer, source) {
  const url = new URL(source, window.location.href).href;
  const release = () => {
    const remaining = modelSources.get(url) - 1;
    if (remaining > 0) modelSources.set(url, remaining);
    else modelSources.delete(url);
  };
  modelSources.set(url, (modelSources.get(url) || 0) + 1);
  try {
    viewer.mapURLs((resource) => {
      if (/^(data|blob):/i.test(resource)) return resource;
      const resolved = new URL(resource, window.location.href).href;
      if (modelSources.has(resolved)) return resolved;
      throw new Error("External model resources are prohibited.");
    });
  } catch (error) {
    release();
    throw error;
  }
  return release;
}

export function assetProcessingMessage(asset) {
  return (
    {
      pending: "Pending",
      processing: "Processing",
      approved: "Ready",
      rejected: "Failed",
      error: "Processing problem",
    }[asset.processing_status] || "Unavailable"
  );
}

export function isAssetProcessing(asset) {
  return ["pending", "processing"].includes(asset?.processing_status);
}

export function hasProcessingAssets(data) {
  return (Array.isArray(data) ? data : data?.results || []).some(isAssetProcessing);
}

export function mergeAssetResource(previous, next) {
  const before = Array.isArray(previous) ? previous : previous?.results || [];
  const byId = new Map(before.map((asset) => [asset.id, asset]));
  const merge = (asset) => {
    const old = byId.get(asset.id);
    // Each version is immutable. Keep a working preview URL during silent
    // status refreshes; a newly approved version still receives its own URL.
    if (old?.processing_status === "approved" && asset.processing_status === "approved"
      && old.processing_updated_at === asset.processing_updated_at
      && old.url && old.url_expires_at * 1000 > Date.now()) {
      return { ...asset, url: old.url, url_expires_at: old.url_expires_at };
    }
    return asset;
  };
  return Array.isArray(next) ? next.map(merge) : { ...next, results: next.results.map(merge) };
}

// User guidance depends on the outcome, not the validator's diagnostics.
export function assetProcessingDetail(asset) {
  return {
    pending: "Waiting to be checked.",
    processing: "Checking your file.",
    rejected: "Choose a different file and upload a new version.",
    error: "Processing couldn't finish. Please try again later.",
  }[asset.processing_status] || "";
}

export function uploadProgressPercent(event) {
  return Number.isFinite(event.total) && event.total > 0 && Number.isFinite(event.loaded)
    ? Math.max(0, Math.min(100, Math.floor(event.loaded / event.total * 100))) : null;
}

export function uploadErrorMessage(error) {
  if (!error.response && !error.request && !error.code) {
    const message = error.message || "";
    if (message === "Your username is unavailable. Please sign in again.") return "Please sign in again before uploading.";
    if (/^Choose a |^The selected file is empty\.|^This file could not be read\./.test(message)) return message;
  }
  if (error.response?.status === 413) return `Choose a file up to ${MAX_UPLOAD_MB} MB.`;
  if ([401, 403].includes(error.response?.status)) return "You can't upload right now. Check that you're signed in with upload access.";
  if (error.response?.status === 400) return "Check the file and asset details, then try again.";
  return "Upload failed. Check your connection and try again.";
}

export async function validateAssetFile(file) {
  if (!file) throw new Error("Choose a file to upload.");
  if (!file.size) throw new Error("The selected file is empty.");
  if (file.size > MAX_UPLOAD_BYTES)
    throw new Error("Choose a file smaller than " + MAX_UPLOAD_MB + " MB.");
  let detected;
  try {
    detected = await fileTypeFromBlob(file);
  } catch {
    throw new Error(
      "This file could not be read. Choose a valid JPG, PNG, MP4, or GLB file.",
    );
  }
  if (!detected || !["jpg", "png", "mp4", "glb"].includes(detected.ext)) {
    throw new Error("Choose a valid JPG, PNG, MP4, or GLB file.");
  }
  return { fileType: detected.ext, fileSize: file.size / (1024 * 1024) };
}
