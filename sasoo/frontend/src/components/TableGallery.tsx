import { Markdown } from '@/components/Markdown';
import { Loader2 } from 'lucide-react';
import { getLibraryAssetUrl, type Table, type VisualState } from '@/lib/api';
import { S } from '@/lib/strings';
import { resolveArtifactPlaceholder } from '@/lib/artifactState';
import { CONFIDENCE_REVIEW_THRESHOLD } from '@/lib/confidence';
import { AppIcon } from '@/components/icons';

interface TableGalleryProps {
  tables: Table[];
  loading?: boolean;
  visualState?: VisualState;
  visualError?: string | null;
  artifactsReady?: boolean;
  artifactsError?: string | null;
  onJumpToTablePage?: (table: Table) => void;
}

function formatPercent(confidence: number | null | undefined): string | null {
  if (typeof confidence !== 'number' || Number.isNaN(confidence)) return null;
  return `${Math.round(confidence * 100)}%`;
}

const REPAIR_REASON_LABELS: Record<string, string> = {
  irregular_row_widths: '열 폭 불균형',
  multiline_header: '멀티라인 헤더',
  sparse_header: '빈 헤더 셀',
  caption_linked_but_grid_weak: '캡션 근처 약한 그리드',
  page_audit_suspect: '감사 대상 페이지',
  ruled_bbox_without_grid: '선형 표 후보 재검토',
};

function formatRepairReason(reason: string | null | undefined): string | null {
  if (!reason) return null;
  const parts = reason
    .split('|')
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => REPAIR_REASON_LABELS[part] || part.replace(/_/g, ' '));

  return parts.length > 0 ? parts.join(' · ') : null;
}

// FigureGallery의 색점 문법과 동일: pill 대신 7px 색점 1개 + title 툴팁.
// I6: 상태 점과 신뢰도 점을 하나로 합친다 — review_required거나 신뢰도가
// 검토 임계값 미만이면 warning, 아니면 success. 문구만 원인별로 분기한다.
function buildStatusDot(table: Table): { isWarning: boolean; label: string } {
  const hasConfidence = typeof table.confidence === 'number' && !Number.isNaN(table.confidence);
  const confidenceIsLow = hasConfidence && table.confidence! < CONFIDENCE_REVIEW_THRESHOLD;
  const needsReview = table.review_required || table.extraction_status === 'uncertain' || confidenceIsLow;

  if (!needsReview) {
    return {
      isWarning: false,
      label: hasConfidence ? `신뢰도 ${Math.round(table.confidence! * 100)}%` : S.tables.statusReady,
    };
  }

  if (hasConfidence) {
    return {
      isWarning: true,
      label: `신뢰도 ${Math.round(table.confidence! * 100)}%, 검토를 권해요`,
    };
  }

  return { isWarning: true, label: S.tables.reviewRequired };
}

function TableSkeleton() {
  return (
    <div className="card animate-pulse space-y-4">
      <div className="h-4 w-32 rounded-sm bg-border" />
      <div className="flex gap-2">
        <div className="h-5 w-20 rounded-full bg-border" />
        <div className="h-5 w-16 rounded-full bg-border" />
      </div>
      <div className="space-y-2">
        <div className="h-3 w-full rounded-sm bg-border" />
        <div className="h-3 w-5/6 rounded-sm bg-border" />
        <div className="h-3 w-2/3 rounded-sm bg-border" />
      </div>
    </div>
  );
}

