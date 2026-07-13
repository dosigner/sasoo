import { useMemo, useState, useCallback, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ChevronDown,
  Loader2,
  AlertCircle,
} from 'lucide-react';
import { usePapers } from '@/hooks/usePapers';
import { type Paper, type PaperStatus } from '@/lib/api';
import { getAllAgents } from '@/lib/agents';
import { LEVEL_LABELS, type LevelKey } from '@/components/LevelSlider';
import { S } from '@/lib/strings';
import { useToast } from '@/components/Toast';
import { Modal, Select } from '@/components/ui';
import { AppIcon } from '@/components/icons';

type ViewMode = 'grid' | 'list';

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

function statusLabel(status: PaperStatus): string {
  switch (status) {
    case 'completed':
      return S.status.analyzed;
    case 'analyzing':
      return S.status.analyzing;
    case 'pending':
      return S.status.pending;
    case 'error':
      return S.status.error;
    default:
      return status;
  }
}

function statusTone(status: PaperStatus): {
  line: string;
  panel: string;
  badge: string;
  dot: string;
} {
  switch (status) {
    case 'completed':
      return {
        line: 'bg-success',
        panel: 'bg-success/[0.05]',
        badge: 'border-success/20 bg-success/10 text-success',
        dot: 'bg-success',
      };
    case 'analyzing':
      return {
        line: 'bg-accent',
        panel: 'bg-accent/[0.05]',
        badge: 'border-accent/20 bg-accent/10 text-accent',
        dot: 'bg-accent',
      };
    case 'error':
      return {
        line: 'bg-danger',
        panel: 'bg-danger/[0.05]',
        badge: 'border-danger/20 bg-danger/10 text-danger',
        dot: 'bg-danger',
      };
    case 'pending':
    default:
      return {
        line: 'bg-warning',
        panel: 'bg-warning/[0.05]',
        badge: 'border-warning/20 bg-warning/10 text-warning',
        dot: 'bg-warning',
      };
  }
}

function handleInteractiveKeyDown(
  event: KeyboardEvent<HTMLElement>,
  onActivate: () => void,
): void {
  if (event.target !== event.currentTarget) return;
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    onActivate();
  }
}

function activityLabel(paper: Paper): string {
  const date = paper.analyzed_at || paper.created_at;
  return date ? formatDate(date) : '-';
}

function statusMetaCount(papers: Paper[], status: PaperStatus): number {
  return papers.filter((paper) => paper.status === status).length;
}

// 분석 시 실제 적용된 설명 수준 라벨. 값이 없으면(구 데이터·미분석) '미지정'.
function explanationLevelLabel(paper: Paper): string {
  const key = paper.explanation_level as LevelKey | null | undefined;
  return key && key in LEVEL_LABELS ? LEVEL_LABELS[key] : '미지정';
}

type TableSortKey = 'title' | 'year' | 'analyzed_at';

interface SortableThProps {
  label: string;
  colKey: TableSortKey;
  activeKey?: string;
  order?: 'asc' | 'desc';
  onSort: (key: TableSortKey) => void;
}

function SortableTh({ label, colKey, activeKey, order, onSort }: SortableThProps) {
  const active = activeKey === colKey;
  return (
    <th
      scope="col"
      aria-sort={active ? (order === 'asc' ? 'ascending' : 'descending') : 'none'}
      className="library-th-sortable"
    >
      <button
        type="button"
        onClick={() => onSort(colKey)}
        className="inline-flex items-center gap-1 uppercase tracking-[inherit]"
      >
        {label}
        {active &&
          (order === 'asc' ? (
            <ChevronUp className="h-3 w-3" />
          ) : (
            <ChevronDown className="h-3 w-3" />
          ))}
      </button>
    </th>
  );
}

interface PaperTableRowProps {
  paper: Paper;
  onOpen: (id: string) => void;
  onDelete: (id: string, title: string) => void;
}

