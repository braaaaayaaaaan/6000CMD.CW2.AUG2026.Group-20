"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import useBrowserSession from "@/hooks/useBrowserSession";

export default function Landing() {
  const router = useRouter();
  const session = useBrowserSession();

  useEffect(() => {
    if (session.ready) router.replace(session.authenticated ? "/editor/home" : "/login");
  }, [session.ready, session.authenticated, router]);

  return <p role="status">Loading…</p>;
}
