import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function loadGalaxzApiKey() {
  if (process.env.GALAXZ_API_KEY) return process.env.GALAXZ_API_KEY;

  const envPath = path.resolve(__dirname, '..', '.env');
  if (!fs.existsSync(envPath)) return '';

  const line = fs
    .readFileSync(envPath, 'utf8')
    .split(/\r?\n/)
    .find((entry) => entry.trim().startsWith('GALAXZ_API_KEY='));

  if (!line) return '';
  return line.slice('GALAXZ_API_KEY='.length).trim().replace(/^["']|["']$/g, '');
}

const galaxzApiKey = loadGalaxzApiKey();

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    open: true,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://localhost:8001',
        changeOrigin: true,
        headers: galaxzApiKey ? { Authorization: `Bearer ${galaxzApiKey}` } : undefined,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});
