"use client";

import {
  Box,
  Button,
  Card,
  CloseButton,
  DataList,
  Dialog,
  Flex,
  Grid,
  IconButton,
  NumberInput,
  Portal,
  Spinner,
  Stack,
  Table,
  Tabs,
  Text,
} from "@chakra-ui/react";
import { useRef, useState } from "react";
import { RxPinBottom, RxEyeOpen } from "react-icons/rx";
import Sketch from "@uiw/react-color-sketch";
import { api, downloadAsset, errorMessage } from "@/utils/api";
import { formatDateTime } from "@/utils/dateTime";
import { hasProcessingAssets, mergeAssetResource } from "@/utils/assetFiles";
import { toaster } from "@/styles/ui/toaster";
import useBrowserSession from "@/hooks/useBrowserSession";
import useApiResource from "@/hooks/useApiResource";
import EditAssetModal from "../EditAssetModal";
import UpdateAssetModal from "../UpdateAssetModal";
import PreviewAssetMedia, { AssetProcessingStatus } from "./PreviewAssetMedia";

export default function PreviewAssetCardv2({
  asset,
  isOpen = true,
  exposure,
  shadowIntensity,
  shadowSoftness,
  hsva,
  onExposureChange,
  onShadowIntensityChange,
  onShadowSoftnessChange,
  onHsvaChange,
  onAssetDeleted,
  onAssetUpdated,
  onAssetUploaded,
  onVersionsLoaded,
}) {
  const session = useBrowserSession();
  const editable = session.ready && ["Editor", "Admin"].includes(session.group);
  const download = (asset, filename) =>
    downloadAsset(asset, filename).catch(() =>
      toaster.create({ description: "Couldn't download this file. Please try again.", type: "error" }),
    );
  const history = useApiResource(
    "/get-all-file-versions/" + encodeURIComponent(asset.code) + "/",
    {
      enabled: isOpen,
      pollWhile: hasProcessingAssets,
      mergeData: mergeAssetResource,
      onData: onVersionsLoaded,
      failureMessage: "Couldn't load version history. Please refresh to try again.",
      refreshKey: JSON.stringify([
        asset.id,
        asset.name,
        asset.description,
        asset.tags,
        asset.version_no,
        asset.processing_status,
      ]),
    },
  );
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const busy = useRef(false);
  const metadata = [
    ["Name", asset.name],
    ["Code", asset.code],
    ["Description", asset.description],
    ["Version", asset.version_no],
    ["Uploaded", formatDateTime(asset.upload_datetime)],
    ["Uploaded by", asset.uploaded_by],
    ["Status", <AssetProcessingStatus key="status" asset={(history.data || []).find((version) => version.id === asset.id) || asset} showDetail />],
    ["Format", asset.file_type],
    ["Size", Number(asset.file_size).toFixed(2) + " MB"],
  ];

  async function removeAsset() {
    if (busy.current) return;
    busy.current = true;
    setDeleting(true);
    setDeleteError("");
    try {
      await api.delete(
        "/delete-asset-by-code/" + encodeURIComponent(asset.code) + "/",
      );
      setDeleteOpen(false);
      onAssetDeleted?.(asset.code);
    } catch (error) {
      setDeleteError(errorMessage(error, "Unable to delete this asset."));
    } finally {
      busy.current = false;
      setDeleting(false);
    }
  }

  return (
    <Card.Root w="full" minW="0">
      <Card.Body display="flex" flexDirection="column" height="100%">
        <Tabs.Root
          defaultValue="metadata"
          variant="outline"
          style={{ flex: 1, display: "flex", flexDirection: "column" }}
        >
          <Tabs.List flexWrap="wrap">
            <Tabs.Trigger value="metadata">Details</Tabs.Trigger>
            {asset.file_type === "glb" && asset.processing_status === "approved" && (
              <Tabs.Trigger value="advanced">3D view</Tabs.Trigger>
            )}
            <Tabs.Trigger value="version">Version history</Tabs.Trigger>
          </Tabs.List>
          <Tabs.Content
            value="metadata"
            flexDirection="column"
            flex="1"
            _selected={{ display: "flex" }}
          >
            <DataList.Root orientation="horizontal">
              {metadata.map(([label, value]) => (
                <DataList.Item key={label}>
                  <DataList.ItemLabel>{label}</DataList.ItemLabel>
                  <DataList.ItemValue overflowWrap="anywhere" minW="0">
                    {value}
                  </DataList.ItemValue>
                </DataList.Item>
              ))}
            </DataList.Root>
            <Flex
              justifyContent="space-between"
              alignItems="center"
              gap="2"
              wrap="wrap"
              mt="auto"
              pt="4"
            >
              <Button
                variant="surface"
                disabled={asset.processing_status !== "approved"}
                onClick={() => download(asset)}
              >
                Download
              </Button>
              {editable && (
                <Flex gap="2" wrap="wrap">
                  <EditAssetModal
                    asset={asset}
                    onAssetUpdated={onAssetUpdated}
                  />
                  <UpdateAssetModal
                    asset={asset}
                    onAssetUpdated={(updated, context) => {
                      onAssetUploaded?.(updated, context);
                      history.refresh();
                    }}
                  />
                  <Dialog.Root
                    role="alertdialog"
                    placement="center"
                    open={deleteOpen}
                    onOpenChange={({ open }) => {
                      if (!busy.current) {
                        setDeleteOpen(open);
                        setDeleteError("");
                      }
                    }}
                    closeOnEscape={!deleting}
                    closeOnInteractOutside={!deleting}
                    lazyMount
                    unmountOnExit
                  >
                    <Dialog.Trigger asChild>
                      <Button variant="surface" colorPalette="red">
                        Delete
                      </Button>
                    </Dialog.Trigger>
                    <Portal>
                      <Dialog.Backdrop />
                      <Dialog.Positioner>
                        <Dialog.Content w="calc(100% - 2rem)">
                          <Dialog.Header>
                            <Dialog.Title>Are you sure?</Dialog.Title>
                          </Dialog.Header>
                          <Dialog.Body>
                            <Text>
                              This will permanently delete your asset and remove
                              all of its versions from the system!
                            </Text>
                            {deleteError && (
                              <Text role="alert" color="red.600">
                                {deleteError}
                              </Text>
                            )}
                          </Dialog.Body>
                          <Dialog.Footer>
                            <Dialog.ActionTrigger asChild>
                              <Button variant="outline" disabled={deleting}>
                                Cancel
                              </Button>
                            </Dialog.ActionTrigger>
                            <Button
                              variant="surface"
                              colorPalette="red"
                              onClick={removeAsset}
                              loading={deleting}
                              disabled={deleting}
                              loadingText="Deleting…"
                            >
                              Delete
                            </Button>
                          </Dialog.Footer>
                          <Dialog.CloseTrigger asChild>
                            <CloseButton size="sm" disabled={deleting} />
                          </Dialog.CloseTrigger>
                        </Dialog.Content>
                      </Dialog.Positioner>
                    </Portal>
                  </Dialog.Root>
                </Flex>
              )}
            </Flex>
          </Tabs.Content>
          {asset.file_type === "glb" && asset.processing_status === "approved" && (
            <Tabs.Content value="advanced">
              <Grid
                templateColumns={{ base: "minmax(0, 1fr)", md: "1fr 2fr" }}
                gap={{ base: "20px", md: "50px" }}
              >
                <Grid templateRows="repeat(3, 1fr)" gap="10px">
                  {[
                    ["Exposure", exposure, onExposureChange],
                    [
                      "Shadow Intensity",
                      shadowIntensity,
                      onShadowIntensityChange,
                    ],
                    ["Shadow Softness", shadowSoftness, onShadowSoftnessChange],
                  ].map(([label, value, change]) => (
                    <Box key={label}>
                      <Text>{label}</Text>
                      <NumberInput.Root
                        width="150px"
                        marginTop="10px"
                        min={0}
                        max={100}
                        step={0.01}
                        value={String(value)}
                        allowMouseWheel
                        onValueChange={({ value }) => change(value)}
                      >
                        <NumberInput.Control />
                        <NumberInput.Input aria-label={label} />
                      </NumberInput.Root>
                    </Box>
                  ))}
                </Grid>
                <Box minW="0">
                  <Text>Background Colour</Text>
                  <Box marginTop="10px">
                    <Sketch
                      color={hsva}
                      onChange={({ hsva }) => onHsvaChange(hsva)}
                      style={{ width: 300, maxWidth: "100%" }}
                    />
                  </Box>
                </Box>
              </Grid>
            </Tabs.Content>
          )}
          <Tabs.Content value="version">
            <Button
              variant="outline"
              size="sm"
              mb="2"
              onClick={history.refresh}
              disabled={history.loading}
            >
              Refresh versions
            </Button>
            {history.loading && (
              <Box role="status">
                <Spinner size="sm" mr="2" />
                Loading versions…
              </Box>
            )}
            {history.error && (
              <Stack>
                <Text role="alert">{history.error}</Text>
                <Button onClick={history.refresh}>Retry versions</Button>
              </Stack>
            )}
            {history.pollError && <Text role="status" fontSize="sm" color="fg.muted" mb="2">{history.pollError}</Text>}
            {!history.loading && !history.error && !history.data?.length && (
              <Text>No versions found.</Text>
            )}
            <Box overflow="auto" maxH="460px">
              <Table.Root variant="outline">
                <Table.Header>
                  <Table.Row>
                    <Table.ColumnHeader>Version No.</Table.ColumnHeader>
                    <Table.ColumnHeader>File</Table.ColumnHeader>
                    <Table.ColumnHeader>Status</Table.ColumnHeader>
                    <Table.ColumnHeader>Actions</Table.ColumnHeader>
                  </Table.Row>
                </Table.Header>
                <Table.Body>
                  {(history.data || []).map((version) => (
                    <Table.Row key={version.id}>
                      <Table.Cell>{version.version_no}</Table.Cell>
                      <Table.Cell overflowWrap="anywhere">
                        {version.name}({version.version_no}).{version.file_type}
                      </Table.Cell>
                      <Table.Cell><AssetProcessingStatus asset={version} showDetail /></Table.Cell>
                      <Table.Cell>
                        <Flex direction="row" alignItems="center" gap="8px">
                          <Dialog.Root lazyMount unmountOnExit>
                            <Dialog.Trigger asChild>
                              <IconButton
                                variant="plain"
                                disabled={
                                  version.processing_status !== "approved"
                                }
                                color="gray.400"
                                minW="0"
                                h="auto"
                                _hover={{ color: "gray.500" }}
                                aria-label={
                                  "Preview version " + version.version_no
                                }
                              >
                                <RxEyeOpen size={24} />
                              </IconButton>
                            </Dialog.Trigger>
                            <Portal>
                              <Dialog.Backdrop />
                              <Dialog.Positioner>
                                <Dialog.Content
                                  maxW="760px"
                                  w="calc(100% - 2rem)"
                                >
                                  <Dialog.Header>
                                    <Dialog.Title>
                                      {version.name}({version.version_no}).
                                      {version.file_type}
                                      <Text fontSize="sm" color="gray.500">
                                        Version {version.version_no}
                                      </Text>
                                    </Dialog.Title>
                                  </Dialog.Header>
                                  <Dialog.Body>
                                    <Box
                                      borderWidth="1px"
                                      rounded="md"
                                      bg={
                                        version.file_type === "glb"
                                          ? "transparent"
                                          : "gray.100"
                                      }
                                      h={{ base: "280px", md: "460px" }}
                                    >
                                      <PreviewAssetMedia asset={version} />
                                    </Box>
                                  </Dialog.Body>
                                  <Dialog.CloseTrigger asChild>
                                    <CloseButton size="sm" />
                                  </Dialog.CloseTrigger>
                                </Dialog.Content>
                              </Dialog.Positioner>
                            </Portal>
                          </Dialog.Root>
                          <IconButton
                            variant="plain"
                            disabled={version.processing_status !== "approved"}
                            color="gray.400"
                            minW="0"
                            h="auto"
                            _hover={{ color: "gray.500" }}
                            aria-label={
                              "Download version " + version.version_no
                            }
                            onClick={() =>
                              download(
                                version,
                                version.name +
                                  "(" +
                                  version.version_no +
                                  ")." +
                                  version.file_type,
                              )
                            }
                          >
                            <RxPinBottom size={24} />
                          </IconButton>
                        </Flex>
                      </Table.Cell>
                    </Table.Row>
                  ))}
                </Table.Body>
              </Table.Root>
            </Box>
          </Tabs.Content>
        </Tabs.Root>
      </Card.Body>
    </Card.Root>
  );
}
