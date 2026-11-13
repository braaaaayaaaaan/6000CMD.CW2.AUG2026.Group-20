"use client";

import { useEffect } from "react";
import { Text } from "@chakra-ui/react";
import { useRouter } from "next/navigation";
import EditorLayout from "@/components/layouts/EditorLayout";
import AssetCard from "@/components/AssetCard";
import useBrowserSession from "@/hooks/useBrowserSession";

export default function EditorHome() {
  const router = useRouter();
  const session = useBrowserSession();
  useEffect(() => {
    if (session.ready && !session.authenticated) router.replace("/login");
  }, [session.ready, session.authenticated, router]);

  return (
    <EditorLayout>
      {session.ready && session.authenticated
        ? <AssetCard />
        : <Text role="status" py="6">Loading your workspace…</Text>}
    </EditorLayout>
  );
}
