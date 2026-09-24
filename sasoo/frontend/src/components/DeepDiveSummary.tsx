import { Fragment, useEffect, useId, useMemo, useRef, useState } from 'react';
import { Markdown, type MarkdownCitationOptions } from './Markdown';
import { buildDeepDiveNarrative, readInputCoverage, readSummaryExtensions } from '@/lib/summaryContent';
import { S } from '@/lib/strings';
import { focusReadingTarget } from '@/lib/readingNavigation';
import { detectCitations } from '@/lib/citations';
import { withRoJosa } from '@/lib/josa';

interface DeepDiveSummaryProps {
  readonly data: Record<string, unknown>;
  readonly citations?: MarkdownCitationOptions;
}

function SourceReferences({ refs, citations }: {
  readonly refs: readonly string[];
  readonly citations?: MarkdownCitationOptions;
}) {
  return (
    <div data-summary-sources className="text-sm text-fg-secondary">
      <span>{S.deepDive.sourceRefs}</span>
      <p>{refs.map((ref, index) => {
        const match = detectCitations(ref).find((candidate) =>
          candidate.start === 0 && candidate.end === ref.length && candidate.type !== 'page',
        );
        return (
          <Fragment key={index}>
            {index > 0 && ', '}
            {match && citations && citations.isAllowed?.(match) ? (
              <button
                type="button"
                className="citation-chip"
                title={`${withRoJosa(ref)} 이동`}
                onClick={() => citations.onClick({ type: match.type, n: match.n })}
              >{ref}</button>
            ) : ref}
          </Fragment>
        );
      })}</p>
    </div>
  );
}

