"use client";

import {
  Box,
  Button,
  Card,
  Flex,
  Grid,
  Heading,
  Badge,
  Spinner,
  Stack,
  Text,
} from "@chakra-ui/react";
import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { LuUpload, LuRefreshCw, LuImage, LuVideo, LuBox } from "react-icons/lu";
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
import ListPagination from "./ListPagination";

export default function AssetCard({ uploadsView = false, openUpload = false }) {
  const router = useRouter();
  const session = useBrowserSession();
  const dispatch = useDispatch();
  const observed = useRef(new Map());
  const [uploadsToWatch, setUploadsToWatch] = useState([]);
  const { tags, loading: tagsLoading, error: tagsError } = useTags();
  const [filter, setFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const receiptRead = useRef(false);
  const editable = session.ready && ["Editor", "Admin"].includes(session.group);
  const managingUploads = editable && uploadsView;
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
    if (managingUploads && !receiptRead.current) {
      receiptRead.current = true;
      try {
        const receipt = JSON.parse(sessionStorage.getItem("dam-upload-receipt") || "null");
        sessionStorage.removeItem("dam-upload-receipt");
        if (receipt?.user === session.id && receipt.id) {
          observed.current.set(receipt.id, receipt);
          if (isAssetProcessing(receipt)) setUploadsToWatch((ids) => [...new Set([...ids, receipt.id])]);
        }
      } catch { /* Statuses still load normally when storage is unavailable. */ }
    }
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
    if (!managingUploads) {
      try {
        sessionStorage.setItem("dam-upload-receipt", JSON.stringify({
          id: updated.id, user: session.id, processing_status: updated.processing_status, ...context,
        }));
      } catch { /* The uploads page can fetch the current state directly. */ }
      router.push("/editor/uploads");
      return;
    }
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

  const fileInfo = (asset) => `${asset.file_type.toUpperCase()} · ${Number(asset.file_size).toFixed(2)} MB · Version ${asset.version_no}`;
  const details = (asset) => <PreviewAssetModal asset={asset} triggerLabel={managingUploads ? "Details" : undefined} onAssetDeleted={deleted}
    onAssetUpdated={assetChanged} onAssetUploaded={uploaded} onVersionsLoaded={observeAssets} />;
  const filtered = Boolean(search || tagFilter || filter);

  return (
    <Stack gap="6">
      {editable && uploadsToWatch.map((id) => <UploadStatusTracker key={id} assetId={id}
        enabled={!managingUploads || !assets.some((asset) => asset.id === id)} onStatus={observeAssets} />)}
      <Flex align={{ base: "start", sm: "center" }} justify="space-between" gap="4" direction={{ base: "column", sm: "row" }}>
        <Stack gap="1">
          <Heading as="h1" size="2xl">{managingUploads ? "Uploads" : "Asset library"}</Heading>
          <Text color="fg.muted" fontSize="sm">
            {managingUploads ? "Follow each asset's latest upload. Open Details for earlier versions." : "Browse and download files that are ready to use."}
          </Text>
        </Stack>
        {editable && (managingUploads
          ? <UploadAssetModal onAssetUploaded={uploaded} defaultOpen={openUpload} />
          : <Button asChild size="sm" bg="blue.700" color="white" flexShrink="0">
              <Link href="/editor/uploads?upload=1" onClick={() => dispatch(setKeyword(""))}><LuUpload />Upload a file</Link>
            </Button>)}
      </Flex>

      <Flex align="center" justify="space-between" gap="3" wrap="wrap" borderBottomWidth="1px" pb="4">
        <Text fontSize="sm" color="fg.muted" role="status">{count} {count === 1 ? "asset" : "assets"}{search && ` matching “${search}”`}</Text>
        <Flex align="center" gap="2" wrap="wrap">
          <BasicFilterComponent value={filter} onChange={setFilter} />
          <TagFilterComponent value={tagFilter} onChange={setTagFilter} />
          {filtered && <Button size="sm" variant="plain" onClick={() => { dispatch(setKeyword("")); setFilter(""); setTagFilter(""); }}>Clear filters</Button>}
          <Button size="sm" minW="32" variant="outline" onClick={resource.refresh} loading={resource.loading} loadingText="Refreshing"><LuRefreshCw />Refresh</Button>
        </Flex>
      </Flex>
      {resource.error && <Stack align="start" gap="3" p="5" borderWidth="1px" rounded="lg">
        <Text role="alert">{resource.error}</Text><Button size="sm" variant="outline" onClick={resource.refresh}>Try again</Button>
      </Stack>}
      {resource.pollError && <Text role="status" fontSize="sm" color="fg.muted">{resource.pollError}</Text>}
      {resource.loading && !assets.length && <Flex role="status" align="center" justify="center" gap="3" py="12"><Spinner size="sm" />Loading {managingUploads ? "uploads" : "library"}…</Flex>}
      {!resource.loading && !resource.error && !assets.length && <Stack align="center" textAlign="center" gap="3" py="14" px="5" borderWidth="1px" borderStyle="dashed" rounded="lg">
        <LuUpload size={28} aria-hidden="true" />
        <Heading size="md">{filtered ? "No matching assets" : managingUploads ? "No uploads yet" : "Your library is waiting"}</Heading>
        <Text color="fg.muted" fontSize="sm" maxW="md">{filtered ? "Try a different search or clear your filters." : managingUploads ? "Upload a file to get started. Its progress will appear here." : editable ? "Files appear here once they are ready. Check Uploads to follow their progress." : "There are no ready files yet. Please check back later."}</Text>
        {filtered ? <Button variant="outline" size="sm" onClick={() => { dispatch(setKeyword("")); setFilter(""); setTagFilter(""); }}>Clear filters</Button>
          : editable && !managingUploads && <Button asChild variant="outline" size="sm"><Link href="/editor/uploads">View uploads</Link></Button>}
      </Stack>}

      {managingUploads ? <Stack gap="3" aria-busy={resource.loading}>
        {assets.length > 0 && <Grid display={{ base: "none", lg: "grid" }} templateColumns="minmax(0, 1fr) minmax(230px, 0.8fr) 240px" gap="6" px="5" color="fg.muted" fontSize="xs" fontWeight="semibold" aria-hidden="true"><Text>FILE</Text><Text>STATUS</Text><Text textAlign="right">ACTIONS</Text></Grid>}
        {assets.map((asset) => {
          const FileIcon = asset.file_type === "glb" ? LuBox : asset.file_type === "mp4" ? LuVideo : LuImage;
          return <Grid key={asset.id} as="article" aria-label={asset.name}
            templateColumns={{ base: "minmax(0, 1fr)", lg: "minmax(0, 1fr) minmax(230px, 0.8fr) 240px" }}
            gap={{ base: "4", lg: "6" }} alignItems="center" p={{ base: "4", md: "5" }} borderWidth="1px" rounded="lg" bg="bg.panel">
            <Flex gap="3" align="start" minW="0">
              <Flex boxSize="11" flexShrink="0" align="center" justify="center" bg="blue.50" color="blue.700" rounded="md"><FileIcon size={22} aria-hidden="true" /></Flex>
              <Stack gap="1" minW="0">
                <Text fontWeight="semibold" overflowWrap="anywhere">{asset.name}</Text>
                <Text fontSize="xs" color="fg.muted">{fileInfo(asset)}</Text>
                <Text fontSize="xs" color="fg.muted" overflowWrap="anywhere">{asset.uploaded_by} · {formatDateTime(asset.upload_datetime)}</Text>
              </Stack>
            </Flex>
            <AssetProcessingStatus asset={asset} showDetail />
            <Flex gap="2" wrap="wrap" justify={{ base: "start", lg: "end" }}>
              {details(asset)}
              {asset.processing_status === "approved" && <Button variant="surface" onClick={() => download(asset)}>Download</Button>}
              {["rejected", "error"].includes(asset.processing_status) && <UploadAssetModal asset={asset} onAssetUploaded={uploaded} />}
            </Flex>
          </Grid>;
        })}
      </Stack> : <Grid templateColumns={{ base: "minmax(0, 1fr)", sm: "repeat(2, minmax(0, 1fr))", lg: "repeat(3, minmax(0, 1fr))", xl: "repeat(4, minmax(0, 1fr))" }} gap="5" aria-busy={resource.loading}>
        {assets.map((asset) => <Card.Root key={asset.id} minW="0" overflow="hidden" variant="elevated">
          <Box aspectRatio={4 / 3} bg="gray.100" borderBottomWidth="1px" p="2"><PreviewAssetMedia asset={asset} compact /></Box>
          <Card.Body p="4" gap="2">
            <Flex gap="2" align="start" justify="space-between"><Card.Title fontSize="md" lineClamp={2} title={asset.name}>{asset.name}</Card.Title><Badge variant="subtle" flexShrink="0">{asset.file_type.toUpperCase()}</Badge></Flex>
            <Text fontSize="xs" color="fg.muted">{Number(asset.file_size).toFixed(2)} MB · Version {asset.version_no}</Text>
            <Card.Description fontSize="sm" lineClamp={2} minH="10">{asset.description}</Card.Description>
            <Text fontSize="xs" color="fg.muted" truncate title={tagLabel(asset)}>{tagLabel(asset) === "None" ? "No tags" : tagLabel(asset)}</Text>
          </Card.Body>
          <Card.Footer px="4" pb="4" pt="0" gap="2" mt="auto" flexWrap="wrap">
            {details(asset)}
            <Button variant="surface" disabled={asset.processing_status !== "approved"} onClick={() => download(asset)}>Download</Button>
          </Card.Footer>
        </Card.Root>)}
      </Grid>}
      <ListPagination page={page} count={count} onPageChange={changePage} disabled={resource.loading} />
    </Stack>
  );
}
