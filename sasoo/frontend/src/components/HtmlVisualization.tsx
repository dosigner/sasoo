import type { VisualizationItem } from '@/lib/api';

// Allow local calculations without granting access to the app or network.
const CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'";
const ERROR_HANDLER = `<script>function showError(){if(document.querySelector('[data-html-error]'))return;const p=document.createElement('p');p.dataset.htmlError='true';p.setAttribute('role','alert');p.textContent='계산 실행에 오류가 있어요. 다시 생성한 뒤 확인하세요.';p.style.color='#b42318';document.body.prepend(p)}addEventListener('error',showError);addEventListener('unhandledrejection',showError)</script>`;

export function htmlVisualizationDocument(code: string): string {
  return `<!doctype html><html lang="ko"><head><meta http-equiv="Content-Security-Policy" content="${CSP}"><meta name="viewport" content="width=device-width, initial-scale=1"><style>body{margin:0;padding:16px;font-family:Arial,sans-serif;color:#172033;background:#fff}*{box-sizing:border-box}svg{max-width:100%}input,select,button{font:inherit}</style></head><body>${ERROR_HANDLER}${code}</body></html>`;
}

export function HtmlVisualization({ item }: { item: VisualizationItem }) {
  return (
    <div className="space-y-2">
      <p className="text-xs text-fg-muted">변수와 결과의 관계를 확인하는 설명용 계산입니다. 적용 가정과 원문 근거를 함께 확인하세요.</p>
      <iframe
        title={item.title}
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        srcDoc={htmlVisualizationDocument(item.html_code ?? '')}
        className="h-[520px] w-full rounded-lg border border-border bg-white"
      />
    </div>
  );
}
