"use client";

import { Button, CloseButton, Dialog, Field, Input, Portal, Text } from "@chakra-ui/react";
import { useRef, useState } from "react";
import { LuPlus } from "react-icons/lu";
import { api, errorMessage } from "@/utils/api";
import { refreshTags } from "@/hooks/useTags";
import { toaster } from "@/styles/ui/toaster";

export default function AddTag() {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const busy = useRef(false);
  async function submit(event) {
    event.preventDefault();
    if (busy.current) return;
    busy.current = true; setSaving(true); setError("");
    try {
      await api.post("/tags/", { title: title.trim() });
      setOpen(false);
      await refreshTags();
      toaster.create({ description: "Tag created.", type: "success" });
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      busy.current = false; setSaving(false);
    }
  }
  return (
    <Dialog.Root open={open} onOpenChange={({ open }) => {
      if (busy.current) return;
      setOpen(open);
      if (open) { setTitle(""); setError(""); }
    }} closeOnEscape={!saving} closeOnInteractOutside={!saving} lazyMount unmountOnExit>
      <Dialog.Trigger asChild><Button size="xs" bg="blue.700" color="white"><LuPlus />New Tag</Button></Dialog.Trigger>
      <Portal><Dialog.Backdrop /><Dialog.Positioner>
        <Dialog.Content as="form" onSubmit={submit} w="calc(100% - 2rem)">
          <Dialog.Header><Dialog.Title>Add New Tag</Dialog.Title></Dialog.Header>
          <Dialog.Body>
            <Field.Root><Field.Label>Tag Name</Field.Label>
              <Input placeholder="Enter Your Tag Name" required maxLength={50} value={title} onChange={(event) => setTitle(event.target.value)} disabled={saving} />
            </Field.Root>
            {error && <Text role="alert" color="red.600">{error}</Text>}
          </Dialog.Body>
          <Dialog.Footer>
            <Dialog.ActionTrigger asChild><Button type="button" variant="surface" colorPalette="gray" disabled={saving}>Cancel</Button></Dialog.ActionTrigger>
            <Button type="submit" bg="blue.700" color="white" loading={saving} disabled={saving} loadingText="Saving…">Save</Button>
          </Dialog.Footer>
          <Dialog.CloseTrigger asChild><CloseButton type="button" size="sm" disabled={saving} /></Dialog.CloseTrigger>
        </Dialog.Content>
      </Dialog.Positioner></Portal>
    </Dialog.Root>
  );
}
