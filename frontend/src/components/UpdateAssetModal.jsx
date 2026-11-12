"use client";
import UploadAssetModal from "./UploadAssetModal";

export default function UpdateAssetModal({ asset, onAssetUpdated }) {
  return <UploadAssetModal asset={asset} onAssetUploaded={onAssetUpdated} />;
}
