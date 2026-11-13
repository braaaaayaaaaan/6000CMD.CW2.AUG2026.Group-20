"use client";

import { Suspense, useEffect } from "react";
import { Flex, Spinner, Text } from "@chakra-ui/react";
import { useRouter, useSearchParams } from "next/navigation";
import EditorLayout from "@/components/layouts/EditorLayout";
import AssetCard from "@/components/AssetCard";
import useBrowserSession from "@/hooks/useBrowserSession";

function LoadingUploads() {
  return <Flex role="status" align="center" gap="3" py="8"><Spinner size="sm" /><Text>Loading Uploads…</Text></Flex>;
}

function Uploads() {
  const session = useBrowserSession();
  const router = useRouter();
  const search = useSearchParams();
  const editable = session.ready && session.authenticated && ["Editor", "Admin"].includes(session.group);
  useEffect(() => {
    if (session.ready && !session.authenticated) router.replace("/login");
    else if (session.ready && !editable) router.replace("/editor/home");
  }, [session.ready, session.authenticated, editable, router]);

  return <EditorLayout>{editable
    ? <AssetCard uploadsView openUpload={search.get("upload") === "1"} />
    : <LoadingUploads />}</EditorLayout>;
}

export default function UploadsPage() {
  return <Suspense fallback={<LoadingUploads />}><Uploads /></Suspense>;
}
