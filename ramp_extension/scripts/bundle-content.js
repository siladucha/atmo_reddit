/**
 * Bundles content script modules into a single file for Chrome MV3.
 * Chrome content scripts don't support ES modules, so we concatenate
 * the files and strip `export` keywords.
 *
 * Source files (order matters):
 *   1. content/reddit-selectors.js (variant detection + selectors)
 *   2. content/reddit-username.js  (username detection)
 *   3. content/reddit-actions.js   (message handler + task execution)
 *
 * Output: content/bundle.js
 */

const fs = require('fs');
const path = require('path');

const contentDir = path.join(__dirname, '..', 'content');

const FILES = [
  'reddit-selectors.js',
  'reddit-username.js',
  'banner-dismiss.js',
  'draft-cleanup.js',
  'reddit-actions.js',
];

let bundle = '// Auto-generated bundle — do not edit directly.\n';
bundle += '// Run: npm run bundle\n\n';

for (const file of FILES) {
  const filePath = path.join(contentDir, file);
  let content = fs.readFileSync(filePath, 'utf-8');

  // Strip ES module export keywords (content scripts are not modules)
  content = content
    .replace(/^export function /gm, 'function ')
    .replace(/^export async function /gm, 'async function ')
    .replace(/^export const /gm, 'const ')
    .replace(/^export let /gm, 'let ')
    .replace(/^export \{[^}]*\};?\s*$/gm, '');

  bundle += `// ── ${file} ${'─'.repeat(60 - file.length)}\n\n`;
  bundle += content;
  bundle += '\n\n';
}

const outputPath = path.join(contentDir, 'bundle.js');
fs.writeFileSync(outputPath, bundle);
console.log(`✓ Bundled ${FILES.length} files → content/bundle.js (${bundle.length} bytes)`);
