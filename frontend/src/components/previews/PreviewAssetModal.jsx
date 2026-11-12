"use client";

import { Box, Button, CloseButton, Dialog, Grid, Portal } from "@chakra-ui/react";
import { useState } from "react";
import { hsvaToHexa } from "@uiw/color-convert";
import PreviewAssetCardv2 from "./PreviewAssetCardv2";
import PreviewAssetMedia from "./PreviewAssetMedia";

export default function PreviewAssetModal({ asset, onAssetDeleted, onAssetUpdated }) {
  const [open, setOpen] = useState(false);
  const [exposure, setExposure] = useState(1);
  const [shadowIntensity, setShadowIntensity] = useState(1);
  const [shadowSoftness, setShadowSoftness] = useState(1);
  const [hsva, setHsva] = useState({ h: 0, s: 0, v: 100, a: 1 });
  const modelOptions = { exposure, shadowIntensity, shadowSoftness, backgroundColor: hsvaToHexa(hsva) };
  return (
    <Dialog.Root open={open} onOpenChange={({ open }) => setOpen(open)} size="cover" placement="center" lazyMount unmountOnExit>
      <Dialog.Trigger asChild><Button variant="surface" size="sm">Preview</Button></Dialog.Trigger>
      <Portal>
        <Dialog.Backdrop /><Dialog.Positioner>
          <Dialog.Content maxW="1600px" w="calc(100% - 2rem)">
            <Dialog.Header><Dialog.Title overflowWrap="anywhere">{asset.name}</Dialog.Title></Dialog.Header>
            <Dialog.Body pb="6">
              <Grid templateColumns={{ base: "minmax(0, 1fr)", xl: "minmax(0, 4fr) minmax(0, 3fr)" }} gap="5">
                <Box borderWidth="1px" rounded="lg" minW="0" h={{ base: "300px", md: "480px", xl: "580px" }}>
                  <PreviewAssetMedia asset={asset} modelOptions={modelOptions} />
                </Box>
                <PreviewAssetCardv2 asset={asset} isOpen={open} {...modelOptions}
                  hsva={hsva} onExposureChange={setExposure}
                  onShadowIntensityChange={setShadowIntensity} onShadowSoftnessChange={setShadowSoftness}
                  onHsvaChange={setHsva} onAssetDeleted={onAssetDeleted} onAssetUpdated={onAssetUpdated} />
              </Grid>
            </Dialog.Body>
            <Dialog.CloseTrigger asChild><CloseButton /></Dialog.CloseTrigger>
          </Dialog.Content>
        </Dialog.Positioner>
      </Portal>
    </Dialog.Root>
  );
}
