// @vitest-environment jsdom
import JSZip from 'jszip';
import { expect, it, vi } from 'vitest';
import type { VisualizationItem } from './api';

const downloads = vi.hoisted(() => [] as Blob[]);
vi.mock('./download', () => ({ downloadBlob: (_name: string, blob: Blob) => downloads.push(blob) }));
vi.mock('@/components/MermaidRenderer', () => ({
  renderMermaidSvg: vi.fn(),
  safeFilename: (title: string) => title.replace(/\s+/g, '_'),
  svgToPngBlob: vi.fn(),
}));

const { exportVisualizationsZip } = await import('./vizExport');

it('exports HTML with a parent policy that blocks frame navigation', async () => {
  // Given
  const item = {
    id: 1, title: '변수 관계', tool: 'html', diagram_type: 'interactive', description: '',
    category: '', mermaid_code: null, image_url: null, image_path: null, status: 'completed',
    html_code: '<input type="range"><script>location.href="https://probe.invalid/?d=1"</script>',
  } as VisualizationItem;

  // When
  await exportVisualizationsZip(7, [item]);
  const zip = await JSZip.loadAsync(await downloads[0].arrayBuffer());
  const html = await zip.file('sources/01_변수_관계.html')!.async('string');
  const doc = new DOMParser().parseFromString(html, 'text/html');

  // Then
  const policy = doc.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute('content') ?? '';
  expect(policy).toContain("frame-src 'none'");
  expect(policy).toContain("form-action 'none'");
  const frame = doc.querySelector('iframe');
  expect(frame?.getAttribute('sandbox')).toBe('allow-scripts');
  expect(policy && frame && doc.querySelector('meta[http-equiv]')!.compareDocumentPosition(frame))
    .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  expect(frame?.getAttribute('srcdoc')).toContain('probe.invalid');
});
