"use client";

import { Button, Flex, Icon, Image, Tabs, Text } from "@chakra-ui/react";
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
      <Flex py="5" gap="4" align="center" justify="space-between" bg="white" wrap={{ base: "wrap", md: "nowrap" }}>
        <Link href="/editor/home" aria-label="Digital Asset Library">
          <Image src={Logo.src ?? Logo} alt="ManticAI" h="40px" w="auto" />
        </Link>
        <SearchBar />
        <Button asChild size="sm" bg="blue.700" color="white" maxW={{ base: "160px", md: "240px" }}>
          <Link href={session.authenticated ? "/user-profile" : "/login"} title={session.username || "Log In"}>
            {session.authenticated ? <><LuUserRound /><Text as="span" truncate>{session.username}</Text></> : "Log In"}
          </Link>
        </Button>
      </Flex>
      <Tabs.Root value={current} lazyMount unmountOnExit variant="line" colorPalette="blue">
        <Tabs.List flexWrap="wrap">
          {items.map((item) => (
            <Tabs.Trigger key={item.title} value={item.title} asChild>
              <Link href={item.page}><Icon asChild color="fg.muted" boxSize="1em" flexShrink="0" aria-hidden="true">{item.icon}</Icon>{item.title}</Link>
            </Tabs.Trigger>
          ))}
          <Tabs.Indicator unstyled />
        </Tabs.List>
      </Tabs.Root>
    </>
  );
}
