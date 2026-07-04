import { resolve } from 'path';
import { defineConfig } from 'vite';
import { copyFileSync, mkdirSync, cpSync, existsSync } from 'fs';

/**
 * Vite config for RAMP Chrome Extension (Manifest V3).
 *
 * Bundles JS entry points and copies static assets to dist/.
 * Chrome extensions use JS entry points (not HTML), so we use
 * rollup's multi-entry input config.
 */

// Plugin to copy static assets (manifest.json, popup.html, icons) to dist/
function copyStaticAssets() {
  return {
    name: 'copy-extension-assets',
    closeBundle() {
      const dist = resolve(__dirname, 'dist');

      // Copy manifest.json
      copyFileSync(
        resolve(__dirname, 'manifest.json'),
        resolve(dist, 'manifest.json')
      );

      // Copy popup HTML
      mkdirSync(resolve(dist, 'popup'), { recursive: true });
      const popupHtml = resolve(__dirname, 'popup/popup.html');
      if (existsSync(popupHtml)) {
        copyFileSync(popupHtml, resolve(dist, 'popup/popup.html'));
      }

      // Copy assets directory (icons)
      const assetsDir = resolve(__dirname, 'assets');
      if (existsSync(assetsDir)) {
        cpSync(assetsDir, resolve(dist, 'assets'), { recursive: true });
      }
    }
  };
}

export default defineConfig({
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // No minification for easier debugging during development
    // Switch to true for production Chrome Web Store builds
    minify: false,
    rollupOptions: {
      input: {
        'background/service-worker': resolve(__dirname, 'background/service-worker.js'),
        'content/reddit-selectors': resolve(__dirname, 'content/reddit-selectors.js'),
        'content/reddit-actions': resolve(__dirname, 'content/reddit-actions.js'),
        'popup/popup': resolve(__dirname, 'popup/popup.js'),
      },
      output: {
        // Preserve directory structure matching manifest.json references
        entryFileNames: '[name].js',
        chunkFileNames: 'shared/[name].js',
        assetFileNames: 'assets/[name].[ext]',
        // Chrome MV3 service workers must be a single file (no dynamic imports)
        // Use inlineDynamicImports only when there's a single input
        // For multiple inputs, ensure no code splitting for service worker
      },
    },
  },
  plugins: [copyStaticAssets()],
});
