"use client";

import { Button, Flex, Image, Tabs, Text } from "@chakra-ui/react";
import { LuUserRound } from "react-icons/lu";
import { usePathname } from "next/navigation";
import Link from "next/link";
import Logo from "../assets/ManticAI_Logo.png";
import SearchBar from "./SearchBar";
import useBrowserSession from "@/hooks/useBrowserSession";

export default function NavBar({ items = [] }) {
  const path = usePathname();
  const session = useBrowserSession();
  const current = items.find((item) => item.page === path)?.title || "";
  return (
    <>
      <Flex py="5" gap="4" align="center" justify="space-between" wrap="wrap">
        <Link href="/editor/home" aria-label="Digital asset library">
          <Image src={Logo.src ?? Logo} alt="ManticAI" h="40px" w="auto" maxW={{ base: "150px", md: "220px" }} />
        </Link>
        <SearchBar />
        <Button asChild size="sm" bg="blue.700" color="white" maxW={{ base: "160px", md: "240px" }}>
          <Link href={session.accessToken ? "/user-profile" : "/login"} title={session.username || "Log in"}>
            {session.accessToken ? <><LuUserRound /><Text as="span" truncate>{session.username}</Text></> : "Log In"}
          </Link>
        </Button>
      </Flex>
      {items.length > 0 && (
        <Tabs.Root value={current} variant="line" colorPalette="blue">
          <Tabs.List flexWrap="wrap">
            {items.map((item) => (
              <Tabs.Trigger key={item.title} value={item.title} asChild>
                <Link href={item.page}>{item.icon}{item.title}</Link>
              </Tabs.Trigger>
            ))}
          </Tabs.List>
        </Tabs.Root>
      )}
    </>
  );
}
