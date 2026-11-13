"use client";

import { Flex, Input, InputGroup } from "@chakra-ui/react";
import { LuSearch } from "react-icons/lu";
import { useDispatch, useSelector } from "react-redux";
import { setKeyword } from "@/app/searchSlice";

export default function SearchBar() {
  const dispatch = useDispatch();
  const keyword = useSelector((state) => state.search.keyword);
  return (
    <Flex flex={{ base: "1 0 100%", md: "1" }} order={{ base: 3, md: 0 }} justify="center" minW="0">
      <InputGroup endElement={<LuSearch />} width={{ base: "full", md: "1/2" }}>
        <Input variant="outline" aria-label="Search assets" placeholder="Search for assets" value={keyword}
          onChange={(event) => dispatch(setKeyword(event.target.value))} />
      </InputGroup>
    </Flex>
  );
}
