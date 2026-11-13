"use client";

import { Button, Flex, Menu, Portal, Text } from "@chakra-ui/react";
import { IoPricetagsSharp } from "react-icons/io5";
import useTags from "@/hooks/useTags";

export default function TagFilterComponent({ value = "", onChange }) {
  const { tags, loading, error, refresh } = useTags();
  return (
    <Flex gap="2" align="center" wrap="wrap">
      <Menu.Root>
        <Menu.Trigger asChild>
          <Button variant="outline" size="sm" disabled={loading}><IoPricetagsSharp /><Text as="span" truncate maxW="40">{value ? tags.find((tag) => String(tag.id) === value)?.title || "Selected Tag" : "All Tags"}</Text></Button>
        </Menu.Trigger>
        <Portal>
          <Menu.Positioner>
            <Menu.Content minW="10rem" aria-label="Filter By Tag">
              <Menu.RadioItemGroup value={value} onValueChange={({ value }) => onChange(value)}>
                <Menu.RadioItem value="">All Tags<Menu.ItemIndicator /></Menu.RadioItem>
                {value && !tags.some((tag) => String(tag.id) === value) && (
                  <Menu.RadioItem value={value}>Selected Tag<Menu.ItemIndicator /></Menu.RadioItem>
                )}
                {tags.map((tag) => (
                  <Menu.RadioItem key={tag.id} value={String(tag.id)}>{tag.title}<Menu.ItemIndicator /></Menu.RadioItem>
                ))}
              </Menu.RadioItemGroup>
            </Menu.Content>
          </Menu.Positioner>
        </Portal>
      </Menu.Root>
      {error && <><Text role="alert" fontSize="sm">{error}</Text><Button size="xs" variant="outline" onClick={refresh}>Retry Tags</Button></>}
    </Flex>
  );
}
