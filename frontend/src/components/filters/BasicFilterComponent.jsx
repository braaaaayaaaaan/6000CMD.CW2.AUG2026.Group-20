"use client";

import { Button, Menu, Portal } from "@chakra-ui/react";
import { HiSortAscending } from "react-icons/hi";

export default function BasicFilterComponent({ value = "", onChange }) {
  return (
    <Menu.Root>
      <Menu.Trigger asChild>
        <Button variant="outline" size="sm"><HiSortAscending />{({ name: "Name A–Z", "-name": "Name Z–A", upload_datetime: "Oldest First" })[value] || "Newest First"}</Button>
      </Menu.Trigger>
      <Portal>
        <Menu.Positioner>
          <Menu.Content minW="10rem" aria-label="Sort Assets">
            <Menu.RadioItemGroup value={value} onValueChange={({ value }) => onChange(value)}>
              {[
                ["Newest First", ""], ["Name A–Z", "name"], ["Name Z–A", "-name"],
                ["Oldest First", "upload_datetime"],
              ].map(([label, filter]) => (
                <Menu.RadioItem key={filter} value={filter}>{label}<Menu.ItemIndicator /></Menu.RadioItem>
              ))}
            </Menu.RadioItemGroup>
          </Menu.Content>
        </Menu.Positioner>
      </Portal>
    </Menu.Root>
  );
}
