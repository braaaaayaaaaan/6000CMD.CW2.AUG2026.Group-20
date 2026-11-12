import { Image } from "@chakra-ui/react";

export default function PreviewImageAsset({ assetURL, assetName = "Asset preview", h, w, onError }) {
  return <Image src={assetURL} alt={assetName} rounded="lg" height={h} width={w} objectFit="contain" onError={onError} />;
}
