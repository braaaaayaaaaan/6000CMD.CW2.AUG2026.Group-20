"use client";

import { useState } from "react";
import { ChakraProvider } from "@chakra-ui/react";
import { Provider as ReduxProvider } from "react-redux";
import { makeStore } from "@/app/store";
import { system } from "../theme";
import { ColorModeProvider } from "./color-mode";
import { Toaster } from "./toaster";

export function Provider({ children }) {
  const [store] = useState(makeStore);
  return (
    <ReduxProvider store={store}>
      <ChakraProvider value={system}>
        <ColorModeProvider>{children}<Toaster /></ColorModeProvider>
      </ChakraProvider>
    </ReduxProvider>
  );
}
