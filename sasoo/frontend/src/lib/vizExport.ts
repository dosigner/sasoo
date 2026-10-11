// Bulk export of a paper's visualizations as a zip:
//   images/NN_title.png   — rendered Mermaid diagrams + PaperBanana images
//   sources/NN_title.mmd  — Mermaid source per diagram
//   README.md             — shareable index with titles, descriptions, images
//
// Loaded via dynamic import so mermaid/jszip stay out of the main bundle.

import JSZip from 'jszip';
import { getStaticUrl, type VisualizationItem } from '@/lib/api';
import { downloadBlob } from '@/lib/download';
import {
  HTML_CHECK_TIMEOUT_MS,
  HTML_CHECK_TYPE,
  HTML_VISUALIZATION_CSP,
  htmlCheckText,
  htmlVisualizationDocument,
} from '@/components/HtmlVisualization';
import {
  renderMermaidSvg,
  safeFilename,
  svgToPngBlob,
} from '@/components/MermaidRenderer';

export interface VizExportResult {
  exported: number;
  skipped: number;
}

// Standalone page around the sandboxed frame. It shows the same execution check
// as the app: only messages from its own frame with its nonce count, and a frame
// that never answers is removed so a runaway loop stops.
function exportedHtmlPage(code: string): string {
  const nonce = crypto.randomUUID();
  const frameDoc = htmlVisualizationDocument(code, nonce)
    .replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;');
  const text = {
    passed: htmlCheckText({ status: 'passed', issues: [], probed: 0 }),
    failed: htmlCheckText({ status: 'failed', issues: [], probed: 0 }),
    timeout: htmlCheckText({ status: 'timeout', issues: [], probed: 0 }),
  };
  const listener = `(()=>{const N=${JSON.stringify(nonce)},T=${JSON.stringify(text).replaceAll('<', '\\u003c')},f=document.getElementById("f"),s=document.getElementById("s");let done=false;
addEventListener("message",e=>{const d=e.data;if(e.source!==f.contentWindow||!d||d.type!==${JSON.stringify(HTML_CHECK_TYPE)}||d.nonce!==N||(d.status!=="passed"&&d.status!=="failed"))return;done=true;
s.textContent=T[d.status]+(Array.isArray(d.issues)&&d.issues.length?" ("+d.issues.slice(0,5).map(String).join("; ").slice(0,600)+")":"");s.style.color=d.status==="failed"?"#b42318":"#475467"});
setTimeout(()=>{if(!done){s.textContent=T.timeout;s.style.color="#b42318";f.remove()}},${HTML_CHECK_TIMEOUT_MS})})()`;
  return `<!doctype html><html lang="ko"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${HTML_VISUALIZATION_CSP}"><title>변수와 결과</title><p id="s" role="status" aria-live="polite" style="font:14px Arial,sans-serif;color:#475467">${htmlCheckText(null)}</p><iframe id="f" title="변수와 결과" sandbox="allow-scripts" referrerpolicy="no-referrer" style="border:0;width:100%;height:90vh" srcdoc="${frameDoc}"></iframe><script>${listener}</script></html>`;
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
      } else if (item.tool === 'html' && item.html_code) {
        sources.file(`${base}.html`, exportedHtmlPage(item.html_code));
        exported += 1;
        mdLines.push(`## ${item.id}. ${item.title}`, '', item.description, '', `[HTML 설명](sources/${base}.html)`, '');
        continue;
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
