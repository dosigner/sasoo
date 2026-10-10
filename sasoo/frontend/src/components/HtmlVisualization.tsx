import { useEffect, useMemo, useRef, useState } from 'react';
import type { HtmlCheckResult, VisualizationItem } from '@/lib/api';
import { S } from '@/lib/strings';

// Allow local calculations without granting access to the app or network.
// Exports reuse it on the parent page: frame-src there blocks navigating the frame away.
export const HTML_VISUALIZATION_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'";
export const HTML_CHECK_TYPE = 'sasoo-html-check';
export const HTML_CHECK_TIMEOUT_MS = 10000;

// Execution check that runs inside the sandboxed frame before the generated code.
// It reports script errors, failed console.assert, NaN/Infinity in <output> (or
// [data-output]) elements and inputs that change nothing, after moving every
// range/number input through its range (and past it for number inputs). Each step
// waits 80 ms so debounced or animated updates are seen. Pages
// without output elements are not scanned for NaN: prose may name it. It removes its own element so the
// generated code cannot read the nonce. This finds accidental faults only: a
// hostile page could fake a pass. The sandbox and CSP are the security boundary,
// and nothing here compares results with the paper.
function checkScript(nonce: string): string {
  return `<script>(()=>{const N=${JSON.stringify(nonce)},post=parent.postMessage.bind(parent),issues=[];let sent=false,probed=0;
const send=()=>{sent=true;post({type:${JSON.stringify(HTML_CHECK_TYPE)},nonce:N,status:issues.length?"failed":"passed",issues:issues.slice(),probed},"*")};
const add=m=>{m=String(m).slice(0,200);if(issues.includes(m)||issues.length>=5)return;issues.push(m);if(sent)send()};
addEventListener("error",e=>add(e.message||"script error"));
addEventListener("unhandledrejection",e=>add("unhandled rejection: "+((e.reason&&e.reason.message)||e.reason)));
const assert=console.assert.bind(console);console.assert=(ok,...a)=>{if(!ok)add("assertion failed"+(a.length?": "+a.join(" "):""));assert(ok,...a)};
const shown=()=>[...document.querySelectorAll("output,[data-output]")].map(e=>e.textContent).join(" ");
const bad=()=>/(^|[^A-Za-z0-9_.])(NaN|-?Infinity)(?![A-Za-z0-9_])/.test(shown());
const settle=()=>new Promise(r=>setTimeout(r,80));
const fire=el=>{el.dispatchEvent(new Event("input",{bubbles:true}));el.dispatchEvent(new Event("change",{bubbles:true}))};
addEventListener("load",async()=>{await settle();if(bad())add("NaN or Infinity is shown");const before=document.body.innerHTML;let changed=false;
for(const el of document.querySelectorAll("input[type=range],input[type=number]")){const v0=el.value,lo=parseFloat(el.min),hi=parseFloat(el.max);
const vals=[lo,hi,(lo+hi)/2].filter(Number.isFinite);if(el.type==="number"&&Number.isFinite(lo)&&Number.isFinite(hi))vals.push(lo-(hi-lo||1),hi+(hi-lo||1));if(!vals.length)vals.push(Number(v0)+1);
for(const v of vals){el.value=String(v);fire(el);await settle();if(bad())add("NaN or Infinity after "+(el.id||el.name||"input")+"="+v);if(document.body.innerHTML!==before)changed=true}
el.value=v0;fire(el);await settle();probed++}
if(probed&&!changed)add("changing the inputs updated no output");send()});
document.currentScript.remove()})()</script>`;
}

export function htmlVisualizationDocument(code: string, nonce: string): string {
  return `<!doctype html><html lang="ko"><head><meta http-equiv="Content-Security-Policy" content="${HTML_VISUALIZATION_CSP}"><meta name="viewport" content="width=device-width, initial-scale=1"><style>body{margin:0;padding:16px;font-family:Arial,sans-serif;color:#172033;background:#fff}*{box-sizing:border-box}svg{max-width:100%}input,select,button{font:inherit}</style>${checkScript(nonce)}</head><body>${code}</body></html>`;
}

