"use client";

import { Box, Button, Card, CloseButton, DataList, Dialog, Flex, Grid, NumberInput, Portal, Spinner, Stack, Table, Tabs, Text } from "@chakra-ui/react";
import { useRef, useState } from "react";
import Sketch from "@uiw/react-color-sketch";
import { api, downloadAsset, errorMessage } from "@/utils/api";
import { formatDateTime } from "@/utils/dateTime";
import { toaster } from "@/styles/ui/toaster";
import useBrowserSession from "@/hooks/useBrowserSession";
import useApiResource from "@/hooks/useApiResource";
import EditAssetModal from "../EditAssetModal";
import UpdateAssetModal from "../UpdateAssetModal";
import PreviewAssetMedia from "./PreviewAssetMedia";

export default function PreviewAssetCardv2({
  asset, isOpen = true, exposure, shadowIntensity, shadowSoftness, hsva,
  onExposureChange, onShadowIntensityChange, onShadowSoftnessChange, onHsvaChange,
  onAssetDeleted, onAssetUpdated,
}) {
  const session = useBrowserSession();
  const editable = session.ready && ["Editor", "Admin"].includes(session.group);
  const download = (asset, filename) => downloadAsset(asset, filename).catch((error) => toaster.create({ description: errorMessage(error), type: "error" }));
  const history = useApiResource("/get-all-file-versions/" + encodeURIComponent(asset.code) + "/", {
    enabled: isOpen, refreshKey: JSON.stringify([asset.id, asset.name, asset.description, asset.tags, asset.version_no]),
  });
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const busy = useRef(false);
  const metadata = [
    ["Name", asset.name], ["Code", asset.code], ["Description", asset.description],
    ["Version", asset.version_no], ["Uploaded", formatDateTime(asset.upload_datetime)], ["Uploaded By", asset.uploaded_by],
    ["File Type", asset.file_type], ["File Size", Number(asset.file_size).toFixed(2) + " MB"],
  ];

  async function removeAsset() {
    if (busy.current) return;
    busy.current = true; setDeleting(true); setDeleteError("");
    try {
      await api.delete("/delete-asset-by-code/" + encodeURIComponent(asset.code) + "/");
      setDeleteOpen(false);
      onAssetDeleted?.(asset.code);
    } catch (error) {
      setDeleteError(errorMessage(error, "Unable to delete this asset."));
    } finally {
      busy.current = false; setDeleting(false);
    }
  }

  return (
    <Card.Root w="full" minW="0" minH={{ xl: "580px" }}>
      <Card.Body>
        <Tabs.Root defaultValue="metadata">
          <Tabs.List flexWrap="wrap">
            <Tabs.Trigger value="metadata">Metadata</Tabs.Trigger>
            {asset.file_type === "glb" && <Tabs.Trigger value="advanced">Advanced Settings</Tabs.Trigger>}
            <Tabs.Trigger value="version">Version Control</Tabs.Trigger>
          </Tabs.List>
          <Tabs.Content value="metadata">
            <DataList.Root orientation="horizontal">
              {metadata.map(([label, value]) => (
                <DataList.Item key={label}>
                  <DataList.ItemLabel>{label}</DataList.ItemLabel>
                  <DataList.ItemValue overflowWrap="anywhere" minW="0">{value}</DataList.ItemValue>
                </DataList.Item>
              ))}
            </DataList.Root>
            <Flex gap="2" wrap="wrap" mt="6">
              <Button size="sm" variant="surface" onClick={() => download(asset)}>Download</Button>
              {editable && <>
                <EditAssetModal asset={asset} onAssetUpdated={onAssetUpdated} />
                <UpdateAssetModal asset={asset} onAssetUpdated={onAssetUpdated} />
                <Dialog.Root role="alertdialog" open={deleteOpen}
                  onOpenChange={({ open }) => { if (!busy.current) { setDeleteOpen(open); setDeleteError(""); } }}
                  closeOnEscape={!deleting} closeOnInteractOutside={!deleting} lazyMount unmountOnExit>
                  <Dialog.Trigger asChild><Button size="sm" variant="surface" colorPalette="red">Delete</Button></Dialog.Trigger>
                  <Portal>
                    <Dialog.Backdrop /><Dialog.Positioner>
                      <Dialog.Content w="calc(100% - 2rem)">
                        <Dialog.Header><Dialog.Title>Delete this asset?</Dialog.Title></Dialog.Header>
                        <Dialog.Body>
                          <Text>This permanently deletes this asset and all of its versions.</Text>
                          {deleteError && <Text role="alert" color="red.600">{deleteError}</Text>}
                        </Dialog.Body>
                        <Dialog.Footer>
                          <Dialog.ActionTrigger asChild><Button variant="outline" disabled={deleting}>Cancel</Button></Dialog.ActionTrigger>
                          <Button colorPalette="red" onClick={removeAsset} loading={deleting} disabled={deleting} loadingText="Deleting…">Delete</Button>
                        </Dialog.Footer>
                        <Dialog.CloseTrigger asChild><CloseButton disabled={deleting} /></Dialog.CloseTrigger>
                      </Dialog.Content>
                    </Dialog.Positioner>
                  </Portal>
                </Dialog.Root>
              </>}
            </Flex>
          </Tabs.Content>
          {asset.file_type === "glb" && <Tabs.Content value="advanced">
            <Stack gap="5">
              <Grid templateColumns={{ base: "1fr", md: "repeat(3, minmax(0, 1fr))" }} gap="3">
                {[
                  ["Exposure", exposure, onExposureChange],
                  ["Shadow intensity", shadowIntensity, onShadowIntensityChange],
                  ["Shadow softness", shadowSoftness, onShadowSoftnessChange],
                ].map(([label, value, change]) => (
                  <Box key={label}>
                    <Text mb="2">{label}</Text>
                    <NumberInput.Root min={0} max={100} step={0.01} value={String(value)} allowMouseWheel
                      onValueChange={({ value }) => change(value)}>
                      <NumberInput.Control /><NumberInput.Input aria-label={label} />
                    </NumberInput.Root>
                  </Box>
                ))}
              </Grid>
              <Box><Text mb="2">Background colour</Text><Sketch color={hsva} onChange={({ hsva }) => onHsvaChange(hsva)} style={{ width: "100%", maxWidth: 300 }} /></Box>
            </Stack>
          </Tabs.Content>}
          <Tabs.Content value="version">
            {history.loading && <Box role="status"><Spinner size="sm" mr="2" />Loading versions…</Box>}
            {history.error && <Stack><Text role="alert">{history.error}</Text><Button onClick={history.refresh}>Retry versions</Button></Stack>}
            {!history.loading && !history.error && !history.data?.length && <Text>No versions found.</Text>}
            <Box overflowX="auto">
              <Table.Root size="sm">
                <Table.Header><Table.Row><Table.ColumnHeader>Version</Table.ColumnHeader><Table.ColumnHeader>File</Table.ColumnHeader><Table.ColumnHeader>Actions</Table.ColumnHeader></Table.Row></Table.Header>
                <Table.Body>
                  {(history.data || []).map((version) => (
                    <Table.Row key={version.id}>
                      <Table.Cell>{version.version_no}</Table.Cell>
                      <Table.Cell overflowWrap="anywhere">{version.name}.{version.file_type}</Table.Cell>
                      <Table.Cell>
                        <Flex gap="2" wrap="wrap">
                          <Dialog.Root lazyMount unmountOnExit>
                            <Dialog.Trigger asChild><Button size="xs" variant="outline" aria-label={"Preview version " + version.version_no}>Preview</Button></Dialog.Trigger>
                            <Portal><Dialog.Backdrop /><Dialog.Positioner>
                              <Dialog.Content maxW="3xl" w="calc(100% - 2rem)">
                                <Dialog.Header><Dialog.Title>{version.name} · Version {version.version_no}</Dialog.Title></Dialog.Header>
                                <Dialog.Body><Box h={{ base: "280px", md: "460px" }}><PreviewAssetMedia asset={version} /></Box></Dialog.Body>
                                <Dialog.CloseTrigger asChild><CloseButton /></Dialog.CloseTrigger>
                              </Dialog.Content>
                            </Dialog.Positioner></Portal>
                          </Dialog.Root>
                          <Button size="xs" variant="outline" aria-label={"Download version " + version.version_no}
                            onClick={() => download(version, version.name + "(" + version.version_no + ")." + version.file_type)}>Download</Button>
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
