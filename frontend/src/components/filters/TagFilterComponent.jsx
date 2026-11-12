"use client";

import { Button, Flex, NativeSelect, Text } from "@chakra-ui/react";
import useTags from "@/hooks/useTags";

export default function TagFilterComponent({ value = "", onChange }) {
  const { tags, loading, error, refresh } = useTags();
  return (
    <Flex gap="2" align="center" wrap="wrap">
      <NativeSelect.Root size="sm" w="auto" minW="150px">
        <NativeSelect.Field aria-label="Filter by tag" value={value} disabled={loading}
          onChange={(event) => onChange(event.target.value)}>
          <option value="">All tags</option>
          {value && !tags.some((tag) => tag.id === value) && <option value={value}>Selected tag</option>}
          {tags.map((tag) => <option key={tag.id} value={tag.id}>{tag.title}</option>)}
        </NativeSelect.Field>
        <NativeSelect.Indicator />
      </NativeSelect.Root>
      {error && <><Text role="alert" fontSize="sm">{error}</Text><Button size="xs" onClick={refresh}>Retry tags</Button></>}
    </Flex>
  );
}
