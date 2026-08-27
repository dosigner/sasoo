// Single anchor-click download path for the whole app.
//
// Two details matter and were previously only honoured on the Mermaid path:
// the anchor has to be in the document, and the object URL has to outlive the
// click. Chromium starts the download asynchronously, so revoking in the same
// tick can invalidate the blob before the download ever picks it up.
export function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Filename stem for a saved asset. \p{L}/\p{N} keeps 한글 that ASCII-only \w drops. */
export function safeAssetFilename(name: string | null | undefined, fallback: string): string {
  const cleaned = (name || '')
    .replace(/[^\p{L}\p{N}._-]+/gu, '_')
    .replace(/^_+|_+$/g, '');
  return cleaned || fallback;
}

/**
 * Extension from an asset path, minus any query/hash the backend appended.
 * A path with no dot has no extension: splitting on '.' there would otherwise
 * hand back the whole path and produce filenames like "그림_1./static/a/b".
 */
export function assetExtension(path: string | null | undefined, fallback = 'png'): string {
  const base = (path || '').split(/[?#]/)[0].split('/').pop() || '';
  const dot = base.lastIndexOf('.');
  return (dot > 0 ? base.slice(dot + 1) : '') || fallback;
}