function PaperTableRow({ paper, onOpen, onDelete }: PaperTableRowProps) {
  const tone = statusTone(paper.status);

  return (
    <tr
      tabIndex={0}
      role="button"
      aria-label={`${paper.title} 워크벤치 열기`}
      onClick={() => onOpen(String(paper.id))}
      onKeyDown={(event) => handleInteractiveKeyDown(event, () => onOpen(String(paper.id)))}
    >
      <td>
        <div className="min-w-0 max-w-[38rem]">
          <div className="line-clamp-2 font-medium leading-snug text-fg" title={paper.title}>
            {paper.title}
          </div>
          {paper.authors && (
            <div className="mt-0.5 truncate text-2xs text-fg-muted" title={paper.authors}>
              {paper.authors}
            </div>
          )}
        </div>
      </td>
      <td>
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
          <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} />
          {statusLabel(paper.status)}
        </span>
      </td>
      <td className="whitespace-nowrap">{paper.domain || '—'}</td>
      <td className="whitespace-nowrap">{explanationLevelLabel(paper)}</td>
      <td className="library-cell-num">{paper.year || '—'}</td>
      <td className="library-cell-num">{activityLabel(paper)}</td>
      <td>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete(String(paper.id), paper.title);
          }}
          className="library-row-action ml-auto"
          title={S.library.delete}
          aria-label={`${paper.title} ${S.library.delete}`}
        >
          <AppIcon name="delete" className="h-4 w-4" />
        </button>
      </td>
    </tr>
  );
}

function PaperArchiveCard({ paper, onOpen, onDelete }: PaperTableRowProps) {
  const tone = statusTone(paper.status);

  return (
    <article
      role="button"
      tabIndex={0}
      aria-label={`${paper.title} 워크벤치 열기`}
      className="library-soft-card group"
      onClick={() => onOpen(String(paper.id))}
      onKeyDown={(event) => handleInteractiveKeyDown(event, () => onOpen(String(paper.id)))}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="text-2xs text-fg-muted">
          {paper.year || '연도 미상'} · {paper.domain}
        </div>
        <span className="library-soft-pill">
          <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} />
          {statusLabel(paper.status)}
        </span>
      </div>

      <h3
        className="mt-3 line-clamp-2 text-[0.95rem] font-semibold leading-snug tracking-[-0.01em] text-fg"
        title={paper.title}
      >
        {paper.title}
      </h3>
      {paper.authors && (
        <div className="mt-1.5 line-clamp-1 text-xs text-fg-muted" title={paper.authors}>
          {paper.authors}
        </div>
      )}

      <div className="mt-auto flex items-center justify-between gap-2 pt-4">
        <div className="flex min-w-0 items-center gap-2 text-xs text-fg-muted">
          <span className="truncate text-fg-secondary">{explanationLevelLabel(paper)}</span>
          <span className="h-1 w-1 shrink-0 rounded-full bg-border" />
          <span className="library-cell-num truncate">{activityLabel(paper)}</span>
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete(String(paper.id), paper.title);
          }}
          className="library-row-action shrink-0 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
          title={S.library.delete}
          aria-label={`${paper.title} ${S.library.delete}`}
        >
          <AppIcon name="delete" className="h-4 w-4" />
        </button>
      </div>
    </article>
  );
}

