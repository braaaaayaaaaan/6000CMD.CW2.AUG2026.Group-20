"use client";

import { Button, Menu, Portal } from "@chakra-ui/react";
import { HiSortAscending } from "react-icons/hi";

export default function BasicFilterComponent({ value = "", onChange }) {
  return (
    <Menu.Root>
      <Menu.Trigger asChild>
        <Button variant="outline" size="sm"><HiSortAscending /> Sort</Button>
      </Menu.Trigger>
      <Portal>
        <Menu.Positioner>
          <Menu.Content minW="10rem" aria-label="Sort assets">
            <Menu.RadioItemGroup value={value} onValueChange={({ value }) => onChange(value)}>
              {[
                ["Default", ""], ["Ascending", "name"], ["Descending", "-name"],
                ["Newest", "-upload_datetime"], ["Oldest", "upload_datetime"],
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
