import { useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowRight } from 'lucide-react';
import type { SynthesisResult } from '@/lib/api';
import { formatMetricValue } from '@/lib/synthesisBlocks';
import { S } from '@/lib/strings';

const T = S.synthesis;

export function BlockSection({
  icon,
  title,
  meta,
  children,
}: {
  icon: ReactNode;
  title: string;
  meta?: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-3">
      <header className="flex items-center gap-2">
        {icon}
        <h3 className="text-sm font-semibold text-fg">{title}</h3>
        {meta && <span className="ml-auto text-2xs text-fg-muted tabular-nums">{meta}</span>}
      </header>
      {children}
    </section>
  );
}

function ClampText({
  text,
  lines,
  className = '',
}: {
  text: string;
  lines: 2 | 3;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <p
      className={`cursor-text ${open ? '' : lines === 2 ? 'line-clamp-2' : 'line-clamp-3'} ${className}`}
      onClick={() => setOpen((v) => !v)}
      title={open ? T.less : T.more}
    >
      {text}
    </p>
  );
}

/** 요약 카드: 문장 2개와 핵심 수치 타일 최대 3개. 타일은 칩이 아니다(PR #43 계약). */
export function SummaryBlock({ synthesis }: { synthesis: SynthesisResult }) {
  const metrics = synthesis.key_metrics.slice(0, 3);
  return (
    <div className="card space-y-3">
      <ClampText text={synthesis.problem_sentence} lines={2} className="text-[15px] leading-relaxed text-fg" />
      <ClampText text={synthesis.method_sentence} lines={2} className="text-[15px] leading-relaxed text-fg" />
      {metrics.length > 0 && (
        <div className="flex flex-wrap gap-x-8 gap-y-3 pt-1">
          {metrics.map((m, i) => (
            <div key={`${m.label}-${i}`} className="flex flex-col" title={m.evidence}>
              <span className="text-xl font-semibold leading-none tabular-nums text-fg">{formatMetricValue(m)}</span>
              <span className="mt-1 text-2xs text-fg-muted">{m.label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const asText = (v: unknown): string =>
  typeof v === 'string' ? v.trim() : Array.isArray(v) ? v.filter((x) => typeof x === 'string').join('\n') : '';

export function problemFields(deepDive: Record<string, unknown> | null) {
  return {
    asIs: asText(deepDive?.as_is),
    toBe: asText(deepDive?.to_be),
    solution: asText(deepDive?.solution),
  };
}

/** 문제와 기여: as_is와 to_be 2열, 패널이 좁으면 컨테이너 쿼리로 1열(스펙 §3.2). */
export function ProblemBlock({ deepDive }: { deepDive: Record<string, unknown> | null }) {
  const { asIs, toBe, solution } = problemFields(deepDive);
  if (!asIs && !toBe) return null;
  return (
    <div className="@container">
      <div className="grid grid-cols-1 gap-3 @[560px]:grid-cols-2">
        {[
          { label: T.asIs, text: asIs },
          { label: T.toBe, text: toBe },
        ].map(({ label, text }) => (
          <div key={label} className="card">
            <p className="mb-1 text-2xs tracking-[0.06em] text-fg-muted">{label}</p>
            {text ? (
              <ClampText text={text} lines={3} className="text-xs leading-relaxed text-fg-secondary" />
            ) : (
              <p className="text-xs text-fg-muted">-</p>
            )}
          </div>
        ))}
      </div>
      {solution && (
        <div className="mt-3 flex items-start gap-2 text-xs leading-relaxed text-fg-secondary">
          <span className="shrink-0 font-medium text-fg">{T.solution}</span>
          <ClampText text={solution} lines={2} className="min-w-0 flex-1" />
        </div>
      )}
    </div>
  );
}

/** 재현 핵심: 이름, 값+단위, 비고(있을 때만) 최대 5행과 레시피 탭 링크(스펙 §3.5). */
export function ReproductionBlock({
  rows,
  showNotes,
  onOpenRecipe,
}: {
  rows: { name: string; value: string; notes: string }[];
  showNotes: boolean;
  onOpenRecipe: () => void;
}) {
  return (
    <div className="card overflow-hidden p-0">
      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-2xs text-fg-muted">
                <th className="px-4 py-2 font-medium">{T.parameter}</th>
                <th className="px-4 py-2 font-medium">{T.value}</th>
                {showNotes && <th className="px-4 py-2 font-medium">{T.notes}</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.name} className="border-t border-border/50">
                  <td className="px-4 py-2 text-fg">{r.name}</td>
                  <td className="px-4 py-2 tabular-nums text-fg-secondary">{r.value}</td>
                  {showNotes && <td className="px-4 py-2 text-fg-muted">{r.notes}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <button
        type="button"
        className="flex w-full items-center gap-1 border-t border-border/50 px-4 py-2 text-left text-2xs text-accent transition hover:bg-surface-hover"
        onClick={onOpenRecipe}
      >
        {T.viewInRecipe}
        <ArrowRight className="h-3 w-3" />
      </button>
    </div>
  );
}
