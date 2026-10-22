import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = process.env.LSG_BACKEND ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": backend,
      "/mcp": backend,
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
  build: {
    chunkSizeWarningLimit: 1200,
    rolldownOptions: {
      output: {
        // keep the big, rarely changing libraries in their own cacheable chunks
        advancedChunks: {
          groups: [
            { name: "three", test: /node_modules[\/](three|@react-three|postprocessing|three-stdlib|maath|troika|camera-controls)/ },
            { name: "react", test: /node_modules[\/](react|react-dom|scheduler|zustand)[\/]/ },
          ],
        },
      },
    },
  },
});
