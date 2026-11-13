"use client";

import { useEffect } from "react";
import { Text } from "@chakra-ui/react";
import { useRouter } from "next/navigation";
import EditorLayout from "@/components/layouts/EditorLayout";
import SecurityDashboard from "@/components/security/SecurityDashboard";
import useBrowserSession from "@/hooks/useBrowserSession";

export default function SecurityPage() {
  const session = useBrowserSession();
  const router = useRouter();
  const allowed = session.ready && session.authenticated && session.group === "Admin";
  useEffect(() => {
    if (session.ready && !session.authenticated) router.replace("/login");
    else if (session.ready && session.group !== "Admin") router.replace("/editor/home");
  }, [session.ready, session.authenticated, session.group, router]);
  return <EditorLayout wide>{allowed ? <SecurityDashboard /> : <Text role="status">Checking administrator access...</Text>}</EditorLayout>;
}
