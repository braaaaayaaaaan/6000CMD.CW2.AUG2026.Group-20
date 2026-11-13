"use client";

import {
  Button,
  CloseButton,
  Dialog,
  Field,
  Input,
  Portal,
  Stack,
  Text,
  Textarea,
} from "@chakra-ui/react";
import { toaster } from "../styles/ui/toaster";
import { useRef, useState } from "react";
import { api } from "@/utils/api";
import useTags from "../hooks/useTags";
import AssetTag from "./AssetTag.jsx";

export default function EditAssetModal({ asset, onAssetUpdated }) {

  // State variables to store uploaded asset details
  const [name, setName] = useState(asset.name);
  const [description, setDescription] = useState(asset.description);
  const [open, setOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const savingRef = useRef(false);

  // state variable to store tag
  const { tags, loading, error, refresh } = useTags();
  const [selectedTag, setSelectedTag] = useState(asset.tags || []);

  function handleOpenChange({ open: nextOpen }) {
    if (savingRef.current) return;
    if (nextOpen) {
      setName(asset.name);
      setDescription(asset.description);
      setSelectedTag(asset.tags || []);
      setSaveError("");
    }
    setOpen(nextOpen);
  }

  //called by AssetTag (onSelectTag) and will return the array of tag ids
  async function handleTagSelect(tag_id) {
    if (savingRef.current) return;
    setSelectedTag((prevSelected) => {
      if (prevSelected.includes(tag_id)) {
        // if already selected, remove it
        return prevSelected.filter((id) => id !== tag_id);
      } else {
        // otherwise add it
        return [...prevSelected, tag_id];
      }
    });
  }

  async function handleAssetFileEdit(event) {
    event.preventDefault();
    if (savingRef.current) return;
    savingRef.current = true;
    setIsSaving(true);
    setSaveError("");

    try {
      const response = await api.patch("/assets/" + asset.id + "/", {
        name,
        description,
        tags: selectedTag,
      });

      setOpen(false);
      onAssetUpdated?.(response.data);
      toaster.create({
        description: "Successfully Edited Asset!",
        type: "success"
      });

    } catch (err) {
      const details = err.response?.data;
      setSaveError(
        details && typeof details === "object"
          ? Object.entries(details)
              .map(([field, messages]) => `${field}: ${Array.isArray(messages) ? messages.join(" ") : String(messages)}`)
              .join(" ")
          : "Unable to save changes. Please try again."
      );
    } finally {
      savingRef.current = false;
      setIsSaving(false);
    }
  }

  return (
    <>
      <Dialog.Root
        open={open}
        onOpenChange={handleOpenChange}
        closeOnEscape={!isSaving}
        closeOnInteractOutside={!isSaving}
        lazyMount
        unmountOnExit
      >
        <Dialog.Trigger asChild>
          <Button 
          variant="surface"
          >
            Edit
          </Button>
        </Dialog.Trigger>

        <Portal>
          <Dialog.Backdrop />

          <Dialog.Positioner>
            <Dialog.Content colorPalette="gray" as="form" onSubmit={handleAssetFileEdit} maxW="lg" w="calc(100% - 2rem)">
              <Dialog.Header>
                <Dialog.Title>Edit Asset: {asset.name}</Dialog.Title>
              </Dialog.Header>

              <Dialog.Body pb="4">
                <Stack gap="4">
                  {/* Name field */}
                  <Field.Root>
                    <Field.Label>Name</Field.Label>
                    <Input
                      placeholder="Name"
                      required
                      maxLength={200}
                      value={name}
                      disabled={isSaving}
                      onChange={(e) => setName(e.target.value)}
                    />
                  </Field.Root>

                  {/* Description field */}
                  <Field.Root>
                    <Field.Label>Description</Field.Label>
                    <Textarea
                      placeholder="Description"
                      required
                      value={description}
                      disabled={isSaving}
                      onChange={(e) => setDescription(e.target.value)}
                      height="200px"
                    />
                  </Field.Root>

                  {/* tags */}
                  <Field.Root>
                    <Field.Label>Tags</Field.Label>
                    <AssetTag
                      tags={tags}
                      loading={loading}
                      error={error}
                      disabled={isSaving}
                      onRetry={refresh}
                      selectedTags={selectedTag}
                      onSelectTag={handleTagSelect}
                    />
                  </Field.Root>
                  {saveError && <Text role="alert" color="fg.error">{saveError}</Text>}
                </Stack>
              </Dialog.Body>
              <Dialog.CloseTrigger asChild>
                <CloseButton size="sm" disabled={isSaving} />
              </Dialog.CloseTrigger>

              <Dialog.Footer>
                <Dialog.ActionTrigger asChild>
                  <Button type="button" variant="outline" disabled={isSaving}>Cancel</Button>
                </Dialog.ActionTrigger>

                <Button
                  type="submit"
                  bg="blue.700"
                  color="white"
                  loading={isSaving}
                  loadingText="Saving…"
                >Save</Button>
              </Dialog.Footer>
            </Dialog.Content>
          </Dialog.Positioner>
        </Portal>
      </Dialog.Root>
    </>
  );
}
