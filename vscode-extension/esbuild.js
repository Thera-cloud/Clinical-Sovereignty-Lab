const esbuild = require('esbuild');
const path = require('path');
const fs = require('fs');

const production = process.argv.includes('--production');
const watch = process.argv.includes('--watch');

const extensionConfig = {
  entryPoints: ['./src/extension.ts'],
  bundle: true,
  outfile: './dist/extension.js',
  external: ['vscode'],
  format: 'cjs',
  platform: 'node',
  target: 'node18',
  sourcemap: !production,
  minify: production,
  define: {
    'process.env.NODE_ENV': production ? '"production"' : '"development"',
  },
};

const webviewConfig = {
  entryPoints: ['./src/webview/chat.js'],
  bundle: true,
  outfile: './dist/webview/chat.js',
  format: 'iife',
  platform: 'browser',
  target: 'es2020',
  sourcemap: !production,
  minify: production,
  loader: {
    '.css': 'text',
  },
};

async function copyWebviewAssets() {
  const srcDir = path.join(__dirname, 'src', 'webview');
  const distDir = path.join(__dirname, 'dist', 'webview');
  fs.mkdirSync(distDir, { recursive: true });

  for (const file of ['chat.html', 'chat.css']) {
    const src = path.join(srcDir, file);
    const dst = path.join(distDir, file);
    if (fs.existsSync(src)) {
      fs.copyFileSync(src, dst);
    }
  }
}

async function main() {
  if (watch) {
    const extCtx = await esbuild.context(extensionConfig);
    const webCtx = await esbuild.context(webviewConfig);
    await Promise.all([extCtx.watch(), webCtx.watch()]);
    await copyWebviewAssets();
    console.log('[watch] Build complete. Watching for changes...');
  } else {
    await esbuild.build(extensionConfig);
    await esbuild.build(webviewConfig);
    await copyWebviewAssets();
    console.log(`[build] ${production ? 'Production' : 'Development'} build complete.`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
