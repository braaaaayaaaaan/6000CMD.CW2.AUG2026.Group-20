"use client";

import { Container, Flex, Box } from "@chakra-ui/react";
import { FaFolderOpen } from "react-icons/fa6";
import { IoPricetagsSharp } from "react-icons/io5";
import { LuUpload } from "react-icons/lu";
import NavBar from "../NavBar";
import useBrowserSession from "@/hooks/useBrowserSession";

export default function EditorLayout({ children }) {
  const session = useBrowserSession();
  const items = [{ title: "Asset Library", page: "/editor/home", icon: <FaFolderOpen /> }];
  if (session.ready && ["Editor", "Admin"].includes(session.group)) {
    items.push({ title: "Uploads", page: "/editor/uploads", icon: <LuUpload /> });
    items.push({ title: "Tag Management", page: "/editor/tag-management", icon: <IoPricetagsSharp /> });
  }
  return (
    <>
      <Container maxW="7xl" px={{ base: "4", md: "6" }} pb="12">
        <Flex direction="column" gap="6">
          <Box><NavBar items={items} /></Box>
          <Box minW="0">{children}</Box>
        </Flex>
      </Container>
    </>
  );
}
