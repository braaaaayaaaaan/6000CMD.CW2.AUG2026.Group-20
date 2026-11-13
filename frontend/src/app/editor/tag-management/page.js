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
    if (session.ready && !session.authenticated) router.replace("/login");
    else if (session.ready && !editable) router.replace("/editor/home");
  }, [session.ready, session.authenticated, editable, router]);
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
      <Heading>Tag Management</Heading>
      <Stack>
        <Box display="flex" justifyContent="flex-end"><AddTag /></Box>
        {usage.error && <Stack><Text role="alert">Usage Counts: {usage.error}</Text><Button alignSelf="start" variant="outline" onClick={usage.refresh}>Retry Counts</Button></Stack>}
        {actionError && !deleting && <Text role="alert" color="red.600">{actionError}</Text>}
        <Box overflowX="auto">
          <Table.Root variant="line">
            <Table.Header><Table.Row><Table.ColumnHeader>Tag Name</Table.ColumnHeader><Table.ColumnHeader textAlign="center">Usage Count</Table.ColumnHeader><Table.ColumnHeader textAlign="center">Actions</Table.ColumnHeader></Table.Row></Table.Header>
            <Table.Body>
              {loading ? (
                <Table.Row><Table.Cell colSpan={3} textAlign="center"><Spinner size="lg" color="purple.500" aria-label="Loading Tags" /></Table.Cell></Table.Row>
              ) : error ? (
                <Table.Row><Table.Cell colSpan={3} textAlign="center" color="red.500">
                  <Text role="alert">{error}</Text><Button size="xs" variant="outline" onClick={refresh}>Retry Tags</Button>
                </Table.Cell></Table.Row>
              ) : rows.length ? rows.map((tag) => (
                <Table.Row key={tag.id}>
                  <Table.Cell>
                    {editing?.id === tag.id
                      ? <Box as="form" id={"edit-tag-" + tag.id} onSubmit={save}>
                          <Input size="sm" width="auto" aria-label="Tag Name" required maxLength={50} value={editing.title} disabled={saving}
                            onChange={(event) => setEditing({ id: tag.id, title: event.target.value })} />
                        </Box>
                      : tag.title}
                  </Table.Cell>
                  <Table.Cell textAlign="center">{loading || usage.loading ? "Loading…" : error || usage.error ? "Unavailable" : (usage.data || []).find((item) => item.id === tag.id)?.usage_count ?? 0}</Table.Cell>
                  <Table.Cell textAlign="center">
                    <Flex gap="10px" wrap="wrap" justify="center">
                      {editing?.id === tag.id ? <>
                        <Button size="xs" bg="green.600" type="submit" form={"edit-tag-" + tag.id} loading={saving} disabled={saving}>Save</Button>
                        <Button size="xs" bg="gray.400" disabled={saving} onClick={() => { setEditing(null); setActionError(""); }}>Cancel</Button>
                      </> : <>
                        <Button size="xs" variant="surface" colorPalette="gray" disabled={saving || loading} onClick={() => { setEditing({ id: tag.id, title: tag.title }); setActionError(""); }}>Edit</Button>
                        <Button size="xs" colorPalette="red" variant="surface" disabled={saving || loading} onClick={() => { setDeleting(tag); setActionError(""); }}>Delete</Button>
                      </>}
                    </Flex>
                  </Table.Cell>
                </Table.Row>
              )) : <Table.Row><Table.Cell colSpan={3} textAlign="center">No Tags Found!</Table.Cell></Table.Row>}
            </Table.Body>
          </Table.Root>
        </Box>
        <ListPagination page={page} count={tags.length} onPageChange={setPage} disabled={saving || loading} />
        <Dialog.Root role="alertdialog" open={Boolean(deleting)} onOpenChange={({ open }) => {
          if (!open && !busy.current) { setDeleting(null); setActionError(""); }
        }} closeOnEscape={!saving} closeOnInteractOutside={!saving} lazyMount unmountOnExit>
          <Portal><Dialog.Backdrop /><Dialog.Positioner>
            <Dialog.Content w="calc(100% - 2rem)">
              <Dialog.Header><Dialog.Title>Delete Tag?</Dialog.Title></Dialog.Header>
              <Dialog.Body>
                <Text>Remove “{deleting?.title}” and its associations? The assets will be kept.</Text>
                {actionError && <Text role="alert" color="red.600">{actionError}</Text>}
              </Dialog.Body>
              <Dialog.Footer>
                <Dialog.ActionTrigger asChild><Button variant="outline" disabled={saving}>Cancel</Button></Dialog.ActionTrigger>
                <Button variant="surface" colorPalette="red" onClick={remove} loading={saving} disabled={saving} loadingText="Deleting…">Delete</Button>
              </Dialog.Footer>
              <Dialog.CloseTrigger asChild><CloseButton size="sm" disabled={saving} /></Dialog.CloseTrigger>
            </Dialog.Content>
          </Dialog.Positioner></Portal>
        </Dialog.Root>
      </Stack>
      </> : <Text role="status">Loading Your Workspace…</Text>}
    </EditorLayout>
  );
}
