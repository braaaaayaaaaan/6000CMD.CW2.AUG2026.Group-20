"use client";

import { Container, Flex, Box } from "@chakra-ui/react";
import { FaFolderOpen, FaShieldHalved } from "react-icons/fa6";
import { IoPricetagsSharp } from "react-icons/io5";
import { LuUpload } from "react-icons/lu";
import NavBar from "../NavBar";
import useBrowserSession from "@/hooks/useBrowserSession";

export default function EditorLayout({ children, wide = false }) {
  const session = useBrowserSession();
  const items = [{ title: "Asset Library", page: "/editor/home", icon: <FaFolderOpen /> }];
  if (session.ready && ["Editor", "Admin"].includes(session.group)) {
    items.push({ title: "Uploads", page: "/editor/uploads", icon: <LuUpload /> });
    items.push({ title: "Tag Management", page: "/editor/tag-management", icon: <IoPricetagsSharp /> });
  }
  if (session.ready && session.group === "Admin") {
    items.push({ title: "Security Dashboard", page: "/editor/security", icon: <FaShieldHalved /> });
  }
  return (
    <>
      <Container colorPalette="gray" maxW={wide ? "1440px" : "7xl"}
        px={wide ? { base: "4", md: "8", xl: "12" } : { base: "4", md: "6" }} pb="12">
        <Flex direction="column" gap="6">
          <Box><NavBar items={items} /></Box>
          <Box minW="0">{children}</Box>
        </Flex>
      </Container>
    </>
  );
}
