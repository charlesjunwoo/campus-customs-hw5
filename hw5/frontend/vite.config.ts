import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dashboard talks to the FastAPI backend at http://localhost:8000 (CORS allows this origin).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
});
