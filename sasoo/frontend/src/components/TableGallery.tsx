import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Loader2 } from 'lucide-react';
import { getLibraryAssetUrl, type Table, type VisualState } from '@/lib/api';
import { S } from '@/lib/strings';
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

function buildStatusBadge(table: Table): { label: string; classes: string } {
  if (table.review_required || table.extraction_status === 'uncertain') {
    return {
      label: S.tables.reviewRequired,
      classes: 'bg-amber-500/10 text-amber-300 border border-amber-500/20',
    };
  }

  return {
    label: S.tables.statusReady,
    classes: 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20',
  };
}

function TableSkeleton() {
  return (
    <div className="card animate-pulse space-y-4">
      <div className="h-4 w-32 rounded bg-surface-700" />
      <div className="flex gap-2">
        <div className="h-5 w-20 rounded-full bg-surface-700" />
        <div className="h-5 w-16 rounded-full bg-surface-700" />
      </div>
      <div className="space-y-2">
        <div className="h-3 w-full rounded bg-surface-700" />
        <div className="h-3 w-5/6 rounded bg-surface-700" />
        <div className="h-3 w-2/3 rounded bg-surface-700" />
      </div>
    </div>
  );
}

export default function TableGallery({
  tables,
  loading = false,
  visualState = 'ready',
  visualError = null,
  artifactsError = null,
  onJumpToTablePage,
}: TableGalleryProps) {
  const effectiveError = visualError ?? artifactsError;
  const hasArtifactError = visualState === 'error' && Boolean(effectiveError);
  const isPreparingArtifacts = visualState === 'running';
  const isPartialArtifacts = visualState === 'partial';

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
            <Loader2 className="mb-2 h-8 w-8 animate-spin text-primary-400" />
          ) : hasArtifactError ? (
            <AppIcon name="error" className="mb-2 h-8 w-8 text-red-400" />
          ) : isPartialArtifacts ? (
            <AppIcon name="warning" className="mb-2 h-8 w-8 text-amber-400" />
          ) : (
            <AppIcon name="tables" className="mb-2 h-8 w-8 text-surface-600" />
          )}
          <p className="text-sm text-surface-400">
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
        <div className="flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-200">
          <AppIcon name="error" className="h-3.5 w-3.5 text-red-300" />
          <span>{effectiveError}</span>
        </div>
      ) : isPreparingArtifacts && (
        <div className="flex items-center gap-2 rounded-lg border border-primary-500/20 bg-primary-500/10 px-3 py-2 text-xs text-primary-200">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-primary-400" />
          <span>{S.tables.syncing}</span>
        </div>
      )}

      {!hasArtifactError && !isPreparingArtifacts && isPartialArtifacts && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          <AppIcon name="warning" className="h-3.5 w-3.5 text-amber-300" />
          <span>{S.tables.partialWarning}</span>
        </div>
      )}

      <div className="grid gap-3">
        {tables.map((table, index) => {
          const statusBadge = buildStatusBadge(table);
          const confidenceLabel = formatPercent(table.confidence);
          const csvUrl = getLibraryAssetUrl(table.csv_path);
          const htmlUrl = getLibraryAssetUrl(table.html_path);

          return (
            <div
              key={table.id ?? `${table.table_num ?? 'table'}-${index}`}
              className="card space-y-4 border border-surface-700/40 bg-surface-900/30 [.light_&]:bg-white"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-[15px] font-semibold text-surface-100">
                      {table.table_num || `Table ${index + 1}`}
                    </h3>
                    {typeof table.page_number === 'number' && (
                      <span className="status-pill border-surface-700/50 bg-surface-800/80 text-surface-300">
                        {S.tables.pageLabel(table.page_number)}
                      </span>
                    )}
                    <span className={`status-pill ${statusBadge.classes}`}>
                      {statusBadge.label}
                    </span>
                  </div>
                  {table.caption && (
                    <p className="mt-2 text-[14px] leading-6 text-surface-300">
                      {table.caption}
                    </p>
                  )}
                </div>

                <div className="flex flex-wrap items-center justify-end gap-2">
                  {confidenceLabel && (
                    <span className="status-pill border-primary-500/20 bg-primary-500/10 text-primary-300">
                      {S.tables.confidence(confidenceLabel)}
                    </span>
                  )}
                  {table.parse_method && (
                    <span className="status-pill border-surface-700/50 bg-surface-800/80 text-surface-300">
                      {S.tables.parseMethod(table.parse_method)}
                    </span>
                  )}
                  {table.resolver_version && (
                    <span className="status-pill border-surface-700/50 bg-surface-800/80 text-surface-400">
                      {S.tables.resolverLabel(table.resolver_version)}
                    </span>
                  )}
                  {table.classifier_model && (
                    <span className="status-pill border-surface-700/50 bg-surface-800/80 text-surface-400">
                      {S.tables.modelLabel(table.classifier_model)}
                    </span>
                  )}
                </div>
              </div>

              {(table.review_required || table.repair_attempted) && (
                <div className="rounded-xl bg-surface-950/40 px-4 py-3 [.light_&]:bg-surface-50">
                  <div className="flex flex-wrap items-center gap-2 text-[11px] text-surface-500 [.light_&]:text-surface-600">
                    {table.review_required && (
                      <span className="status-pill border-amber-500/20 bg-amber-500/10 text-amber-300">
                        {S.tables.reviewRequired}
                      </span>
                    )}
                    {table.repair_attempted && (
                      <span className="status-pill border-primary-500/20 bg-primary-500/10 text-primary-300">
                        {S.tables.repairAttempted}
                      </span>
                    )}
                    {table.repair_confidence != null && (
                      <span className="status-pill border-surface-700/50 bg-surface-900/60 text-surface-300">
                        {S.tables.repairConfidence(formatPercent(table.repair_confidence) || '0%')}
                      </span>
                    )}
                  </div>
                  {formatRepairReason(table.repair_reason) && (
                    <p className="mt-2 text-[13px] leading-5 text-surface-400 [.light_&]:text-surface-600">
                      {formatRepairReason(table.repair_reason)}
                    </p>
                  )}
                </div>
              )}

              {table.markdown_text && (
                <div className="rounded-xl border border-surface-700/30 bg-surface-950/50 px-4 py-3 [.light_&]:bg-surface-50">
                  <div className="mb-2 flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.14em] text-surface-500 [.light_&]:text-surface-600">
                    <AppIcon name="tables" className="h-3.5 w-3.5 text-primary-400" />
                    {S.tables.markdownPreview}
                  </div>
                  <div className="analysis-content line-clamp-6 text-[13px] leading-6 text-surface-300">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {table.markdown_text}
                    </ReactMarkdown>
                  </div>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-2">
                {typeof table.page_number === 'number' && onJumpToTablePage && (
                  <button
                    type="button"
                    onClick={() => onJumpToTablePage(table)}
                    className="btn-secondary text-xs"
                  >
                    <AppIcon name="arrow-right" className="h-3.5 w-3.5" />
                    {S.tables.jumpToPage}
                  </button>
                )}
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