export default function TableGallery({
  tables,
  loading = false,
  // FigureGallery와 동일한 이유로 'ready'가 아니라 'running'이 기본값이다.
  // 응답 전/실패로 undefined면 "표가 없다"가 아니라 "준비 중"으로 보여야 한다.
  visualState = 'running',
  visualError = null,
  artifactsError = null,
  onJumpToTablePage,
}: TableGalleryProps) {
  const effectiveError = visualError ?? artifactsError;
  const placeholder = resolveArtifactPlaceholder(visualState, Boolean(effectiveError));
  const hasArtifactError = placeholder === 'error';
  const isPreparingArtifacts = placeholder === 'preparing';
  const isPartialArtifacts = placeholder === 'partial';

  if (loading && tables.length === 0) {
    return (
      <div className="grid gap-3">
        <TableSkeleton />
        <TableSkeleton />
      </div>
    );
  }

  if (tables.length === 0) {
    return (
        <div className="card flex flex-col items-center justify-center py-8 text-center">
          {isPreparingArtifacts ? (
            <Loader2 className="mb-2 h-8 w-8 animate-spin text-accent" />
          ) : hasArtifactError ? (
            <AppIcon name="error" className="mb-2 h-8 w-8 text-danger" />
          ) : isPartialArtifacts ? (
            <AppIcon name="warning" className="mb-2 h-8 w-8 text-warning" />
          ) : (
            <AppIcon name="tables" className="mb-2 h-8 w-8 text-fg-muted" />
          )}
          <p className="text-sm text-fg-muted">
            {isPreparingArtifacts
              ? S.tables.preparing
              : hasArtifactError
                ? effectiveError
                : isPartialArtifacts
                  ? S.tables.partialWarning
                : S.tables.noTables}
          </p>
        </div>
      );
  }

  return (
    <div className="space-y-4">
      {hasArtifactError ? (
        <div className="flex items-center gap-2 rounded-lg border border-danger/20 bg-danger/10 px-3 py-2 text-xs text-danger">
          <AppIcon name="error" className="h-3.5 w-3.5 text-danger" />
          <span>{effectiveError}</span>
        </div>
      ) : isPreparingArtifacts && (
        <div className="flex items-center gap-2 rounded-lg border border-accent/20 bg-accent/10 px-3 py-2 text-xs text-accent">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" />
          <span>{S.tables.syncing}</span>
        </div>
      )}

      {!hasArtifactError && !isPreparingArtifacts && isPartialArtifacts && (
        <div className="flex items-center gap-2 rounded-lg border border-warning/20 bg-warning/10 px-3 py-2 text-xs text-warning">
          <AppIcon name="warning" className="h-3.5 w-3.5 text-warning" />
          <span>{S.tables.partialWarning}</span>
        </div>
      )}

      <div className="grid gap-3">
        {tables.map((table, index) => {
          const statusDot = buildStatusDot(table);
          const metaLine = [
            typeof table.page_number === 'number' ? S.tables.pageLabel(table.page_number) : null,
            // C2: parse_method는 내부 파이프라인 용어라 개발자 모드에서만 노출한다.
            import.meta.env.DEV && table.parse_method ? S.tables.parseMethod(table.parse_method) : null,
          ]
            .filter(Boolean)
            .join(' · ');
          const csvUrl = getLibraryAssetUrl(table.csv_path);
          const htmlUrl = getLibraryAssetUrl(table.html_path);

          return (
            <div
              key={table.id ?? `${table.table_num ?? 'table'}-${index}`}
              data-citation-anchor={
                table.table_num?.match(/\d+/)?.[0]
                  ? `table-${table.table_num.match(/\d+/)![0]}`
                  : undefined
              }
              className="space-y-4 overflow-hidden rounded-[12px] bg-surface p-4 shadow-[0_1px_2px_rgba(0,0,0,.04),0_2px_8px_rgba(0,0,0,.04)] dark:shadow-none"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="min-w-0 truncate text-base font-[650] text-fg">
                      {table.table_num || `Table ${index + 1}`}
                    </h3>
                    <span
                      role="img"
                      className={`h-[7px] w-[7px] flex-shrink-0 rounded-full ${statusDot.isWarning ? 'bg-warning' : 'bg-success'}`}
                      title={statusDot.label}
                      aria-label={statusDot.label}
                    />
                  </div>
                  {table.caption && (
                    <p className="mt-2 text-sm leading-6 text-fg-secondary">
                      {table.caption}
                    </p>
                  )}
                  {(metaLine || (typeof table.page_number === 'number' && onJumpToTablePage)) && (
                    <div className="mt-2 flex items-center justify-between gap-2 text-2xs text-fg-muted">
                      <span>{metaLine}</span>
                      {typeof table.page_number === 'number' && onJumpToTablePage && (
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            onJumpToTablePage(table);
                          }}
                          className="-mr-1.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg"
                          aria-label={S.tables.jumpToPage}
                          title="PDF에서 보기"
                        >
                          <AppIcon name="document" className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  )}
                </div>

                {import.meta.env.DEV && (table.resolver_version || table.classifier_model) && (
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    {table.resolver_version && (
                      <span className="status-pill border-border/50 bg-surface/80 text-fg-muted">
                        {S.tables.resolverLabel(table.resolver_version)}
                      </span>
                    )}
                    {table.classifier_model && (
                      <span className="status-pill border-border/50 bg-surface/80 text-fg-muted">
                        {S.tables.modelLabel(table.classifier_model)}
                      </span>
                    )}
                  </div>
                )}
              </div>

              {(table.review_required || table.repair_attempted) && (
                <div className="rounded-xl bg-bg/40 px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2 text-2xs text-fg-muted">
                    {table.review_required && (
                      <span className="status-pill border-warning/20 bg-warning/10 text-warning">
                        {S.tables.reviewRequired}
                      </span>
                    )}
                    {table.repair_attempted && (
                      <span className="status-pill border-accent/20 bg-accent/10 text-accent">
                        {S.tables.repairAttempted}
                      </span>
                    )}
                    {table.repair_confidence != null && (
                      <span className="status-pill border-border/50 bg-surface/60 text-fg-secondary">
                        {S.tables.repairConfidence(formatPercent(table.repair_confidence) || '0%')}
                      </span>
                    )}
                  </div>
                  {formatRepairReason(table.repair_reason) && (
                    <p className="mt-2 text-sm leading-5 text-fg-muted">
                      {formatRepairReason(table.repair_reason)}
                    </p>
                  )}
                </div>
              )}

              {table.markdown_text && (
                <div className="rounded-xl border border-border/30 bg-bg/50 px-4 py-3">
                  <div className="mb-2 flex items-center gap-2 text-2xs font-medium uppercase tracking-[0.14em] text-fg-muted">
                    <AppIcon name="tables" className="h-3.5 w-3.5 text-accent" />
                    {S.tables.markdownPreview}
                  </div>
                  <div className="analysis-content line-clamp-6 text-sm leading-6 text-fg-secondary">
                    <Markdown>{table.markdown_text}</Markdown>
                  </div>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-2">
                {csvUrl && (
                  <a
                    href={csvUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="btn-ghost text-xs"
                  >
                    <AppIcon name="download" className="h-3.5 w-3.5" />
                    {S.tables.csvAsset}
                  </a>
                )}
                {htmlUrl && (
                  <a
                    href={htmlUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="btn-ghost text-xs"
                  >
                    <AppIcon name="document" className="h-3.5 w-3.5" />
                    {S.tables.htmlAsset}
                  </a>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
