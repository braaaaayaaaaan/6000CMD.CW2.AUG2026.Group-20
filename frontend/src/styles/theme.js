import { createSystem, defaultConfig } from "@chakra-ui/react";

export const system = createSystem(defaultConfig, {
  globalCss: {
    html: { colorPalette: "blue", colorScheme: "light" },
  },
  theme: {
    semanticTokens: {
      colors: {
        bg: {
          DEFAULT: { value: "{colors.white}" },
          panel: { value: "{colors.white}" },
          subtle: { value: "{colors.blue.50}" },
          muted: { value: "{colors.blue.100}" },
          emphasized: { value: "{colors.blue.200}" },
          inverted: { value: "{colors.blue.900}" },
          error: { value: "{colors.blue.50}" },
          warning: { value: "{colors.blue.50}" },
          success: { value: "{colors.green.50}" },
        },
        fg: {
          DEFAULT: { value: "{colors.blue.950}" },
          muted: { value: "{colors.blue.800}" },
          subtle: { value: "{colors.blue.600}" },
          inverted: { value: "{colors.white}" },
          error: { value: "{colors.blue.700}" },
          warning: { value: "{colors.blue.700}" },
          success: { value: "{colors.green.700}" },
        },
        border: {
          DEFAULT: { value: "{colors.blue.200}" },
          muted: { value: "{colors.blue.100}" },
          subtle: { value: "{colors.blue.50}" },
          emphasized: { value: "{colors.blue.300}" },
          inverted: { value: "{colors.blue.800}" },
          error: { value: "{colors.blue.600}" },
          warning: { value: "{colors.blue.600}" },
          success: { value: "{colors.green.600}" },
        },
        blue: {
          solid: { value: "{colors.blue.700}" },
          contrast: { value: "{colors.white}" },
        },
      },
    },
    slotRecipes: {
      dialog: { base: { backdrop: { bg: "blue.950/45" } } },
      toast: {
        base: {
          root: {
            bg: "blue.700",
            color: "white",
            "&[data-type=warning]": { bg: "blue.700", color: "white" },
            "&[data-type=success]": { bg: "green.700", color: "white", borderColor: "green.600" },
            "&[data-type=error]": { bg: "blue.700", color: "white" },
          },
        },
      },
    },
  },
});
