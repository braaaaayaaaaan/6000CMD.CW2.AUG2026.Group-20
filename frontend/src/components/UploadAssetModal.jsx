"use client";

import {
  Box,
  Button,
  CloseButton,
  Dialog,
  Field,
  FileUpload,
  Icon,
  Input,
  Portal,
  Progress,
  Stack,
  Text,
  Textarea,
} from "@chakra-ui/react";
import { useEffect, useRef, useState } from "react";
import { MdCloudUpload } from "react-icons/md";
import { LuUpload } from "react-icons/lu";
import { api } from "@/utils/api";
import {
  ACCEPTED_FILES,
  MAX_UPLOAD_BYTES,
  MAX_UPLOAD_MB,
  validateAssetFile,
  uploadErrorMessage,
  uploadProgressPercent,
  isAssetProcessing,
} from "@/utils/assetFiles";
import useBrowserSession from "@/hooks/useBrowserSession";
import useTags from "@/hooks/useTags";
import useApiResource from "@/hooks/useApiResource";
import AssetTag from "./AssetTag";
import { toaster, notifyUploadStatus, uploadToast } from "@/styles/ui/toaster";

// Follow only uploads started in this mounted workspace when their management
// card is off-screen. Visible cards already share the collection's polling.
const keepWatchingUpload = (asset) => !asset || isAssetProcessing(asset);
export function UploadStatusTracker({ assetId, enabled, onStatus }) {
  useApiResource("/assets/" + encodeURIComponent(assetId) + "/", {
    enabled,
    pollWhile: keepWatchingUpload,
    onData: (asset) => onStatus([asset]),
    failureMessage: "Status is unavailable. Refresh Manage Uploads to check again.",
  });
  return null;
}

