"use client";

import { Box, Button, CloseButton, Dialog, Field, FileUpload, Icon, Input, Portal, Stack, Text, Textarea } from "@chakra-ui/react";
import { useRef, useState } from "react";
import { MdCloudUpload } from "react-icons/md";
import { api, errorMessage } from "@/utils/api";
import { ACCEPTED_FILES, MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, validateAssetFile } from "@/utils/assetFiles";
import useBrowserSession from "@/hooks/useBrowserSession";
import useTags from "@/hooks/useTags";
import AssetTag from "./AssetTag";
import { toaster } from "@/styles/ui/toaster";

export default function UploadAssetModal({ asset, onAssetUploaded }) {
  const session = useBrowserSession();
  const { tags, loading, error, refresh } = useTags();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState(null);
  const [selectedTags, setSelectedTags] = useState([]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const busy = useRef(false);

  function changeOpen({ open: next }) {
    if (busy.current) return;
    if (next) {
      setName(""); setDescription(""); setFile(null); setSelectedTags([]); setSaveError("");
    }
    setOpen(next);
  }

  async function submit(event) {
    event.preventDefault();
    if (busy.current) return;
    busy.current = true;
    setSaving(true);
    setSaveError("");
    try {
      await validateAssetFile(file);
      if (!session.username) throw new Error("Your username is unavailable. Please sign in again.");
      const data = new FormData();
      data.append("name", asset ? asset.name : name.trim());
      data.append("description", asset ? asset.description : description.trim());
      data.append("url", file);
      (asset ? asset.tags : selectedTags).forEach((id) => data.append("tags", id));
      if (asset) {
        data.append("code", asset.code);
      }
      const response = await api.post("/assets/", data);
      setOpen(false);
      onAssetUploaded?.(response.data);
      toaster.create({ description: asset ? "New version uploaded." : "Asset uploaded.", type: "success" });
    } catch (error) {
      setSaveError(errorMessage(error, "Unable to upload this file. Please try again."));
    } finally {
      busy.current = false;
      setSaving(false);
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={changeOpen} closeOnEscape={!saving} closeOnInteractOutside={!saving} lazyMount unmountOnExit>
      <Dialog.Trigger asChild>
        <Button variant={asset ? "surface" : "solid"} colorPalette="blue" size="sm">
          <MdCloudUpload />{asset ? "Update" : "Upload Asset"}
        </Button>
      </Dialog.Trigger>
      <Portal>
        <Dialog.Backdrop />
        <Dialog.Positioner>
          <Dialog.Content as="form" onSubmit={submit} maxW="lg" w="calc(100% - 2rem)">
            <Dialog.Header><Dialog.Title>{asset ? "Upload New Version" : "Upload New Asset"}</Dialog.Title></Dialog.Header>
            <Dialog.Body>
              <Stack gap="4">
                {!asset && <>
                  <Field.Root required>
                    <Field.Label>Name</Field.Label>
                    <Input value={name} onChange={(event) => setName(event.target.value)} required maxLength={200} disabled={saving} />
                  </Field.Root>
                  <Field.Root required>
                    <Field.Label>Description</Field.Label>
                    <Textarea value={description} onChange={(event) => setDescription(event.target.value)} required disabled={saving} />
                  </Field.Root>
                </>}
                <FileUpload.Root maxFiles={1} accept={ACCEPTED_FILES} maxFileSize={MAX_UPLOAD_BYTES}
                  acceptedFiles={file ? [file] : []} disabled={saving}
                  onFileChange={({ acceptedFiles }) => { setFile(acceptedFiles[0] || null); setSaveError(""); }}
                  onFileReject={() => setSaveError("Choose a JPG, PNG, MP4, or GLB file up to " + MAX_UPLOAD_MB + " MB.")}>
                  <FileUpload.Label>Asset file</FileUpload.Label>
                  <FileUpload.HiddenInput />
                  <FileUpload.Dropzone>
                    <Icon size="md"><MdCloudUpload /></Icon>
                    <FileUpload.DropzoneContent>
                      <Box>Drop a file here or click to browse.</Box>
                      <Text fontSize="sm">JPG, PNG, MP4, GLB · up to {MAX_UPLOAD_MB} MB</Text>
                    </FileUpload.DropzoneContent>
                  </FileUpload.Dropzone>
                  <FileUpload.List />
                </FileUpload.Root>
                {!asset && <Field.Root>
                  <Field.Label>Tags</Field.Label>
                  <AssetTag tags={tags} loading={loading} error={error} onRetry={refresh} disabled={saving}
                    selectedTags={selectedTags} onSelectTag={(id) => setSelectedTags((previous) =>
                      previous.includes(id) ? previous.filter((item) => item !== id) : [...previous, id])} />
                </Field.Root>}
                {saveError && <Text role="alert" color="red.600">{saveError}</Text>}
              </Stack>
            </Dialog.Body>
            <Dialog.Footer>
              <Dialog.ActionTrigger asChild><Button type="button" variant="outline" disabled={saving}>Cancel</Button></Dialog.ActionTrigger>
              <Button type="submit" loading={saving} loadingText="Uploading…" disabled={saving}>Upload</Button>
            </Dialog.Footer>
            <Dialog.CloseTrigger asChild><CloseButton type="button" disabled={saving} /></Dialog.CloseTrigger>
          </Dialog.Content>
        </Dialog.Positioner>
      </Portal>
    </Dialog.Root>
  );
}