/** The check result in a message, or null unless it comes from this frame with this nonce. */
export function readHtmlCheck(event: MessageEvent, frame: Window | null | undefined, nonce: string): HtmlCheckResult | null {
  const data = event.data as Record<string, unknown> | null;
  if (!frame || event.source !== frame || !data || typeof data !== 'object') return null;
  if (data.type !== HTML_CHECK_TYPE || data.nonce !== nonce) return null;
  if (data.status !== 'passed' && data.status !== 'failed') return null;
  const issues = Array.isArray(data.issues)
    ? data.issues.filter((x): x is string => typeof x === 'string').slice(0, 5).map((x) => x.slice(0, 200))
    : [];
  const probed = typeof data.probed === 'number' && Number.isInteger(data.probed) && data.probed >= 0 ? data.probed : 0;
  return { status: data.status, issues, probed };
}

/** One status sentence. Never claims a check against the paper's numbers. */
export function htmlCheckText(check: HtmlCheckResult | null): string {
  const T = S.htmlCheck;
  if (!check) return T.checking;
  if (check.status === 'timeout') return T.timeout;
  if (check.status === 'failed') return T.failed;
  return check.probed > 0 ? T.passedWithInputs(check.probed) : T.passed;
}

export function HtmlVisualization({
  item,
  onCheck,
}: {
  item: VisualizationItem;
  onCheck?: (result: HtmlCheckResult) => void;
}) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const onCheckRef = useRef(onCheck);
  onCheckRef.current = onCheck;
  const [attempt, setAttempt] = useState(0);
  const code = item.html_code ?? '';
  // A new nonce per document and per retry: late messages from an old frame are ignored.
  const nonce = useMemo(() => `${crypto.randomUUID()}:${attempt}:${code.length}`, [code, attempt]);
  const [check, setCheck] = useState<HtmlCheckResult | null>(null);

  useEffect(() => {
    setCheck(null);
    let answered = false;
    const onMessage = (event: MessageEvent) => {
      const result = readHtmlCheck(event, frameRef.current?.contentWindow, nonce);
      if (!result) return;
      answered = true;
      setCheck(result);
      onCheckRef.current?.(result);
    };
    window.addEventListener('message', onMessage);
    // The frame runs in its own process, so this timer still fires when the
    // generated code never finishes; unmounting the frame then stops it.
    const timer = window.setTimeout(() => {
      if (answered) return;
      const result: HtmlCheckResult = { status: 'timeout', issues: [], probed: 0 };
      setCheck(result);
      onCheckRef.current?.(result);
    }, HTML_CHECK_TIMEOUT_MS);
    return () => {
      window.removeEventListener('message', onMessage);
      window.clearTimeout(timer);
    };
  }, [nonce]);

  const tone = check?.status === 'failed' || check?.status === 'timeout' ? 'text-danger' : 'text-fg-muted';
  return (
    <div className="space-y-2">
      <p className="text-xs text-fg-muted">{S.htmlCheck.intro}</p>
      <div role="status" aria-live="polite" className={`text-xs ${tone}`}>
        <p>{htmlCheckText(check)}</p>
        {check?.issues.length ? (
          <ul className="mt-1 list-disc pl-4 font-mono text-2xs">
            {check.issues.map((issue, i) => <li key={i}>{issue}</li>)}
          </ul>
        ) : null}
      </div>
      {check?.status === 'timeout' ? (
        <button type="button" className="btn-ghost px-2 py-1 text-2xs" onClick={() => setAttempt((n) => n + 1)}>
          {S.htmlCheck.rerun}
        </button>
      ) : (
        <iframe
          key={nonce}
          ref={frameRef}
          title={item.title}
          sandbox="allow-scripts"
          referrerPolicy="no-referrer"
          srcDoc={htmlVisualizationDocument(code, nonce)}
          className="h-[520px] w-full rounded-lg border border-border bg-white"
        />
      )}
    </div>
  );
}
