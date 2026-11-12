"use client";

import { Container, Flex, Box } from "@chakra-ui/react";
import { FaFolderOpen } from "react-icons/fa6";
import { IoPricetagsSharp } from "react-icons/io5";
import NavBar from "../NavBar";
import useBrowserSession from "@/hooks/useBrowserSession";

export default function EditorLayout({ children }) {
  const session = useBrowserSession();
  const items = [{ title: "Assets", page: "/editor/home", icon: <FaFolderOpen /> }];
  if (session.ready && ["Editor", "Admin"].includes(session.group)) {
    items.push({ title: "Tag Management", page: "/editor/tag-management", icon: <IoPricetagsSharp /> });
  }
  return (
    <Container maxW="8xl" px={{ base: "4", md: "8" }} pb="10">
      <Flex direction="column" gap="6">
        <NavBar items={items} />
        <Box minW="0">{children}</Box>
      </Flex>
    </Container>
  );
}
