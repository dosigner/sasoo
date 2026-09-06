import { Fragment, useMemo, useState } from 'react';
import katex from 'katex';
import 'katex/dist/katex.min.css';
import type { SynthesisEquation } from '@/lib/api';
import { S } from '@/lib/strings';

const T = S.synthesis;

/** 실패해도 체인에서 버리지 않는다. 원문을 그 자리에 두기 위해 오류를 값으로 돌려준다. */
export function renderEquation(latex: string): { html: string } | { error: string } {
  try {
    return {
      html: katex.renderToString(latex, { displayMode: true, throwOnError: true, strict: 'ignore' }),
    };
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err) };
  }
}

export function EquationChain({
  equations,
  expandAll,
}: {
  equations: SynthesisEquation[];
  expandAll: boolean;
}) {
  if (equations.length === 0) return null;
  return (
    <ol className="space-y-4">
      {equations.map((eq, i) => (
        <EquationItem key={`${i}-${eq.latex.slice(0, 24)}`} eq={eq} expandAll={expandAll} />
      ))}
    </ol>
  );
}

function EquationItem({ eq, expandAll }: { eq: SynthesisEquation; expandAll: boolean }) {
  const [full, setFull] = useState(false);
  const rendered = useMemo(() => renderEquation(eq.latex), [eq.latex]);
  const symbols = eq.symbols.slice(0, 4);
  return (
    <li className="space-y-1.5">
      <div className="flex items-start gap-3">
        <div
          className="min-w-0 flex-1 overflow-x-auto text-center [&_.katex-display]:my-0"
          role="math"
          aria-label={eq.meaning}
        >
          {'html' in rendered ? (
            <div dangerouslySetInnerHTML={{ __html: rendered.html }} />
          ) : (
            <code className="block whitespace-pre-wrap break-all text-left font-mono text-xs text-fg-secondary">
              {eq.latex}
            </code>
          )}
        </div>
        {eq.paper_number && (
          <span className="shrink-0 text-2xs text-fg-muted tabular-nums">
            {T.equationNumber(eq.paper_number)}
          </span>
        )}
      </div>
      {'error' in rendered && <p className="text-2xs text-fg-muted">{T.equationRenderFailed}</p>}
      <p
        className={`cursor-text text-xs leading-relaxed text-fg-secondary ${full ? '' : 'line-clamp-2'}`}
        onClick={() => setFull((v) => !v)}
      >
        {eq.meaning}
      </p>
      {symbols.length > 0 && (
        <details open={expandAll || undefined} className="text-2xs text-fg-muted">
          <summary className="cursor-pointer select-none">{T.symbols}</summary>
          <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
            {symbols.map((s) => (
              <Fragment key={s.symbol}>
                <dt className="font-mono text-fg-secondary">{s.symbol}</dt>
                <dd className="m-0">{s.meaning}</dd>
              </Fragment>
            ))}
          </dl>
        </details>
      )}
    </li>
  );
}
