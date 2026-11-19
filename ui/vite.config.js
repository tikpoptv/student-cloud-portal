import {defineConfig} from 'vite';
import tailwindcss from '@tailwindcss/vite';
import {fileURLToPath} from 'node:url';
export default defineConfig({
  root:fileURLToPath(new URL('.',import.meta.url)),
  base:'/static/ui/', plugins:[tailwindcss()],
  build:{outDir:'../static/ui',emptyOutDir:true,
    rollupOptions:{input:fileURLToPath(new URL('src/main.jsx',import.meta.url)),output:{entryFileNames:'app.js',chunkFileNames:'[name]-[hash].js',assetFileNames:'[name][extname]'}}}
});
