import { renderToStaticMarkup } from 'react-dom/server';
import { Markdown } from '@/components/Markdown';
import { downloadBlob, safeAssetFilename } from './download';

interface ReportContent {
  title: string;
  markdown: string;
}

export function buildReportHtml(report: ReportContent): string {
  const html = renderToStaticMarkup(
    <html lang="ko">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>{report.title}</title>
        <style>{`
          :root { color-scheme: light dark; }
          body { font-family: Pretendard, system-ui, sans-serif; max-width: 44rem; margin: 2rem auto; padding: 0 1rem; font-size: .9375rem; line-height: 1.625rem; overflow-wrap: anywhere; word-break: keep-all; }
          strong, h1, h2, h3, h4 { font-weight: 650; }
          h1 { font-size: 1.5rem; line-height: 2rem; }
          h2 { font-size: 1.25rem; } h3 { font-size: 1.0625rem; }
          h2, h3, h4 { margin: 1.5rem 0 .5rem; }
          p { margin: 0 0 .75rem; }
          pre, table, .katex-display { display: block; max-width: 100%; overflow-x: auto; }
          pre { padding: 1rem; border: 1px solid GrayText; border-radius: .75rem; }
          code { font-size: .8125rem; line-height: 1.25rem; word-break: normal; }
          th, td { padding: .5rem; border-bottom: 1px solid GrayText; text-align: left; }
          blockquote { border-left: 2px solid GrayText; margin-left: 0; padding-left: 1rem; font-style: normal; }
          .katex-html { display: none; }
        `}</style>
      </head>
      <body><main><Markdown>{report.markdown}</Markdown></main></body>
    </html>,
  );
  // React hoists image preloads before JSX CSP metadata.
  return '<!doctype html>' + html.replace(
    '<head>',
    `<head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"/>`,
  );
}

export function downloadReport(report: ReportContent, format: 'md' | 'html'): void {
  const content = format === 'html' ? buildReportHtml(report) : report.markdown;
  const type = format === 'html' ? 'text/html;charset=utf-8' : 'text/markdown;charset=utf-8';
  downloadBlob(`${safeAssetFilename(report.title, 'Sasoo-report')}.${format}`, new Blob([content], { type }));
}
