import { ChevronDown } from 'lucide-react';

import { Markdown } from '@/components/Markdown';
import { AppIcon } from '@/components/icons';
import type { ReviewMap } from '@/lib/api';
import { S } from '@/lib/strings';

const CARD = 'border border-border/45 bg-surface/40 px-3.5';
const CARD_STYLE = { borderRadius: 'var(--radius-surface)' } as const;

function Title({ children }: { children: string }) {
  return <h3 className="mb-2 font-[650] text-fg">{children}</h3>;
}

function Field({ label, text }: { label: string; text: string }) {
  if (!text.trim()) return null;
  return (
    <div className="mt-2 [&_p:last-child]:mb-0">
      <p className="mb-0.5 text-xs font-medium text-fg-muted">{label}</p>
      <Markdown>{text}</Markdown>
    </div>
  );
}

/** Review 논문의 deep_dive 대체 결과. 대분야, 파트별 지도, 앞으로의 과제, 읽는 순서를 그린다. */
export default function ReviewMapView({
  reviewMap,
  onJumpToPage,
}: {
  reviewMap: ReviewMap;
  onJumpToPage?: (page: number) => void;
}) {
  const parts = Array.isArray(reviewMap.parts) ? reviewMap.parts : [];
  const future = Array.isArray(reviewMap.future_directions) ? reviewMap.future_directions : [];
  const paths = Array.isArray(reviewMap.reading_paths) ? reviewMap.reading_paths : [];

  return (
    <div className="reading-prose space-y-5">
      <div className="workbench-tab-heading">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <AppIcon name="library" className="h-4 w-4 text-accent" />
            <h3 className="text-lg font-semibold text-fg">{S.reviewMap.tabLabel}</h3>
          </div>
          <p className="mt-1 text-xs text-fg-muted">{S.reviewMap.intro}</p>
        </div>
      </div>

      {typeof reviewMap.field_overview === 'string' && reviewMap.field_overview.trim() && (
        <section>
          <Title>{S.reviewMap.fieldTitle}</Title>
          <div className={`${CARD} py-3 [&_p:last-child]:mb-0`} style={CARD_STYLE}>
            <Markdown>{reviewMap.field_overview}</Markdown>
          </div>
        </section>
      )}

      {parts.length > 0 && (
        <section>
          <Title>{S.reviewMap.partsTitle}</Title>
          <div className={CARD} style={CARD_STYLE}>
            {parts.map((part, index) => {
              const page = typeof part.page === 'number' ? part.page : null;
              return (
                <details key={`${part.title}-${index}`} open={index === 0}
                  className="group/part border-b border-border/45 pb-2 last:border-b-0">
                  <summary className="flex min-h-8 cursor-pointer list-none items-center justify-between gap-2 py-2.5 focus-visible:outline-2 focus-visible:outline-accent [&::-webkit-details-marker]:hidden">
                    <span className="min-w-0">
                      <span className="block font-[650] text-fg">{part.title}</span>
                      {part.subfield && <span className="block text-sm text-fg-muted">{part.subfield}</span>}
                    </span>
                    <span className="flex shrink-0 items-center gap-1.5">
                      {page !== null && (
                        <button
                          type="button"
                          title={S.reviewMap.pageJump(page)}
                          onClick={(event) => {
                            // summary 안의 클릭은 기본 동작이 아코디언 토글이라 막는다.
                            event.preventDefault();
                            event.stopPropagation();
                            onJumpToPage?.(page);
                          }}
                          className="min-h-8 px-1.5 py-0.5 text-sm text-fg-muted tabular-nums transition-colors duration-150 hover:text-accent focus:outline-hidden focus-visible:ring-2 focus-visible:ring-accent"
                          style={{ borderRadius: 'var(--radius-control)' }}
                        >
                          {S.reviewMap.pageLabel(page)}
                        </button>
                      )}
                      <ChevronDown className="h-3.5 w-3.5 text-fg-muted group-open/part:rotate-180" />
                    </span>
                  </summary>
                  <Field label={S.reviewMap.summary} text={part.summary ?? ''} />
                  <Field label={S.reviewMap.development} text={part.development ?? ''} />
                  <Field label={S.reviewMap.takeaway} text={part.takeaway ?? ''} />
                </details>
              );
            })}
          </div>
        </section>
      )}

      {future.length > 0 && (
        <section>
          <Title>{S.reviewMap.futureTitle}</Title>
          <div className="space-y-2">
            {future.map((item, index) => (
              <article key={index} className={`${CARD} py-3`} style={CARD_STYLE}>
                <Field label={S.reviewMap.need} text={item.need ?? ''} />
                <Field label={S.reviewMap.research} text={item.research ?? ''} />
              </article>
            ))}
          </div>
        </section>
      )}

      {paths.length > 0 && (
        <section>
          <Title>{S.reviewMap.pathsTitle}</Title>
          <div className="space-y-2">
            {paths.map((path, index) => (
              <article key={index} className={`${CARD} py-3`} style={CARD_STYLE}>
                <h4 className="font-[650] text-fg">{path.goal}</h4>
                <ol className="mt-1.5 list-decimal pl-5 text-fg">
                  {(Array.isArray(path.order) ? path.order : []).map((title, step) => (
                    <li key={step}>{title}</li>
                  ))}
                </ol>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
