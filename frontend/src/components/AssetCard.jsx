"use client";

import { Box, Button, Card, Flex, Spinner, Stack, Text } from "@chakra-ui/react";
import { useMemo, useState } from "react";
import { useSelector } from "react-redux";
import useBrowserSession from "@/hooks/useBrowserSession";
import useApiResource from "@/hooks/useApiResource";
import useDebouncedValue from "@/hooks/useDebouncedValue";
import useTags from "@/hooks/useTags";
import { downloadAsset, errorMessage } from "@/utils/api";
import { formatDateTime } from "@/utils/dateTime";
import { toaster } from "@/styles/ui/toaster";
import UploadAssetModal from "./UploadAssetModal";
import BasicFilterComponent from "./filters/BasicFilterComponent";
import TagFilterComponent from "./filters/TagFilterComponent";
import PreviewAssetModal from "./previews/PreviewAssetModal";
import PreviewAssetMedia from "./previews/PreviewAssetMedia";
import EditAssetModal from "./EditAssetModal";
import ListPagination from "./ListPagination";

export default function AssetCard() {
  const session = useBrowserSession();
  const { tags, loading: tagsLoading, error: tagsError } = useTags();
  const [filter, setFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const keyword = useSelector((state) => state.search.keyword);
  const search = useDebouncedValue(keyword);
  const queryKey = JSON.stringify([search, filter, tagFilter]);
  const [pagination, setPagination] = useState({ queryKey: null, page: 1 });
  const page = pagination.queryKey === queryKey ? pagination.page : 1;
  const params = new URLSearchParams({ page: String(page) });
  if (search) params.set("search", search);
  if (filter) params.set("ordering", filter);
  if (tagFilter) params.set("tags", tagFilter);
  const resource = useApiResource("/assets/?" + params.toString());
  const assets = resource.data?.results || [];
  const count = resource.data?.count || 0;
  const tagNames = useMemo(() => new Map(tags.map((tag) => [tag.id, tag.title])), [tags]);
  const editable = session.ready && ["Editor", "Admin"].includes(session.group);
  const download = (asset) => downloadAsset(asset).catch((error) => toaster.create({ description: errorMessage(error), type: "error" }));

  function changePage(next) { setPagination({ queryKey, page: next }); }

  function assetChanged(updated) {
    resource.mutate((data) => data && ({
      ...data, results: data.results.map((asset) => asset.code === updated.code ? updated : asset),
    }));
    resource.refresh();
  }

  function uploaded(updated) {
    changePage(1);
    assetChanged(updated);
  }

  function deleted(code) {
    resource.mutate((data) => data && ({
      ...data, count: Math.max(0, data.count - 1), results: data.results.filter((asset) => asset.code !== code),
    }));
    if (assets.length === 1 && page > 1) changePage(page - 1);
    resource.refresh();
  }

  function tagLabel(asset) {
    if (!asset.tags.length) return "None";
    if (asset.tags.every((id) => tagNames.has(id))) return asset.tags.map((id) => tagNames.get(id)).join(", ");
    return tagsLoading ? "Loading…" : tagsError ? "Unavailable" : "Tags changed; refresh assets.";
  }

  return (
    <Stack gap="5" mt="5">
      <Flex gap="3" justify="space-between" wrap="wrap" align="center">
        <BasicFilterComponent value={filter} onChange={setFilter} />
        <TagFilterComponent value={tagFilter} onChange={setTagFilter} />
        {editable && <Box ml={{ md: "auto" }}><UploadAssetModal onAssetUploaded={uploaded} /></Box>}
      </Flex>
      {resource.loading && <Flex role="status" gap="2" align="center"><Spinner size="sm" />Loading assets…</Flex>}
      {resource.error && <Stack>
        <Text role="alert" color="red.600">{resource.error}</Text>
        <Button alignSelf="start" onClick={resource.refresh}>Retry assets</Button>
      </Stack>}
      {!resource.loading && !resource.error && !assets.length && (
        <Text role="status">{search || tagFilter ? "No assets match your filters." : "No assets yet. Upload a file to get started."}</Text>
      )}
      <Flex gap="6" wrap="wrap" align="stretch" aria-busy={resource.loading}>
        {assets.map((asset) => (
          <Card.Root key={asset.id} w={{ base: "full", sm: "320px" }} maxW="full" variant="elevated">
            <Card.Body gap="3" minW="0">
              <Box h="150px"><PreviewAssetMedia asset={asset} compact /></Box>
              <Card.Title overflowWrap="anywhere">{asset.name}</Card.Title>
              <Text fontSize="sm">{Number(asset.file_size).toFixed(2)} MB</Text>
              <Card.Description overflowWrap="anywhere">{asset.description}</Card.Description>
              <Text fontSize="sm" overflowWrap="anywhere"><b>Uploaded By:</b> {asset.uploaded_by}</Text>
              <Text fontSize="sm" overflowWrap="anywhere"><b>Uploaded:</b> {formatDateTime(asset.upload_datetime)}</Text>
              <Text fontSize="sm" overflowWrap="anywhere"><b>Tags:</b> {tagLabel(asset)}</Text>
            </Card.Body>
            <Card.Footer gap="2" flexWrap="wrap">
              <PreviewAssetModal asset={asset} onAssetDeleted={deleted} onAssetUpdated={assetChanged} />
              <Button variant="surface" size="sm" onClick={() => download(asset)}>Download</Button>
              {editable && <EditAssetModal asset={asset} onAssetUpdated={assetChanged} />}
            </Card.Footer>
          </Card.Root>
        ))}
      </Flex>
      <ListPagination page={page} count={count} onPageChange={changePage} disabled={resource.loading} />
    </Stack>
  );
}