export default function Library() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [showFilters, setShowFilters] = useState(false);
  const [searchValue, setSearchValue] = useState('');
  const [deleteModal, setDeleteModal] = useState<{
    show: boolean;
    paperId: string | null;
    paperTitle: string;
  }>({
    show: false,
    paperId: null,
    paperTitle: '',
  });
  const [deleting, setDeleting] = useState(false);

  const {
    papers,
    total,
    page,
    totalPages,
    loading,
    error,
    filters,
    setFilters,
    setSearch,
    goToPage,
    deletePaper,
    availableTags,
  } = usePapers();

  const activityCount = useMemo(
    () => papers.filter((paper) => Boolean(paper.analyzed_at || paper.created_at)).length,
    [papers]
  );

  const handleOpenPaper = useCallback(
    (id: string) => {
      navigate(`/workbench/${id}`);
    },
    [navigate]
  );

  const handleDeletePaper = useCallback(async (id: string, title: string) => {
    setDeleteModal({
      show: true,
      paperId: id,
      paperTitle: title,
    });
  }, []);

  const confirmDelete = useCallback(async () => {
    if (!deleteModal.paperId) return;

    setDeleting(true);
    try {
      await deletePaper(deleteModal.paperId);
      setDeleteModal({ show: false, paperId: null, paperTitle: '' });
      toast.success(S.toast.paperDeleted);
    } catch {
      toast.error(S.toast.deleteFailed);
    } finally {
      setDeleting(false);
    }
  }, [deleteModal.paperId, deletePaper, toast]);

  const cancelDelete = useCallback(() => {
    setDeleteModal({ show: false, paperId: null, paperTitle: '' });
  }, []);

  const clearFilters = useCallback(() => {
    setFilters({
      domain: undefined,
      year: undefined,
      status: undefined,
      tags: undefined,
      sort_by: 'created_at',
      sort_order: 'desc',
    });
    setSearch('');
    setSearchValue('');
  }, [setFilters, setSearch]);

  const hasActiveFilters =
    filters.domain || filters.year || filters.status || (filters.tags && filters.tags.length > 0);

  const from = (page - 1) * (filters.page_size || 20) + 1;
  const to = Math.min(page * (filters.page_size || 20), total);
  const handleGoUpload = useCallback(() => navigate('/'), [navigate]);

  // 테이블 헤더 클릭 정렬: 같은 컬럼이면 방향 토글, 다른 컬럼이면 그 컬럼의 기본 방향으로.
  const toggleSort = useCallback(
    (key: TableSortKey) => {
      if (filters.sort_by === key) {
        setFilters({ sort_order: filters.sort_order === 'asc' ? 'desc' : 'asc' });
      } else {
        setFilters({ sort_by: key, sort_order: key === 'title' ? 'asc' : 'desc' });
      }
    },
    [filters.sort_by, filters.sort_order, setFilters]
  );

  return (
    <div className="page-container-wide">
      <section className="library-archive-header archive-panel panel-compact mb-4">
        <div className="page-header-dense">
          <div>
            <div className="archive-kicker">{S.library.heroKicker}</div>
            <h1 className="mt-2 text-[1.8rem] font-semibold tracking-[-0.05em] text-fg">
              {S.library.title}
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-fg-muted">
              {S.library.heroBody}
            </p>
            <div className="page-status-strip mt-3">
              <span className="archive-inline-status archive-inline-status-muted">
                {S.library.paperCount(total)}
              </span>
              <span className="archive-inline-status archive-inline-status-muted">
                {S.library.collectionReady} {statusMetaCount(papers, 'completed')}
              </span>
              <span className="archive-inline-status archive-inline-status-muted">
                {S.library.collectionActive} {activityCount}
              </span>
            </div>
          </div>
        </div>

        <div className="library-controlbar mt-4 lg:grid-cols-[minmax(0,1fr)_auto_auto_auto] lg:items-center">
          <div className="relative" role="search">
            <AppIcon name="search" className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-fg-muted" />
            <input
              type="text"
              placeholder={S.library.searchPlaceholder}
              value={searchValue}
              onChange={(e) => {
                setSearchValue(e.target.value);
                setSearch(e.target.value);
              }}
              className="w-full rounded-full border border-border bg-surface px-10 py-3 text-sm text-fg outline-none transition-colors placeholder:text-fg-muted focus:border-fg-muted"
              aria-label="논문 검색"
            />
          </div>

          <button
            onClick={() => setShowFilters(!showFilters)}
            className={`inline-flex items-center justify-center gap-2 rounded-full border px-4 py-3 text-xs transition-colors ${
              showFilters || hasActiveFilters
                ? 'border-accent/30 bg-accent/10 text-accent'
                : 'border-border bg-surface text-fg-secondary hover:border-fg-muted'
            }`}
            aria-expanded={showFilters}
            aria-label="필터 열기/닫기"
          >
            <AppIcon name="filter" className="w-3.5 h-3.5" />
            {S.library.filters}
            {hasActiveFilters && <span className="h-1.5 w-1.5 rounded-full bg-accent" />}
            <AppIcon
              name="chevron-down"
              className={`w-3 h-3 transition-transform ${showFilters ? 'rotate-180' : ''}`}
            />
          </button>

          {viewMode === 'grid' && (
            <Select
              value={`${filters.sort_by}:${filters.sort_order}`}
              onValueChange={(value) => {
                const [sort_by, sort_order] = value.split(':') as [
                  'created_at' | 'title' | 'year' | 'analyzed_at',
                  'asc' | 'desc',
                ];
                setFilters({ sort_by, sort_order });
              }}
              aria-label="정렬 기준"
              className="rounded-full"
              options={[
                { value: 'created_at:desc', label: S.library.newestFirst },
                { value: 'created_at:asc', label: S.library.oldestFirst },
                { value: 'title:asc', label: S.library.titleAZ },
                { value: 'title:desc', label: S.library.titleZA },
                { value: 'year:desc', label: S.library.yearNewest },
                { value: 'year:asc', label: S.library.yearOldest },
                { value: 'analyzed_at:desc', label: S.library.recentlyAnalyzed },
              ]}
            />
          )}

          <div className="inline-flex items-center rounded-full border border-border bg-surface p-1">
            <button
              onClick={() => setViewMode('list')}
              className={`rounded-full px-3 py-2 text-xs transition-colors ${
                viewMode === 'list'
                  ? 'bg-accent/10 text-accent'
                  : 'text-fg-muted hover:text-fg-secondary'
              }`}
              aria-label={S.library.listView}
            >
              {S.library.listView}
            </button>
            <button
              onClick={() => setViewMode('grid')}
              className={`rounded-full px-3 py-2 text-xs transition-colors ${
                viewMode === 'grid'
                  ? 'bg-accent/10 text-accent'
                  : 'text-fg-muted hover:text-fg-secondary'
              }`}
              aria-label={S.library.gridView}
            >
              {S.library.gridView}
            </button>
          </div>
        </div>
      </section>

      {showFilters && (
        <section className="library-filter-panel mb-4">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-2xs uppercase tracking-[0.16em] text-fg-muted">분류 기준</div>
              <div className="mt-1 text-sm leading-6 text-fg-secondary">분야와 상태로 먼저 좁히고, 연도와 태그는 보조 기준으로 쓰세요.</div>
            </div>
            {hasActiveFilters && (
              <button
                onClick={clearFilters}
                className="rounded-full border border-border px-3 py-2 text-xs text-fg-secondary transition-colors hover:border-fg-muted hover:text-fg"
              >
                {S.library.clearAll}
              </button>
            )}
          </div>

          <div className="mb-4">
            <div className="mb-2 text-2xs text-fg-muted">{S.library.domain}</div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setFilters({ domain: undefined })}
                className={`rounded-full px-3 py-2 text-xs transition-colors ${
                  !filters.domain
                    ? 'bg-accent/10 text-accent'
                    : 'border border-border text-fg-muted hover:border-fg-muted hover:text-fg'
                }`}
              >
                {S.library.allDomains}
              </button>
              {getAllAgents().map((agent) => (
                <button
                  key={agent.domain}
                  type="button"
                  onClick={() => setFilters({ domain: agent.domain })}
                  className={`rounded-full px-3 py-2 text-xs transition-colors ${
                    filters.domain === agent.domain
                      ? 'bg-accent/10 text-accent'
                      : 'border border-border text-fg-muted hover:border-fg-muted hover:text-fg'
                  }`}
                >
                  {agent.domain_display}
                </button>
              ))}
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
            <div>
              <div className="mb-2 text-2xs text-fg-muted">{S.library.status}</div>
              <div className="flex flex-wrap gap-2">
                {[
                  { value: '', label: S.library.allStatuses },
                  { value: 'pending', label: S.status.pending },
                  { value: 'analyzing', label: S.status.analyzing },
                  { value: 'completed', label: S.status.analyzed },
                  { value: 'error', label: S.status.error },
                ].map((option) => (
                  <button
                    key={option.value || 'all'}
                    type="button"
                    onClick={() => setFilters({ status: (option.value as PaperStatus) || undefined })}
                    className={`rounded-full px-3 py-2 text-xs transition-colors ${
                      (filters.status || '') === option.value
                        ? 'bg-accent/10 text-accent'
                        : 'border border-border text-fg-muted hover:border-fg-muted hover:text-fg'
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="mb-2 block text-2xs text-fg-muted">
                  {S.library.year}
                </label>
                <input
                  type="number"
                  min={1990}
                  max={new Date().getFullYear()}
                  placeholder={S.library.anyYear}
                  value={filters.year || ''}
                  onChange={(e) =>
                    setFilters({
                      year: e.target.value ? parseInt(e.target.value, 10) : undefined,
                    })
                  }
                  className="w-full rounded-full border border-border bg-surface px-4 py-3 text-sm text-fg outline-none transition-colors placeholder:text-fg-muted focus:border-fg-muted"
                />
              </div>

              <div>
                <label className="mb-2 block text-2xs text-fg-muted">
                  {S.library.tags}
                </label>
                <Select
                  value={filters.tags?.[0] || 'all'}
                  onValueChange={(value) => setFilters({ tags: value === 'all' ? undefined : [value] })}
                  className="w-full rounded-full"
                  aria-label={S.library.tags}
                  options={[
                    { value: 'all', label: S.library.allTags },
                    ...availableTags.map((tag) => ({ value: tag, label: tag })),
                  ]}
                />
              </div>
            </div>
          </div>
        </section>
      )}

      {error && (
        <div className="mb-5 archive-inline-status archive-inline-status-error">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-20" role="status" aria-busy="true">
          <div className="flex flex-col items-center gap-3">
            <Loader2 className="w-6 h-6 text-accent animate-spin" />
            <span className="text-sm text-fg-muted">{S.library.loading}</span>
          </div>
        </div>
      )}

      {!loading && papers.length === 0 && (
        <div className="archive-panel px-6 py-16 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full border border-border bg-bg">
            <AppIcon name="library" className="w-6 h-6 text-fg-muted" />
          </div>
          <h3 className="text-lg font-semibold text-fg-secondary mb-2">
            {hasActiveFilters ? S.library.noMatch : S.library.noPapers}
          </h3>
          <p className="mx-auto max-w-md text-sm leading-relaxed text-fg-muted mb-4">
            {hasActiveFilters
              ? S.library.noMatchDesc
              : S.library.noPapersDesc}
          </p>
          {hasActiveFilters ? (
            <button
              onClick={clearFilters}
              className="rounded-full border border-border px-4 py-2 text-sm text-fg transition-colors hover:border-fg-muted"
            >
              {S.library.clearFilters}
            </button>
          ) : (
            <button
              onClick={handleGoUpload}
              className="btn-primary"
            >
              <AppIcon name="upload" className="w-4 h-4" />
              {S.library.emptyCta}
            </button>
          )}
        </div>
      )}

      {!loading && papers.length > 0 && viewMode === 'list' && (
        <section className="overflow-x-auto rounded-surface border border-border/60 bg-surface/90">
          <table className="library-table min-w-[720px]">
            <thead>
              <tr>
                <SortableTh
                  label="제목"
                  colKey="title"
                  activeKey={filters.sort_by}
                  order={filters.sort_order}
                  onSort={toggleSort}
                />
                <th scope="col">{S.library.status}</th>
                <th scope="col">분류</th>
                <th scope="col">설명 수준</th>
                <SortableTh
                  label={S.library.year}
                  colKey="year"
                  activeKey={filters.sort_by}
                  order={filters.sort_order}
                  onSort={toggleSort}
                />
                <SortableTh
                  label={S.library.recentActivity}
                  colKey="analyzed_at"
                  activeKey={filters.sort_by}
                  order={filters.sort_order}
                  onSort={toggleSort}
                />
                <th scope="col" className="w-12">
                  <span className="sr-only">{S.library.more}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {papers.map((paper) => (
                <PaperTableRow
                  key={paper.id}
                  paper={paper}
                  onOpen={handleOpenPaper}
                  onDelete={handleDeletePaper}
                />
              ))}
            </tbody>
          </table>
        </section>
      )}

      {!loading && papers.length > 0 && viewMode === 'grid' && (
        <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {papers.map((paper) => (
            <PaperArchiveCard
              key={paper.id}
              paper={paper}
              onOpen={handleOpenPaper}
              onDelete={handleDeletePaper}
            />
          ))}
        </section>
      )}

      {!loading && totalPages > 1 && (
        <div className="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-border/50 pt-5">
          <span className="text-xs text-fg-muted">
            {S.library.showing(from, to, total)}
          </span>

          <div className="flex items-center gap-1">
            <button
              onClick={() => goToPage(page - 1)}
              disabled={page <= 1}
              className="flex h-9 w-9 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg disabled:opacity-40"
              aria-label={S.library.prevPage}
            >
              <ChevronLeft className="w-4 h-4" />
            </button>

            {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
              let pageNum: number;
              if (totalPages <= 5) {
                pageNum = i + 1;
              } else if (page <= 3) {
                pageNum = i + 1;
              } else if (page >= totalPages - 2) {
                pageNum = totalPages - 4 + i;
              } else {
                pageNum = page - 2 + i;
              }

              return (
                <button
                  key={pageNum}
                  onClick={() => goToPage(pageNum)}
                  className={`flex h-9 w-9 items-center justify-center rounded-full text-xs transition-colors ${
                    pageNum === page
                      ? 'bg-accent/10 text-accent'
                      : 'text-fg-muted hover:bg-surface-hover hover:text-fg'
                  }`}
                >
                  {pageNum}
                </button>
              );
            })}

            <button
              onClick={() => goToPage(page + 1)}
              disabled={page >= totalPages}
              className="flex h-9 w-9 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg disabled:opacity-40"
              aria-label={S.library.nextPage}
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      <Modal open={deleteModal.show} onClose={cancelDelete}>
        <div className="mb-4 flex items-start gap-3">
          <div
            className="border border-danger/20 bg-danger/10 p-2"
            style={{ borderRadius: 'var(--radius-control)' }}
          >
            <AlertCircle className="w-5 h-5 text-danger" />
          </div>
          <div className="flex-1">
            <h3 className="mb-1 text-base font-semibold text-fg">
              {S.library.deleteTitle}
            </h3>
            <p className="text-sm text-fg-muted">
              {S.library.deleteWarning}
            </p>
          </div>
        </div>

        <div className="mb-6 space-y-3">
          <div
            className="border border-border/50 bg-surface/30 p-3"
            style={{ borderRadius: 'var(--radius-control)' }}
          >
            <p className="mb-1 text-sm font-medium text-fg-secondary">
              {deleteModal.paperTitle}
            </p>
            <p className="text-2xs text-fg-muted">
              {S.library.paperId(deleteModal.paperId ?? '')}
            </p>
          </div>

          <div
            className="border border-danger/20 bg-danger/5 p-3"
            style={{ borderRadius: 'var(--radius-control)' }}
          >
            <p className="text-xs leading-relaxed text-danger">
              <strong>{S.library.deleteDetails}</strong>
              <br />
              • {S.library.deleteItem1}
              <br />
              • {S.library.deleteItem2}
              <br />
              • {S.library.deleteItem3}
            </p>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2">
          <button
            onClick={cancelDelete}
            disabled={deleting}
            className="btn-ghost text-sm"
          >
            {S.library.cancelBtn}
          </button>
          <button
            onClick={confirmDelete}
            disabled={deleting}
            className="btn-danger text-sm"
          >
            {deleting ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                {S.library.deleting}
              </>
            ) : (
              <>
                <AppIcon name="delete" className="w-3.5 h-3.5" />
                {S.library.deleteBtn}
              </>
            )}
          </button>
        </div>
      </Modal>
    </div>
  );
}
