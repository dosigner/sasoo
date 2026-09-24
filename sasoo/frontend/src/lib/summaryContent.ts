import { S } from './strings';
import type { AnalysisStatus } from './api';

export interface SectionAnswer {
  readonly section_title: string;
  readonly question: string;
  readonly answer: string;
  readonly explanation: string;
  readonly source_refs: readonly string[];
}

export interface TransferCheck {
  readonly item: string;
  readonly paper_condition: string;
  readonly condition_basis: 'reported' | 'inferred' | 'not_reported';
  readonly check_before_transfer: string;
  readonly source_refs: readonly string[];
}

export type SummaryExtensions =
  | { readonly kind: 'legacy' }
  | { readonly kind: 'invalid'; readonly message: string }
  | { readonly kind: 'current'; readonly sectionAnswers: readonly SectionAnswer[]; readonly transferChecks: readonly TransferCheck[] };

export type InputCoverage =
  | { readonly kind: 'legacy' | 'unknown' }
  | { readonly kind: 'partial' | 'provided_pdf'; readonly missing: readonly string[] };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isText(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

export function readInputCoverage(data: Record<string, unknown>): InputCoverage {
  if (!Object.hasOwn(data, '_input_coverage')) return { kind: 'legacy' };
  const coverage = data._input_coverage;
  if (!isRecord(coverage) || !Array.isArray(coverage.missing) || !coverage.missing.every(isText)) {
    return { kind: 'unknown' };
  }
  const textInput = coverage.mode === 'text' && coverage.pdf_sha256 === null;
  const pdfInput = coverage.mode === 'pdf' && typeof coverage.pdf_sha256 === 'string'
    && /^[a-f0-9]{64}$/iu.test(coverage.pdf_sha256);
  switch (coverage.status) {
    case 'partial':
      return textInput || pdfInput ? { kind: 'partial', missing: coverage.missing } : { kind: 'unknown' };
    case 'provided_pdf':
      return pdfInput ? { kind: 'provided_pdf', missing: coverage.missing } : { kind: 'unknown' };
    default:
      return { kind: 'unknown' };
  }
}

function isSourceRefs(value: unknown): value is readonly string[] {
  return Array.isArray(value) && value.length <= 4 && value.every(isText);
}

function isSectionAnswer(value: unknown): value is SectionAnswer {
  return isRecord(value)
    && isText(value.section_title) && isText(value.question) && isText(value.answer)
    && typeof value.explanation === 'string'
    && isSourceRefs(value.source_refs) && value.source_refs.length > 0;
}

function isTransferCheck(value: unknown): value is TransferCheck {
  if (!isRecord(value) || !isText(value.item) || !isText(value.paper_condition)
    || !isText(value.check_before_transfer) || !isSourceRefs(value.source_refs)) return false;
  return value.condition_basis === 'not_reported'
    || ((value.condition_basis === 'reported' || value.condition_basis === 'inferred')
      && value.source_refs.length > 0);
}

export function readSummaryExtensions(data: Record<string, unknown>): SummaryExtensions {
  if (Object.hasOwn(data, '_parse_error') || Object.hasOwn(data, 'error')) {
    return { kind: 'invalid', message: S.deepDive.invalid };
  }
  const hasAnswers = Object.hasOwn(data, 'section_answers');
  const hasChecks = Object.hasOwn(data, 'transfer_checks');
  if (!hasAnswers && !hasChecks) return { kind: 'legacy' };
  const answers: unknown = data.section_answers;
  const checks: unknown = data.transfer_checks;
  if (!hasAnswers || !hasChecks
    || !Array.isArray(answers) || answers.length > 12 || !answers.every(isSectionAnswer)
    || !Array.isArray(checks) || checks.length > 8 || !checks.every(isTransferCheck)) {
    return { kind: 'invalid', message: S.deepDive.invalid };
  }
  return { kind: 'current', sectionAnswers: answers, transferChecks: checks };
}

export function getSummaryDisplayStatus(
  status: AnalysisStatus | null, data: Record<string, unknown> | null,
): AnalysisStatus | null {
  if (!status || !data) return status;
  const extensions = readSummaryExtensions(data);
  if (extensions.kind !== 'invalid') {
    if (data.skipped !== true) return status;
    return {
      ...status,
      phases: status.phases.map((phase) => phase.phase === 'deep_dive' && phase.status === 'completed'
        ? { ...phase, status: 'skipped' } : phase),
    };
  }
  return {
    ...status,
    overall_status: status.overall_status === 'completed' ? 'error' : status.overall_status,
    phases: status.phases.map((phase) => phase.phase === 'deep_dive' && phase.status !== 'running'
      ? { ...phase, status: 'error', error_message: extensions.message }
      : phase),
  };
}

const normalizeSectionTitle = (title: string): string =>
  title.normalize('NFC').replace(/\s+/gu, ' ').trim().toLowerCase();

export function findSectionAnswerIndex(title: string, answers: readonly SectionAnswer[]): number | null {
  const normalized = normalizeSectionTitle(title);
  const matches = answers.flatMap((answer, index) =>
    normalizeSectionTitle(answer.section_title) === normalized ? [index] : []);
  return matches.length === 1 ? matches[0] : null;
}

export function buildDeepDiveNarrative(data: Record<string, unknown>): { main: string; additional: string } {
  if (data.skipped === true && isText(data.message)) return { main: data.message, additional: '' };
  const main: string[] = [];
  const additional: string[] = [];
  const mainFields = ['problem_definition', 'as_is', 'to_be', 'solution', 'method_summary', 'key_results'] as const;
  for (const key of mainFields) {
    const value = data[key];
    if (isText(value)) main.push(`### ${S.deepDive.headings[key]}\n\n${value.trim()}`);
  }
  if (isText(data.detailed_analysis)) main.push(data.detailed_analysis.trim());
  if (Array.isArray(data.weaknesses) && data.weaknesses.length > 0) {
    main.push(`### ${S.deepDive.headings.weaknesses}\n\n${data.weaknesses.map((item) => `- ${item}`).join('\n')}`);
  }

  const md = S.analysis.md;
  const proseFields = [
    ['novelty_assessment', md.novelty], ['comparison_to_prior_work', md.comparisonToPrior],
  ] as const;
  for (const [key, label] of proseFields) {
    if (isText(data[key])) additional.push(`### ${label}\n\n${data[key]}`);
  }
  if (data.comparison_scope === 'in_paper_only') additional.push(md.comparisonScopeNote);
  const listFields = [
    ['strengths', md.strengths], ['suggested_improvements', md.suggestedImprovements],
    ['practical_applications', md.practicalApplications], ['follow_up_questions', md.followUpQuestions],
  ] as const;
  for (const [key, label] of listFields) {
    const items: unknown = data[key];
    if (Array.isArray(items) && items.length > 0) {
      additional.push(`### ${label}\n\n${items.map((item) => `- ${item}`).join('\n')}`);
    }
  }
  return { main: main.join('\n\n'), additional: additional.join('\n\n') };
}
