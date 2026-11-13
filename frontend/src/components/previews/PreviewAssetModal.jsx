"use client";

import {
  Box,
  Button,
  CloseButton,
  Dialog,
  Flex,
  Grid,
  Portal,
} from "@chakra-ui/react";
import { useState } from "react";
import { hsvaToHexa } from "@uiw/color-convert";
import PreviewAssetCardv2 from "./PreviewAssetCardv2";
import PreviewAssetMedia from "./PreviewAssetMedia";

export default function PreviewAssetModal({
  asset,
  onAssetDeleted,
  onAssetUpdated,
  onAssetUploaded,
  onVersionsLoaded,
  triggerLabel,
}) {
  const [open, setOpen] = useState(false);
  const [exposure, setExposure] = useState(1);
  const [shadowIntensity, setShadowIntensity] = useState(1);
  const [shadowSoftness, setShadowSoftness] = useState(1);
  const [hsva, setHsva] = useState({ h: 0, s: 0, v: 100, a: 1 });
  const ready = asset.processing_status === "approved";
  const modelOptions = {
    exposure,
    shadowIntensity,
    shadowSoftness,
    backgroundColor: hsvaToHexa(hsva),
  };
  return (
    <Dialog.Root
      open={open}
      onOpenChange={({ open }) => setOpen(open)}
      scrollBehavior="inside"
      placement="center"
      lazyMount
      unmountOnExit
    >
      <Dialog.Trigger asChild>
        <Button variant="surface">
          {triggerLabel || (asset.processing_status === "approved" ? "Preview" : "Details")}
        </Button>
      </Dialog.Trigger>
      <Portal>
        <Dialog.Backdrop />
        <Dialog.Positioner>
          <Dialog.Content colorPalette="gray" maxW={ready ? "6xl" : "2xl"} w="calc(100% - 2rem)" maxH="calc(100dvh - 2rem)">
            <Dialog.Header pr="12" pb="2">
              <Dialog.Title fontSize="xl" fontWeight="semibold" overflowWrap="anywhere">{asset.name}</Dialog.Title>
            </Dialog.Header>
            <Dialog.Body pt="2" pb="6">
              <Flex
                direction="column"
                gap="6"
                alignItems="flex-start"
              >
                <Grid
                  w="full"
                  templateColumns={{
                    base: "minmax(0, 1fr)",
                    xl: ready ? "minmax(0, 4fr) minmax(0, 3fr)" : "minmax(0, 1fr)",
                  }}
                  gap="6"
                >
                  {ready && <Box
                    borderWidth="1px"
                    rounded="md"
                    minW="0"
                    h={{ base: "260px", md: "420px", xl: "520px" }}
                    bg={asset.file_type === "glb" ? "transparent" : "blue.50"}
                  >
                    <PreviewAssetMedia
                      asset={asset}
                      modelOptions={modelOptions}
                    />
                  </Box>}
                  <PreviewAssetCardv2
                    asset={asset}
                    isOpen={open}
                    {...modelOptions}
                    hsva={hsva}
                    onExposureChange={setExposure}
                    onShadowIntensityChange={setShadowIntensity}
                    onShadowSoftnessChange={setShadowSoftness}
                    onHsvaChange={setHsva}
                    onAssetDeleted={onAssetDeleted}
                    onAssetUpdated={onAssetUpdated}
                    onAssetUploaded={onAssetUploaded}
                    onVersionsLoaded={onVersionsLoaded}
                  />
                </Grid>
              </Flex>
            </Dialog.Body>
            <Dialog.CloseTrigger asChild>
              <CloseButton size="sm" />
            </Dialog.CloseTrigger>
          </Dialog.Content>
        </Dialog.Positioner>
      </Portal>
    </Dialog.Root>
  );
}
