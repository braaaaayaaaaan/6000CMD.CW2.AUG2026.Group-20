import { Image } from "@chakra-ui/react";

export default function PreviewImageAsset({ assetURL, assetName = "Asset preview", h, w, onError }) {
  return assetURL ? <Image src={assetURL} crossOrigin="use-credentials" referrerPolicy="no-referrer" alt={assetName} rounded="lg" height={h} width={w} objectFit="contain" onError={onError} /> : null;
}