export function DeepDiveSummary({ data, citations }: DeepDiveSummaryProps) {
  const extensions = readSummaryExtensions(data);
  const narrative = buildDeepDiveNarrative(data);
  const coverage = readInputCoverage(data);
  const coverageCopy = S.deepDive.coverage[coverage.kind];
  const articleRef = useRef<HTMLElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const [currentSection, setCurrentSection] = useState('main');
  const id = useId();
  const sourceCitations = useMemo<MarkdownCitationOptions | undefined>(() => citations && ({
    onClick: citations.onClick,
    isAllowed: (target) => target.type !== 'page' && (citations.isAllowed?.(target) ?? false),
  }), [citations]);
  const links = [
    ['main', S.deepDive.main], ['answers', S.deepDive.answersLink], ['transfer', S.deepDive.transferLink],
  ] as const;

  useEffect(() => {
    const panel = articleRef.current?.closest<HTMLElement>('[data-analysis-scroll]');
    if (!panel) return;
    const updateCurrentSection = () => {
      const threshold = panel.getBoundingClientRect().top + (navRef.current?.getBoundingClientRect().height ?? 0) + 12;
      let current = 'main';
      for (const [target] of links) {
        const element = articleRef.current?.querySelector<HTMLElement>(`[data-summary-anchor="${target}"]`);
        if (element && element.getBoundingClientRect().top <= threshold) current = target;
      }
      setCurrentSection(current);
    };
    panel.addEventListener('scroll', updateCurrentSection, { passive: true });
    window.addEventListener('resize', updateCurrentSection);
    updateCurrentSection();
    return () => {
      panel.removeEventListener('scroll', updateCurrentSection);
      window.removeEventListener('resize', updateCurrentSection);
    };
  }, [extensions.kind]);

  return (
    <article className="reading-prose" ref={articleRef} data-deep-dive-summary>
      <nav ref={navRef} aria-label={S.deepDive.navigation} className="sticky top-0 z-10 mb-4 flex flex-wrap gap-x-4 gap-y-1 border-b border-border/45 bg-surface/95 py-1 text-sm backdrop-blur-sm">
        {links.filter(([target]) => target === 'main' || extensions.kind === 'current').map(([target, label]) => (
          <button
            key={target}
            type="button"
            data-summary-link={target}
            aria-current={currentSection === target ? 'location' : undefined}
            className="inline-flex min-h-8 items-center border-b-2 border-transparent text-fg-secondary hover:text-accent focus-visible:outline-2 focus-visible:outline-accent aria-current:border-accent aria-current:text-accent"
            onClick={() => {
              const element = articleRef.current?.querySelector<HTMLElement>(`[data-summary-anchor="${target}"]`);
              if (element) {
                focusReadingTarget(element);
                setCurrentSection(target);
              }
            }}
          >
            {label}
          </button>
        ))}
      </nav>
      {data.skipped !== true && (
        <aside
          data-summary-coverage={coverage.kind}
          role={coverage.kind === 'partial' ? 'alert' : 'status'}
          aria-label={coverageCopy.title}
          className={coverage.kind === 'partial'
            ? 'mb-4 rounded-control border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-fg'
            : 'mb-4 text-sm text-fg-secondary'}
        >
          <p className="font-semibold">{coverageCopy.title}</p>
          <p>{coverageCopy.description}</p>
          {'missing' in coverage && coverage.missing.length > 0 && (
            <ul>{coverage.missing.map((missing, index) => <li key={index}>{missing}</li>)}</ul>
          )}
          {coverage.kind === 'partial' && coverage.missing.length === 0 && <p>{S.deepDive.unknownMissing}</p>}
        </aside>
      )}
      <section id={`${id}-main`} data-summary-anchor="main" tabIndex={-1} aria-label={S.deepDive.main}>
        <Markdown headingAnchors codeTools citations={citations}>{narrative.main}</Markdown>
      </section>

      {extensions.kind === 'legacy' && data.skipped !== true && <p className="text-sm text-fg-secondary">{S.deepDive.legacy}</p>}
      {extensions.kind === 'invalid' && <p role="alert" className="text-danger">{extensions.message}</p>}
      {extensions.kind === 'current' && (
        <>
          <section aria-labelledby={`${id}-answers`}>
            <h3 id={`${id}-answers`} data-summary-anchor="answers" tabIndex={-1}>{S.deepDive.answers}</h3>
            {extensions.sectionAnswers.length === 0 && <p data-summary-empty>{S.deepDive.empty}</p>}
            {extensions.sectionAnswers.map((answer, index) => (
              <article key={index} data-summary-answer={index} className="my-5">
                <h4 tabIndex={-1}>{answer.section_title}</h4>
                <div className="font-[650]"><Markdown codeTools citations={sourceCitations}>{answer.question}</Markdown></div>
                <Markdown codeTools citations={sourceCitations}>{answer.answer}</Markdown>
                <details>
                  <summary className="min-h-8 cursor-pointer py-1 text-sm text-fg-secondary focus-visible:outline-2 focus-visible:outline-accent">
                    {S.deepDive.explanation}
                  </summary>
                  {answer.explanation && <Markdown codeTools citations={sourceCitations}>{answer.explanation}</Markdown>}
                  <SourceReferences refs={answer.source_refs} citations={sourceCitations} />
                </details>
              </article>
            ))}
          </section>
          <section aria-labelledby={`${id}-transfer`}>
            <h3 id={`${id}-transfer`} data-summary-anchor="transfer" tabIndex={-1}>{S.deepDive.transfer}</h3>
            {extensions.transferChecks.length === 0 && <p data-summary-empty>{S.deepDive.empty}</p>}
            {extensions.transferChecks.map((check, index) => (
              <article key={index} className="my-5">
                <h4>{check.item}</h4>
                <p className="text-sm text-fg-secondary">{S.deepDive.basis[check.condition_basis]}</p>
                <Markdown codeTools citations={sourceCitations}>{check.paper_condition}</Markdown>
                <p className="font-[650]">{S.deepDive.transferSuggestion}</p>
                <Markdown codeTools>{check.check_before_transfer}</Markdown>
                {check.source_refs.length > 0 && (
                  <SourceReferences refs={check.source_refs} citations={sourceCitations} />
                )}
              </article>
            ))}
          </section>
        </>
      )}
      {narrative.additional && (
        <details data-summary-additional className="mt-6">
          <summary className="min-h-8 cursor-pointer py-1 font-[650] focus-visible:outline-2 focus-visible:outline-accent">
            {S.deepDive.additional}
          </summary>
          <Markdown headingAnchors codeTools citations={citations}>{narrative.additional}</Markdown>
        </details>
      )}
    </article>
  );
}
