type BrowserEffectGuard = { assertCurrent: () => void };

function downloadBrowserFile(blob: Blob, filename: string, guard: BrowserEffectGuard) {
  guard.assertCurrent();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.hidden = true;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

async function writeBrowserClipboard(content: string, guard: BrowserEffectGuard) {
  guard.assertCurrent();
  if (!navigator.clipboard?.writeText) throw new Error("Clipboard non disponibile");
  await navigator.clipboard.writeText(content);
  guard.assertCurrent();
}

async function writeBrowserClipboardIfAvailable(content: string, guard: BrowserEffectGuard) {
  guard.assertCurrent();
  if (!navigator.clipboard?.writeText) return;
  await navigator.clipboard.writeText(content);
  guard.assertCurrent();
}

function navigateBrowser(destination: string, guard: BrowserEffectGuard) {
  guard.assertCurrent();
  window.location.assign(destination);
}

export {
  downloadBrowserFile,
  navigateBrowser,
  writeBrowserClipboard,
  writeBrowserClipboardIfAvailable,
};
export type { BrowserEffectGuard };
