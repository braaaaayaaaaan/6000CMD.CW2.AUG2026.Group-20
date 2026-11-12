"use client";

import { useState } from "react";
import { ChakraProvider, defaultSystem } from "@chakra-ui/react";
import { Provider as ReduxProvider } from "react-redux";
import { makeStore } from "@/app/store";
import { ColorModeProvider } from "./color-mode";
import { Toaster } from "./toaster";

export function Provider({ children }) {
  const [store] = useState(makeStore);
  return (
    <ReduxProvider store={store}>
      <ChakraProvider value={defaultSystem}>
        <ColorModeProvider>{children}<Toaster /></ColorModeProvider>
      </ChakraProvider>
    </ReduxProvider>
  );
}
