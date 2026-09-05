import { useMemo, useState, type ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';

import { Markdown } from '@/components/Markdown';
import { AppIcon } from '@/components/icons';
import { ContentState, Modal } from '@/components/ui';
import { useReadingGuide } from '@/hooks/useReadingGuide';
import { S } from '@/lib/strings';
import {
  glossarySearchTerm,
  type GlossaryEntry,
  type GuideSection,
  type PrerequisiteEntry,
} from '@/lib/readingGuide';

// 표기 사전 한 줄은 버튼 안에 들어가므로 문단 태그를 벗기고 인라인(수식 포함)으로만 그린다.
const INLINE_MARKDOWN = { p: ({ children }: { children?: ReactNode }) => <>{children}</> };

interface ReadingGuideTabProps {
  paperId: string | null;
  level?: string | null;
  onJumpToPage?: (page: number) => void;
  onSearchInPdf?: (term: string, page: number | null) => void;
}

function formatCreatedAt(createdAt: number): string {
  return new Date(createdAt).toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

function levelLabelOf(level: string | null | undefined): string | null {
  if (!level) return null;
  const levels = S.levels as Record<string, { label: string } | undefined>;
  return levels[level]?.label ?? null;
}

function SectionTitle({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="mb-2 flex items-baseline gap-2">
      <h4 className="text-xs font-[650] text-fg">{title}</h4>
      {hint && <span className="text-2xs font-normal text-fg-muted">{hint}</span>}
    </div>
  );
}

function GlossaryList({
  entries,
  onJumpToPage,
  onSearchInPdf,
}: {
  entries: GlossaryEntry[];
  onJumpToPage?: (page: number) => void;
  onSearchInPdf?: (term: string, page: number | null) => void;
}) {
  const [filter, setFilter] = useState('');
  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return entries;
    return entries.filter(
      (entry) =>
        entry.symbol.toLowerCase().includes(needle) ||
        entry.meaning.toLowerCase().includes(needle),
    );
  }, [entries, filter]);

  return (
    <section>
      <SectionTitle title={S.readingGuide.glossaryTitle} hint={S.readingGuide.glossaryHint} />
      <input
        type="search"
        value={filter}
        onChange={(event) => setFilter(event.target.value)}
        placeholder={S.readingGuide.glossaryFilter}
        aria-label={S.readingGuide.glossaryFilter}
        className="input py-1.5 text-xs"
      />
      {visible.length === 0 ? (
        <p className="mt-3 text-xs text-fg-muted">{S.readingGuide.glossaryEmpty}</p>
      ) : (
        <ul className="mt-2">
          {visible.map((entry, index) => {
            const term = glossarySearchTerm(entry.symbol);
            const canJump = term !== null || entry.page !== null;
            return (
              <li key={`${entry.symbol}-${index}`}>
                <button
                  type="button"
                  disabled={!canJump}
                  onClick={() => {
                    if (term) onSearchInPdf?.(term, entry.page);
                    else if (entry.page !== null) onJumpToPage?.(entry.page);
                  }}
                  className="flex w-full items-baseline gap-3 px-2 py-1.5 text-left transition-colors duration-150 hover:bg-surface-hover focus:outline-hidden focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-default disabled:hover:bg-transparent"
                  style={{ borderRadius: 'var(--radius-control)' }}
                >
                  <span className="shrink-0 font-mono text-xs font-[650] text-fg">
                    <Markdown components={INLINE_MARKDOWN}>{entry.symbol}</Markdown>
                  </span>
                  <span className="min-w-0 flex-1 text-xs font-normal text-fg-secondary">
                    <Markdown components={INLINE_MARKDOWN}>{entry.meaning}</Markdown>
                  </span>
                  {entry.page !== null && (
                    <span className="shrink-0 text-2xs text-fg-muted tabular-nums">
                      {S.readingGuide.pageLabel(entry.page)}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function PrerequisiteCards({ entries }: { entries: PrerequisiteEntry[] }) {
  return (
    <section>
      <SectionTitle title={S.readingGuide.prerequisitesTitle} />
      <div className="space-y-2">
        {entries.map((entry, index) => (
          <article
            key={`${entry.name}-${index}`}
            className="border border-border/45 bg-surface/40 px-3.5 py-3"
            style={{ borderRadius: 'var(--radius-surface)' }}
          >
            <h5 className="text-xs font-[650] text-fg">{entry.name}</h5>
            {entry.primer && (
              <p className="mt-1.5 text-xs font-normal leading-relaxed text-fg-secondary">
                {entry.primer}
              </p>
            )}
            {entry.why && (
              <p className="mt-1.5 text-2xs leading-relaxed text-fg-muted">
                <span className="font-medium">{S.readingGuide.prerequisitesWhy}</span> {entry.why}
              </p>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function SectionAccordion({
  sections,
  onJumpToPage,
}: {
  sections: GuideSection[];
  onJumpToPage?: (page: number) => void;
}) {
  return (
    <section>
      <SectionTitle title={S.readingGuide.sectionsTitle} />
      <div
        className="border border-border/45 bg-surface/40 px-3.5"
        style={{ borderRadius: 'var(--radius-surface)' }}
      >
        {sections.map((section, index) => {
          const page = section.page;
          return (
            <details
              key={`${section.title}-${index}`}
              className="group/guide border-b border-border/45 last:border-b-0"
            >
              <summary className="flex cursor-pointer list-none items-center justify-between gap-2 py-2.5 [&::-webkit-details-marker]:hidden">
                <span className="min-w-0 text-xs font-[650] text-fg">{section.title}</span>
                <span className="flex shrink-0 items-center gap-1.5">
                  {page !== null && (
                    <button
                      type="button"
                      title={S.readingGuide.pageJump(page)}
                      onClick={(event) => {
                        // summary 안의 클릭은 기본 동작이 아코디언 토글이라 막는다.
                        event.preventDefault();
                        event.stopPropagation();
                        onJumpToPage?.(page);
                      }}
                      className="px-1.5 py-0.5 text-2xs text-fg-muted tabular-nums transition-colors duration-150 hover:text-accent focus:outline-hidden focus-visible:ring-2 focus-visible:ring-accent"
                      style={{ borderRadius: 'var(--radius-control)' }}
                    >
                      {S.readingGuide.pageLabel(page)}
                    </button>
                  )}
                  <ChevronDown className="h-3.5 w-3.5 text-fg-muted transition-transform duration-150 group-open/guide:rotate-180" />
                </span>
              </summary>
              {section.body && (
                <div className="analysis-content pb-1 [&_p:last-child]:mb-0">
                  <Markdown>{section.body}</Markdown>
                </div>
              )}
            </details>
          );
        })}
      </div>
    </section>
  );
}

export default function ReadingGuideTab({
  paperId,
  level,
  onJumpToPage,
  onSearchInPdf,
}: ReadingGuideTabProps) {
  const { status, guide, meta, streamText, error, levelMismatch, generate, cancel } =
    useReadingGuide(paperId, level);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const isRegenerate = status === 'ready';
  const confirmModal = (
    <Modal open={confirmOpen} onClose={() => setConfirmOpen(false)}>
      <h3 className="mb-2 text-lg font-[650] text-fg">
        {isRegenerate ? S.readingGuide.regenerateTitle : S.readingGuide.confirmTitle}
      </h3>
      <div className="mb-4 space-y-1 text-sm text-fg-muted">
        {isRegenerate && <p>{S.readingGuide.regenerateNotice}</p>}
        <p>{S.readingGuide.costNotice}</p>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => {
            setConfirmOpen(false);
            void generate();
          }}
          className="btn-primary flex-1 py-2 text-sm"
        >
          {S.readingGuide.confirmCta}
        </button>
        <button
          type="button"
          onClick={() => setConfirmOpen(false)}
          className="btn-ghost flex-1 py-2 text-sm"
        >
          {S.readingGuide.close}
        </button>
      </div>
    </Modal>
  );

  if (status === 'loading') {
    return (
      <ContentState
        icon={(props) => <AppIcon name="library" {...props} />}
        title={S.readingGuide.loading}
        loading
        tone="muted"
      />
    );
  }

  if (status === 'generating') {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <span className="shimmer-label text-xs font-medium">{S.readingGuide.generating}</span>
          <button type="button" onClick={cancel} className="btn-ghost px-2.5 py-1 text-2xs">
            {S.readingGuide.cancel}
          </button>
        </div>
        {streamText && (
          <div className="analysis-content">
            <Markdown>{streamText}</Markdown>
          </div>
        )}
      </div>
    );
  }

  if (status === 'error') {
    return (
      <>
        {confirmModal}
        <ContentState
          icon={(props) => <AppIcon name="error" {...props} />}
          title={S.readingGuide.errorTitle}
          description={error ?? undefined}
          actionLabel={S.readingGuide.retry}
          onAction={() => void generate()}
          tone="error"
        />
      </>
    );
  }

  if (status === 'empty' || !guide) {
    return (
      <>
        {confirmModal}
        <div
          className="border border-border/45 bg-surface/40 px-4 py-4"
          style={{ borderRadius: 'var(--radius-surface)' }}
        >
          <div className="flex items-center gap-2">
            <AppIcon name="library" className="h-4 w-4 text-accent" />
            <h3 className="text-sm font-[650] text-fg">{S.readingGuide.title}</h3>
          </div>
          <p className="mt-2 text-xs font-normal leading-relaxed text-fg-muted">
            {S.readingGuide.intro}
          </p>
          <p className="mt-1 text-2xs leading-relaxed text-fg-muted">{S.readingGuide.costNotice}</p>
          <button
            type="button"
            onClick={() => setConfirmOpen(true)}
            disabled={!paperId}
            className="btn-primary mt-4 px-3 py-1.5 text-xs"
          >
            {S.readingGuide.generate}
          </button>
        </div>
      </>
    );
  }

  const metaLine = meta
    ? S.readingGuide.metaLine(
        formatCreatedAt(meta.createdAt),
        levelLabelOf(meta.level),
        meta.costUsd !== null ? `$${meta.costUsd.toFixed(3)}` : null,
      )
    : null;

  return (
    <div className="space-y-5">
      {confirmModal}

      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="min-w-0 space-y-0.5">
          {metaLine && (
            <p className="text-xs text-fg-muted">
              {metaLine}
              {levelMismatch && (
                <span className="ml-2 text-fg-secondary">{S.readingGuide.levelMismatch}</span>
              )}
            </p>
          )}
          {!guide.parsed && (
            <p className="text-2xs text-fg-muted">{S.readingGuide.rawFallback}</p>
          )}
        </div>
        <button
          type="button"
          onClick={() => setConfirmOpen(true)}
          className="btn-ghost shrink-0 px-2.5 py-1 text-2xs"
        >
          {S.readingGuide.regenerate}
        </button>
      </div>

      {!guide.parsed ? (
        <div className="analysis-content">
          <Markdown>{guide.raw}</Markdown>
        </div>
      ) : (
        <>
          {guide.glossary.length > 0 && (
            <GlossaryList
              entries={guide.glossary}
              onJumpToPage={onJumpToPage}
              onSearchInPdf={onSearchInPdf}
            />
          )}
          {guide.prerequisites.length > 0 && (
            <PrerequisiteCards entries={guide.prerequisites} />
          )}
          {guide.sections.length > 0 && (
            <SectionAccordion sections={guide.sections} onJumpToPage={onJumpToPage} />
          )}
        </>
      )}
    </div>
  );
}
