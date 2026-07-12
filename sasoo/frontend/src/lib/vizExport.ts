// Bulk export of a paper's visualizations as a zip:
//   images/NN_title.png   — rendered Mermaid diagrams + PaperBanana images
//   sources/NN_title.mmd  — Mermaid source per diagram
//   README.md             — shareable index with titles, descriptions, images
//
// Loaded via dynamic import so mermaid/jszip stay out of the main bundle.

import JSZip from 'jszip';
import { getStaticUrl, type VisualizationItem } from '@/lib/api';
import {
  downloadBlob,
  renderMermaidSvg,
  safeFilename,
  svgToPngBlob,
} from '@/components/MermaidRenderer';

export interface VizExportResult {
  exported: number;
  skipped: number;
}

export async function exportVisualizationsZip(
  paperId: number,
  items: VisualizationItem[]
): Promise<VizExportResult> {
  const zip = new JSZip();
  const images = zip.folder('images');
  const sources = zip.folder('sources');
  if (!images || !sources) throw new Error('zip init failed');

  const mdLines: string[] = [`# 시각화 모음 — Paper #${paperId}`, ''];
  let exported = 0;
  let skipped = 0;

  for (const item of items) {
    const base = `${String(item.id).padStart(2, '0')}_${safeFilename(item.title)}`;
    let imageName: string | null = null;

    try {
      if (item.tool === 'mermaid' && item.mermaid_code) {
        sources.file(`${base}.mmd`, item.mermaid_code);
        const rendered = await renderMermaidSvg(item.mermaid_code);
        if ('svg' in rendered) {
          const blob = await svgToPngBlob(rendered.svg);
          if (blob) {
            imageName = `${base}.png`;
            images.file(imageName, blob);
          }
        }
      } else if (item.tool === 'paperbanana' && item.image_url) {
        const response = await fetch(getStaticUrl(item.image_url));
        if (response.ok) {
          imageName = `${base}.png`;
          images.file(imageName, await response.blob());
        }
      }
    } catch (err) {
      console.warn(`viz export: item ${item.id} failed`, err);
    }

    if (imageName) {
      exported += 1;
      mdLines.push(`## ${item.id}. ${item.title}`, '');
      if (item.description) mdLines.push(item.description, '');
      mdLines.push(`![${item.title}](images/${imageName})`, '');
    } else {
      skipped += 1;
    }
  }

  if (exported === 0) throw new Error('no visualizations could be exported');

  zip.file('README.md', mdLines.join('\n'));
  const blob = await zip.generateAsync({ type: 'blob' });
  downloadBlob(`paper_${paperId}_visualizations.zip`, blob);
  return { exported, skipped };
}
