import { fileTypeFromBlob } from "file-type";

const configuredLimit = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_MB);
export const MAX_UPLOAD_MB = Number.isFinite(configuredLimit) && configuredLimit > 0 ? configuredLimit : 100;
export const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;
export const ACCEPTED_FILES = [".jpg", ".jpeg", ".png", ".mp4", ".glb"];

export async function validateAssetFile(file) {
  if (!file) throw new Error("Choose a file to upload.");
  if (!file.size) throw new Error("The selected file is empty.");
  if (file.size > MAX_UPLOAD_BYTES) throw new Error("Choose a file smaller than " + MAX_UPLOAD_MB + " MB.");
  let detected;
  try {
    detected = await fileTypeFromBlob(file);
  } catch {
    throw new Error("This file could not be read. Choose a valid JPG, PNG, MP4, or GLB file.");
  }
  if (!detected || !["jpg", "png", "mp4", "glb"].includes(detected.ext)) {
    throw new Error("Choose a valid JPG, PNG, MP4, or GLB file.");
  }
  return { fileType: detected.ext, fileSize: file.size / (1024 * 1024) };
}
