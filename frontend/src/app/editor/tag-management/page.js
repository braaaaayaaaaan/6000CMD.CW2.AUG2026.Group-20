"use client";

import { Box, Button, CloseButton, Dialog, Flex, Heading, Input, Portal, Spinner, Stack, Table, Text } from "@chakra-ui/react";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import useBrowserSession from "@/hooks/useBrowserSession";
import EditorLayout from "@/components/layouts/EditorLayout";
import AddTag from "@/components/AddTag";
import ListPagination from "@/components/ListPagination";
import useTags from "@/hooks/useTags";
import useApiResource from "@/hooks/useApiResource";
import { api, errorMessage } from "@/utils/api";
import { toaster } from "@/styles/ui/toaster";

export default function TagManagement() {
  const router = useRouter();
  const session = useBrowserSession();
  const editable = session.ready && ["Editor", "Admin"].includes(session.group);
  useEffect(() => {
    if (session.ready && !session.accessToken) router.replace("/login");
    else if (session.ready && !editable) router.replace("/editor/home");
  }, [session.ready, session.accessToken, editable, router]);
  const { tags, loading, error, refresh, revision } = useTags();
  const usage = useApiResource("/tag-usage/", { enabled: !loading && !error, refreshKey: revision });
  const [requestedPage, setPage] = useState(1);
  const page = Math.min(requestedPage, Math.max(1, Math.ceil(tags.length / 40)));
  const rows = tags.slice((page - 1) * 40, page * 40);
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState("");
  const busy = useRef(false);

  async function save(event) {
    event.preventDefault();
    if (busy.current || !editing) return;
    busy.current = true; setSaving(true); setActionError("");
    try {
      await api.patch("/tags/" + editing.id + "/", { title: editing.title.trim() });
      setEditing(null);
      await refresh();
      toaster.create({ description: "Tag updated.", type: "success" });
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      busy.current = false; setSaving(false);
    }
  }

  async function remove() {
    if (busy.current || !deleting) return;
    busy.current = true; setSaving(true); setActionError("");
    try {
      await api.delete("/tags/" + deleting.id + "/");
      setDeleting(null);
      if (editing?.id === deleting.id) setEditing(null);
      await refresh();
      toaster.create({ description: "Tag deleted.", type: "success" });
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      busy.current = false; setSaving(false);
    }
  }

  return (
    <EditorLayout>
      {editable ? <>
      <Stack gap="4">
        <Heading>Tag Management</Heading>
        <Box alignSelf="end"><AddTag /></Box>
        {loading && <Flex role="status" gap="2"><Spinner size="sm" />Loading tags…</Flex>}
        {error && <Stack><Text role="alert">{error}</Text><Button alignSelf="start" onClick={refresh}>Retry tags</Button></Stack>}
        {usage.error && <Stack><Text role="alert">Usage counts: {usage.error}</Text><Button alignSelf="start" onClick={usage.refresh}>Retry counts</Button></Stack>}
        {actionError && !deleting && <Text role="alert" color="red.600">{actionError}</Text>}
        <Box overflowX="auto">
          <Table.Root>
            <Table.Header><Table.Row><Table.ColumnHeader>Tag Name</Table.ColumnHeader><Table.ColumnHeader>Usage Count</Table.ColumnHeader><Table.ColumnHeader>Actions</Table.ColumnHeader></Table.Row></Table.Header>
            <Table.Body>
              {rows.map((tag) => (
                <Table.Row key={tag.id}>
                  <Table.Cell>
                    {editing?.id === tag.id
                      ? <Box as="form" id={"edit-tag-" + tag.id} onSubmit={save}>
                          <Input aria-label="Tag name" required maxLength={50} value={editing.title} disabled={saving}
                            onChange={(event) => setEditing({ id: tag.id, title: event.target.value })} />
                        </Box>
                      : tag.title}
                  </Table.Cell>
                  <Table.Cell>{loading || usage.loading ? "Loading…" : error || usage.error ? "Unavailable" : (usage.data || []).find((item) => item.id === tag.id)?.usage_count ?? 0}</Table.Cell>
                  <Table.Cell>
                    <Flex gap="2" wrap="wrap">
                      {editing?.id === tag.id ? <>
                        <Button size="xs" type="submit" form={"edit-tag-" + tag.id} loading={saving} disabled={saving}>Save</Button>
                        <Button size="xs" variant="outline" disabled={saving} onClick={() => { setEditing(null); setActionError(""); }}>Cancel</Button>
                      </> : <>
                        <Button size="xs" variant="outline" disabled={saving || loading} onClick={() => { setEditing({ id: tag.id, title: tag.title }); setActionError(""); }}>Edit</Button>
                        <Button size="xs" colorPalette="red" variant="outline" disabled={saving || loading} onClick={() => { setDeleting(tag); setActionError(""); }}>Delete</Button>
                      </>}
                    </Flex>
                  </Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table.Root>
        </Box>
        {!loading && !error && !tags.length && <Text>No tags yet. Create a tag to get started.</Text>}
        <ListPagination page={page} count={tags.length} onPageChange={setPage} disabled={saving || loading} />
        <Dialog.Root role="alertdialog" open={Boolean(deleting)} onOpenChange={({ open }) => {
          if (!open && !busy.current) { setDeleting(null); setActionError(""); }
        }} closeOnEscape={!saving} closeOnInteractOutside={!saving} lazyMount unmountOnExit>
          <Portal><Dialog.Backdrop /><Dialog.Positioner>
            <Dialog.Content w="calc(100% - 2rem)">
              <Dialog.Header><Dialog.Title>Delete tag?</Dialog.Title></Dialog.Header>
              <Dialog.Body>
                <Text>Remove “{deleting?.title}” and its associations? The assets will be kept.</Text>
                {actionError && <Text role="alert" color="red.600">{actionError}</Text>}
              </Dialog.Body>
              <Dialog.Footer>
                <Dialog.ActionTrigger asChild><Button variant="outline" disabled={saving}>Cancel</Button></Dialog.ActionTrigger>
                <Button colorPalette="red" onClick={remove} loading={saving} disabled={saving} loadingText="Deleting…">Delete</Button>
              </Dialog.Footer>
              <Dialog.CloseTrigger asChild><CloseButton disabled={saving} /></Dialog.CloseTrigger>
            </Dialog.Content>
          </Dialog.Positioner></Portal>
        </Dialog.Root>
      </Stack>
      </> : <Text role="status">Loading your workspace…</Text>}
    </EditorLayout>
  );
}