export default function UploadAssetModal({ asset, onAssetUploaded, defaultOpen = false }) {
  const session = useBrowserSession();
  const { tags, loading, error, refresh } = useTags();
  const [open, setOpen] = useState(defaultOpen);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState(null);
  const [selectedTags, setSelectedTags] = useState([]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [progress, setProgress] = useState(null);
  const busy = useRef(false);
  const request = useRef(null);
  const activeToast = useRef(null);
  useEffect(() => () => {
    request.current?.abort();
    if (activeToast.current) toaster.dismiss(activeToast.current);
  }, []);

  function changeOpen({ open: next }) {
    if (busy.current) return;
    if (next) {
      setName("");
      setDescription("");
      setFile(null);
      setSelectedTags([]);
      setSaveError("");
      setProgress(null);
    }
    setOpen(next);
  }

  async function submit(event) {
    event.preventDefault();
    if (busy.current) return;
    busy.current = true;
    setSaving(true);
    setSaveError("");
    setProgress(null);
    const controller = new AbortController();
    request.current = controller;
    const toastId = toaster.create({ title: file?.name, description: "Uploading File…", type: "loading" });
    activeToast.current = toastId;
    let uploaded = null;
    try {
      await validateAssetFile(file);
      if (!session.username)
        throw new Error("Your username is unavailable. Please sign in again.");
      const data = new FormData();
      data.append("name", asset ? asset.name : name.trim());
      data.append(
        "description",
        asset ? asset.description : description.trim(),
      );
      data.append("url", file);
      (asset ? asset.tags : selectedTags).forEach((id) =>
        data.append("tags", id),
      );
      if (asset) {
        data.append("code", asset.code);
      }
      const response = await api.post("/assets/", data, {
        signal: controller.signal,
        onUploadProgress: (event) => {
          if (!controller.signal.aborted) setProgress(uploadProgressPercent(event));
        },
      });
      uploaded = response.data;
    } catch (error) {
      if (!controller.signal.aborted) {
        setSaveError(uploadErrorMessage(error));
        uploadToast(toastId, { description: "Upload failed. Please try again.", type: "error", duration: 6500 });
      }
    } finally {
      busy.current = false;
      setSaving(false);
      request.current = null;
      activeToast.current = null;
    }
    if (uploaded && !controller.signal.aborted) {
      const context = { toastId, previousApproved: asset?.processing_status === "approved" };
      notifyUploadStatus(uploaded, context);
      setOpen(false);
      onAssetUploaded?.(uploaded, context);
    }
  }

  return (
    <Dialog.Root
      open={open}
      onOpenChange={changeOpen}
      closeOnEscape={!saving}
      closeOnInteractOutside={!saving}
      placement="center"
      scrollBehavior="inside"
      lazyMount
      unmountOnExit
    >
      <Dialog.Trigger asChild>
        <Button
          variant={asset ? "surface" : "solid"}
          size={asset ? "md" : "sm"}
          bg={asset ? undefined : "blue.700"}
          color={asset ? undefined : "white"}
        >
          {!asset && <MdCloudUpload />}
          {asset ? "New Version" : "Upload A File"}
        </Button>
      </Dialog.Trigger>
      <Portal>
        <Dialog.Backdrop />
        <Dialog.Positioner>
          <Dialog.Content
            as="form"
            onSubmit={submit}
            maxW="xl"
            w="calc(100% - 2rem)"
            maxH="calc(100dvh - 2rem)"
          >
            <Dialog.Header pb="2" pr="12">
              <Dialog.Title>
                {asset ? "Upload A New Version" : "Upload A File"}
              </Dialog.Title>
            </Dialog.Header>
            <Dialog.Body pt="2" pb="6">
              <Stack gap="5">
                <Text fontSize="sm">
                  We&apos;ll check your file before it appears in the library.
                  {asset && " Earlier ready versions stay available while we check the new one."}
                </Text>
                <FileUpload.Root
                  maxW="lg"
                  alignItems="stretch"
                  maxFiles={1}
                  accept={ACCEPTED_FILES}
                  maxFileSize={MAX_UPLOAD_BYTES}
                  acceptedFiles={file ? [file] : []}
                  disabled={saving}
                  onFileChange={({ acceptedFiles }) => {
                    setFile(acceptedFiles[0] || null);
                    setSaveError("");
                  }}
                  onFileReject={() =>
                    setSaveError(
                      "Choose a JPG, PNG, MP4, or GLB file up to " +
                        MAX_UPLOAD_MB +
                        " MB.",
                    )
                  }
                >
                  <FileUpload.Label>File</FileUpload.Label>
                  <FileUpload.HiddenInput />
                  <FileUpload.Dropzone borderColor={file ? "blue.500" : undefined}
                    _hover={{ borderColor: "blue.500" }}
                    _focusVisible={{ outline: "2px solid", outlineColor: "blue.500" }}
                    css={{ '&[data-dragging]': { borderColor: 'var(--chakra-colors-blue-500)' }, '@media (prefers-reduced-motion: no-preference)': { transition: 'border-color 150ms ease' } }}>
                    <Icon size="md" color="fg.muted">
                      {asset ? <LuUpload /> : <MdCloudUpload />}
                    </Icon>
                    <FileUpload.DropzoneContent textAlign="center">
                      <Box>
                        {asset ? (
                          "Drop your new file here."
                        ) : (
                          <>
                            Drop a file here or click to browse.
                            <br />
                            JPG, JPEG, PNG, MP4 and GLB.
                          </>
                        )}
                      </Box>
                      <Text fontSize="sm" color="fg.muted">One file · Up to {MAX_UPLOAD_MB} MB</Text>
                    </FileUpload.DropzoneContent>
                  </FileUpload.Dropzone>
                  <FileUpload.List />
                </FileUpload.Root>
                {!asset && (
                  <>
                    <Field.Root>
                      <Field.Label>Name</Field.Label>
                      <Input
                        placeholder="Give This Asset A Clear Name"
                        value={name}
                        onChange={(event) => setName(event.target.value)}
                        required
                        maxLength={200}
                        disabled={saving}
                      />
                    </Field.Root>
                    <Field.Root>
                      <Field.Label>Description</Field.Label>
                      <Textarea
                        placeholder="Add A Short Description To Help People Find This File"
                        value={description}
                        onChange={(event) => setDescription(event.target.value)}
                        required
                        disabled={saving}
                      />
                    </Field.Root>
                  </>
                )}

                {saving && (
                  <Stack gap="2" role="status" aria-live="polite">
                    <Text fontSize="sm">
                      {progress === 100 ? "Finishing Upload… Waiting For The Server." : "Uploading File…"}
                      {progress !== null && ` ${progress}%`}
                    </Text>
                    <Progress.Root value={progress} size="xs" colorPalette="blue" aria-label="File Upload Progress">
                      <Progress.Track rounded="full"><Progress.Range
                        css={{ '@media (prefers-reduced-motion: no-preference)': { transition: 'width 150ms ease' }, '@media (prefers-reduced-motion: reduce)': { animation: 'none !important' } }}
                      /></Progress.Track>
                    </Progress.Root>
                  </Stack>
                )}
                {!asset && (
                  <Field.Root>
                    <Field.Label>Tags (Optional)</Field.Label>
                    <AssetTag
                      tags={tags}
                      loading={loading}
                      error={error}
                      onRetry={refresh}
                      disabled={saving}
                      selectedTags={selectedTags}
                      onSelectTag={(id) =>
                        setSelectedTags((previous) =>
                          previous.includes(id)
                            ? previous.filter((item) => item !== id)
                            : [...previous, id],
                        )
                      }
                    />
                  </Field.Root>
                )}
                {saveError && (
                  <Text role="alert" color="red.600">
                    {saveError}
                  </Text>
                )}
              </Stack>
            </Dialog.Body>
            <Dialog.Footer borderTopWidth="1px" gap="3">
              <Dialog.ActionTrigger asChild>
                <Button
                  type="button"
                  variant="outline"
                  disabled={saving}
                >
                  Cancel
                </Button>
              </Dialog.ActionTrigger>
              <Button
                type="submit"
                variant="solid"
                bg="blue.700"
                color="white"
                loading={saving}
                loadingText="Uploading…"
                minW="28"
                disabled={saving || !file}
              >
                Upload
              </Button>
            </Dialog.Footer>
            <Dialog.CloseTrigger asChild>
              <CloseButton type="button" size="sm" disabled={saving} />
            </Dialog.CloseTrigger>
          </Dialog.Content>
        </Dialog.Positioner>
      </Portal>
    </Dialog.Root>
  );
}
