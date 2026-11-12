"use client";

import {
  Box,
  Button,
  CloseButton,
  Dialog,
  Flex,
  Grid,
  Heading,
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
}) {
  const [open, setOpen] = useState(false);
  const [exposure, setExposure] = useState(1);
  const [shadowIntensity, setShadowIntensity] = useState(1);
  const [shadowSoftness, setShadowSoftness] = useState(1);
  const [hsva, setHsva] = useState({ h: 0, s: 0, v: 100, a: 1 });
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
      size="cover"
      placement="center"
      lazyMount
      unmountOnExit
    >
      <Dialog.Trigger asChild>
        <Button variant="surface">
          {asset.processing_status === "approved" ? "Preview" : "Details"}
        </Button>
      </Dialog.Trigger>
      <Portal>
        <Dialog.Backdrop />
        <Dialog.Positioner>
          <Dialog.Content>
            <Dialog.Body>
              <Flex
                direction="column"
                gap="10px"
                padding="10px"
                alignItems="flex-start"
              >
                <Dialog.Title asChild>
                  <Heading
                    size="2xl"
                    fontWeight="bold"
                    marginTop="20px"
                    overflowWrap="anywhere"
                  >
                    {asset.name}
                  </Heading>
                </Dialog.Title>
                <Grid
                  w="full"
                  templateColumns={{
                    base: "minmax(0, 1fr)",
                    xl: "minmax(0, 4fr) minmax(0, 3fr)",
                  }}
                  gap="20px"
                >
                  <Box
                    borderWidth="1px"
                    rounded="md"
                    minW="0"
                    h={{ base: "300px", md: "480px", xl: "580px" }}
                    bg={asset.file_type === "glb" ? "transparent" : "gray.100"}
                  >
                    <PreviewAssetMedia
                      asset={asset}
                      modelOptions={modelOptions}
                    />
                  </Box>
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
