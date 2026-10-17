import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // Match the tsconfig.json path alias so "@/components/..." resolves
      // correctly in both the Next.js build and the Vitest test runner.
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    // Provide a setup file for @testing-library/jest-dom matchers
    setupFiles: ["./src/test-setup.ts"],
  },
});
