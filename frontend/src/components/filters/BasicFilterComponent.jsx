"use client";

import { NativeSelect } from "@chakra-ui/react";

export default function BasicFilterComponent({ value = "", onChange }) {
  return (
    <NativeSelect.Root size="sm" w="auto" minW="150px">
      <NativeSelect.Field aria-label="Sort assets" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Default order</option>
        <option value="name">Name: A–Z</option>
        <option value="-name">Name: Z–A</option>
        <option value="-upload_datetime">Newest first</option>
        <option value="upload_datetime">Oldest first</option>
      </NativeSelect.Field>
      <NativeSelect.Indicator />
    </NativeSelect.Root>
  );
}
