"use client";

import {
  Box,
  Button,
  Card,
  Flex,
  Spinner,
  Stack,
  Text,
} from "@chakra-ui/react";
import { useMemo, useRef, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { setKeyword } from "@/app/searchSlice";
import useBrowserSession from "@/hooks/useBrowserSession";
import useApiResource from "@/hooks/useApiResource";
import useDebouncedValue from "@/hooks/useDebouncedValue";
import useTags from "@/hooks/useTags";
import { downloadAsset } from "@/utils/api";
import { formatDateTime } from "@/utils/dateTime";
import { hasProcessingAssets, isAssetProcessing, mergeAssetResource } from "@/utils/assetFiles";
import { toaster, notifyUploadStatus } from "@/styles/ui/toaster";
import UploadAssetModal, { UploadStatusTracker } from "./UploadAssetModal";
import BasicFilterComponent from "./filters/BasicFilterComponent";
import TagFilterComponent from "./filters/TagFilterComponent";
import PreviewAssetModal from "./previews/PreviewAssetModal";
import PreviewAssetMedia, { AssetProcessingStatus } from "./previews/PreviewAssetMedia";
import EditAssetModal from "./EditAssetModal";
import ListPagination from "./ListPagination";

export default function AssetCard() {
  const session = useBrowserSession();
  const dispatch = useDispatch();
  const observed = useRef(new Map());
  const [uploadsToWatch, setUploadsToWatch] = useState([]);
  const { tags, loading: tagsLoading, error: tagsError } = useTags();
  const [filter, setFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [showUploads, setShowUploads] = useState(false);
  const editable = session.ready && ["Editor", "Admin"].includes(session.group);
  const managingUploads = editable && showUploads;
  const keyword = useSelector((state) => state.search.keyword);
  const search = useDebouncedValue(keyword);
  const queryKey = JSON.stringify([search, filter, tagFilter, managingUploads]);
  const [pagination, setPagination] = useState({ queryKey: null, page: 1 });
  const page = pagination.queryKey === queryKey ? pagination.page : 1;
  const params = new URLSearchParams({ page: String(page) });
  if (search) params.set("search", search);
  if (filter) params.set("ordering", filter);
  if (tagFilter) params.set("tags", tagFilter);
  if (managingUploads) params.set("uploads", "1");
  function observeAssets(data) {
    const rows = Array.isArray(data) ? data : data.results;
    const completed = new Set();
    let approved = false;
    for (const asset of rows) {
      const previous = observed.current.get(asset.id);
      if (previous && isAssetProcessing(previous) && !isAssetProcessing(asset)
        && ["approved", "rejected", "error"].includes(asset.processing_status)) {
        notifyUploadStatus(asset, previous);
        completed.add(asset.id);
        approved ||= asset.processing_status === "approved";
      }
      observed.current.set(asset.id, { ...previous, processing_status: asset.processing_status });
    }
    if (completed.size) {
      setUploadsToWatch((ids) => ids.filter((id) => !completed.has(id)));
    }
    if (approved && !managingUploads) resource.refresh();
  }
  const resource = useApiResource("/assets/?" + params.toString(), {
    pollWhile: managingUploads ? hasProcessingAssets : null,
    mergeData: mergeAssetResource,
    onData: observeAssets,
    failureMessage: "Couldn't load assets. Please refresh to try again.",
  });
  const assets = resource.data?.results || [];
  const count = resource.data?.count || 0;
  const tagNames = useMemo(
    () => new Map(tags.map((tag) => [tag.id, tag.title])),
    [tags],
  );
  const download = (asset) =>
    downloadAsset(asset).catch(() =>
      toaster.create({ description: "Couldn't download this file. Please try again.", type: "error" }),
    );

  function changePage(next) {
    setPagination({ queryKey, page: next });
  }

  function assetChanged(updated) {
    resource.mutate(
      (data) =>
        data && {
          ...data,
          results: data.results.map((asset) =>
            asset.id === updated.id ? updated : asset,
          ),
        },
    );
    resource.refresh();
  }

  function uploaded(updated, context = {}) {
    observed.current.set(updated.id, { ...context, processing_status: updated.processing_status });
    if (isAssetProcessing(updated)) setUploadsToWatch((ids) => [...new Set([...ids, updated.id])]);
    dispatch(setKeyword(""));
    setFilter("");
    setTagFilter("");
    setShowUploads(true);
    setPagination({ queryKey: null, page: 1 });
    assetChanged(updated);
  }

  function deleted(code) {
    resource.mutate(
      (data) =>
        data && {
          ...data,
          count: Math.max(0, data.count - 1),
          results: data.results.filter((asset) => asset.code !== code),
        },
    );
    if (assets.length === 1 && page > 1) changePage(page - 1);
    resource.refresh();
  }

  function tagLabel(asset) {
    if (!asset.tags.length) return "None";
    if (asset.tags.every((id) => tagNames.has(id)))
      return asset.tags.map((id) => tagNames.get(id)).join(", ");
    return tagsLoading
      ? "Loading…"
      : tagsError
        ? "Unavailable"
        : "Tags changed; refresh assets.";
  }

  return (
    <Box>
      {editable && uploadsToWatch.map((id) => <UploadStatusTracker key={id} assetId={id}
        enabled={!managingUploads || !assets.some((asset) => asset.id === id)} onStatus={observeAssets} />)}
      <Flex gap="2" justify="space-between" wrap="wrap">
        {editable && (
          <Button
            variant="outline"
            onClick={() => setShowUploads((value) => !value)}
          >
            {managingUploads ? "Back to library" : "Manage uploads"}
          </Button>
        )}
        <Button
          variant="outline"
          onClick={resource.refresh}
          disabled={resource.loading}
        >
          Refresh assets
        </Button>
        <Box height="10">
          <BasicFilterComponent value={filter} onChange={setFilter} />
        </Box>
        <Box height="10">
          <TagFilterComponent value={tagFilter} onChange={setTagFilter} />
        </Box>
        <Box height="10" width="50" ml="auto">
          {editable && <UploadAssetModal onAssetUploaded={uploaded} />}
        </Box>
      </Flex>
      {managingUploads && <Text color="fg.muted" fontSize="sm" mt="3">
        All uploads are shown here, including files being checked. Only ready files appear in the library.
      </Text>}
      <br />
      <br />
      {resource.loading && (
        <Flex role="status" gap="2" align="center">
          <Spinner size="sm" />
          Loading assets…
        </Flex>
      )}
      {resource.error && (
        <Stack>
          <Text role="alert" color="red.600">
            {resource.error}
          </Text>
          <Button alignSelf="start" onClick={resource.refresh}>
            Retry assets
          </Button>
        </Stack>
      )}
      {resource.pollError && <Text role="status" fontSize="sm" color="fg.muted" mb="3">{resource.pollError}</Text>}
      {!resource.loading && !resource.error && !assets.length && (
        <Text role="status">
          {search || tagFilter
            ? "No assets match your filters."
            : "No assets yet. Upload a file to get started."}
        </Text>
      )}
      <Flex gap={31} direction="row" wrap="wrap" aria-busy={resource.loading}>
        {assets.map((asset) => (
          <Card.Root
            key={asset.id}
            w={{ base: "full", sm: "320px" }}
            maxW="full"
            variant="elevated"
          >
            <Card.Body gap="2" colorPalette="gray" minW="0">
              <Stack>
                <Box h="140px">
                  <PreviewAssetMedia asset={asset} compact />
                </Box>
                <Box>
                  <Card.Title overflowWrap="anywhere">{asset.name}</Card.Title>
                  <p>{Number(asset.file_size).toFixed(2)} MB</p>
                  <Text fontSize="sm" color="fg.muted" mb="2">Version {asset.version_no}</Text>
                  <AssetProcessingStatus asset={asset} showDetail={managingUploads} />
                  <Card.Description overflowWrap="anywhere">
                    {asset.description}
                  </Card.Description>
                </Box>
              </Stack>
              <Flex direction="column">
                <Card.Description overflowWrap="anywhere">
                  <b>Uploaded By:</b> {asset.uploaded_by}
                </Card.Description>
                <Card.Description overflowWrap="anywhere">
                  <b>Datetime:</b> {formatDateTime(asset.upload_datetime)}
                </Card.Description>
                <Card.Description overflowWrap="anywhere">
                  <b>Tags: </b>
                  {tagLabel(asset)}
                </Card.Description>
              </Flex>
            </Card.Body>
            <Card.Footer justifyContent="flex-end" flexWrap="wrap">
              <PreviewAssetModal
                asset={asset}
                onAssetDeleted={deleted}
                onAssetUpdated={assetChanged}
                onAssetUploaded={uploaded}
                onVersionsLoaded={observeAssets}
              />
              <Button
                variant="surface"
                disabled={asset.processing_status !== "approved"}
                onClick={() => download(asset)}
              >
                Download
              </Button>
              {editable && (
                <>
                  {["rejected", "error"].includes(asset.processing_status) && <UploadAssetModal asset={asset} onAssetUploaded={uploaded} />}
                  <EditAssetModal asset={asset} onAssetUpdated={assetChanged} />
                </>
              )}
            </Card.Footer>
          </Card.Root>
        ))}
      </Flex>
      <ListPagination
        page={page}
        count={count}
        onPageChange={changePage}
        disabled={resource.loading}
      />
    </Box>
  );
}
