import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Search,
  LayoutGrid,
  List,
  Filter,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FileText,
  Trash2,
  Clock,
  Tag,
  Loader2,
  AlertCircle,
  BookOpen,
} from 'lucide-react';
import { usePapers } from '@/hooks/usePapers';
import { DOMAINS, type Paper, type PaperStatus } from '@/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ViewMode = 'grid' | 'list';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function statusBadge(status: PaperStatus): {
  label: string;
  classes: string;
} {
  switch (status) {
    case 'completed':
      return { label: 'Analyzed', classes: 'badge-success' };
    case 'analyzing':
      return { label: 'Analyzing', classes: 'badge-primary' };
    case 'pending':
      return { label: 'Pending', classes: 'badge-warning' };
    case 'error':
      return { label: 'Error', classes: 'badge-error' };
    default:
      return { label: status, classes: 'badge-primary' };
  }
}

// ---------------------------------------------------------------------------
// Paper Card (Grid View)
// ---------------------------------------------------------------------------

interface PaperCardProps {
  paper: Paper;
  onOpen: (id: string) => void;
  onDelete: (id: string, title: string) => void;
}

function PaperCard({ paper, onOpen, onDelete }: PaperCardProps) {
  const badge = statusBadge(paper.status);

  return (
    <div
      className="card-hover cursor-pointer group"
      onClick={() => onOpen(String(paper.id))}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4 text-primary-400 shrink-0 mt-0.5" />
          <h3 className="text-sm font-medium text-surface-200 line-clamp-2 leading-snug">
            {paper.title}
          </h3>
        </div>
        <span className={`shrink-0 text-2xs ${badge.classes}`}>
          {badge.label}
        </span>
      </div>

      {/* Authors */}
      {paper.authors && (
        <p className="text-2xs text-surface-500 mb-2 truncate">
          {paper.authors}
        </p>
      )}

      {/* Meta */}
      <div className="flex items-center gap-2 text-2xs text-surface-500 mb-3">
        {paper.year && <span>{paper.year}</span>}
        {paper.year && <span className="w-1 h-1 rounded-full bg-surface-600" />}
        <span className="badge-primary text-2xs">{paper.domain}</span>
      </div>

      {/* Tags */}
      {paper.tags && (
        <div className="flex flex-wrap gap-1 mb-3">
          {paper.tags.split(',').map((tag) => tag.trim()).filter(Boolean).slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="badge bg-surface-700/50 text-surface-400 text-2xs"
            >
              <Tag className="w-2.5 h-2.5 mr-0.5" />
              {tag}
            </span>
          ))}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between pt-2 border-t border-surface-700/50">
        <div className="flex items-center gap-1 text-2xs text-surface-500">
          <Clock className="w-3 h-3" />
          {paper.created_at ? formatDate(paper.created_at) : '-'}
        </div>

        {/* Delete */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete(String(paper.id), paper.title);
          }}
          className="p-1 rounded opacity-0 group-hover:opacity-100 text-surface-500 hover:text-red-400 hover:bg-red-500/10 transition-all"
          title="Delete paper and all associated files"
          aria-label="삭제"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Paper Row (List View)
// ---------------------------------------------------------------------------

function PaperRow({ paper, onOpen, onDelete }: PaperCardProps) {
  const badge = statusBadge(paper.status);

  return (
    <div
      className="flex items-center gap-4 px-4 py-3 bg-surface-800 border border-surface-700 rounded-lg hover:border-primary-500/30 transition-colors cursor-pointer group"
      onClick={() => onOpen(String(paper.id))}
    >
      <FileText className="w-5 h-5 text-primary-400 shrink-0" />

      <div className="flex-1 min-w-0">
        <h3 className="text-sm font-medium text-surface-200 truncate">
          {paper.title}
        </h3>
        <div className="flex items-center gap-2 text-2xs text-surface-500 mt-0.5">
          {paper.authors && (
            <span className="truncate max-w-[300px]">
              {paper.authors}
            </span>
          )}
          {paper.year && (
            <>
              <span className="w-1 h-1 rounded-full bg-surface-600" />
              <span>{paper.year}</span>
            </>
          )}
        </div>
      </div>

      <span className="badge-primary text-2xs shrink-0">{paper.domain}</span>

      <span className={`shrink-0 text-2xs ${badge.classes}`}>
        {badge.label}
      </span>

      <div className="flex items-center gap-1 text-2xs text-surface-500 shrink-0 w-24">
        <Clock className="w-3 h-3" />
        {paper.created_at ? formatDate(paper.created_at) : '-'}
      </div>

      {/* Delete */}
      <div className="shrink-0" onClick={(e) => e.stopPropagation()}>
        <button
          onClick={() => onDelete(String(paper.id), paper.title)}
          className="p-1.5 rounded opacity-0 group-hover:opacity-100 text-surface-500 hover:text-red-400 hover:bg-red-500/10 transition-all"
          title="Delete paper and all associated files"
          aria-label="삭제"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function Library() {
  const navigate = useNavigate();
  const [viewMode, setViewMode] = useState<ViewMode>('grid');
  const [showFilters, setShowFilters] = useState(false);
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
  } = usePapers();

  const handleOpenPaper = useCallback(
    (id: string) => {
      navigate(`/workbench/${id}`);
    },
    [navigate]
  );

  const handleDeletePaper = useCallback(
    async (id: string, title: string) => {
      setDeleteModal({
        show: true,
        paperId: id,
        paperTitle: title,
      });
    },
    []
  );

  const confirmDelete = useCallback(async () => {
    if (!deleteModal.paperId) return;

    setDeleting(true);
    try {
      await deletePaper(deleteModal.paperId);
      setDeleteModal({ show: false, paperId: null, paperTitle: '' });
    } catch {
      // Error handled in hook
    } finally {
      setDeleting(false);
    }
  }, [deleteModal.paperId, deletePaper]);

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
  }, [setFilters, setSearch]);

  const hasActiveFilters =
    filters.domain || filters.year || filters.status || (filters.tags && filters.tags.length > 0);

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-surface-100 flex items-center gap-2">
            <BookOpen className="w-5 h-5 text-primary-400" />
            Paper Library
          </h1>
          <p className="text-sm text-surface-500 mt-1">
            {total} paper{total !== 1 ? 's' : ''} in your library
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* View mode toggle */}
          <div className="flex items-center bg-surface-800 rounded-lg border border-surface-700 p-0.5">
            <button
              onClick={() => setViewMode('grid')}
              className={`p-1.5 rounded transition-colors ${
                viewMode === 'grid'
                  ? 'bg-surface-700 text-surface-200'
                  : 'text-surface-500 hover:text-surface-300'
              }`}
              aria-label="그리드 보기"
            >
              <LayoutGrid className="w-4 h-4" />
            </button>
            <button
              onClick={() => setViewMode('list')}
              className={`p-1.5 rounded transition-colors ${
                viewMode === 'list'
                  ? 'bg-surface-700 text-surface-200'
                  : 'text-surface-500 hover:text-surface-300'
              }`}
              aria-label="리스트 보기"
            >
              <List className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Search and filter bar */}
      <div className="flex items-center gap-3 mb-4">
        {/* Search */}
        <div className="relative flex-1 max-w-md" role="search">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-500" />
          <input
            type="text"
            placeholder="Search by title, author, or keywords..."
            defaultValue={filters.search}
            onChange={(e) => setSearch(e.target.value)}
            className="input pl-10"
            aria-label="논문 검색"
          />
        </div>

        {/* Filter toggle */}
        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`btn-ghost text-xs ${
            showFilters || hasActiveFilters
              ? 'bg-surface-700 text-primary-400'
              : ''
          }`}
          aria-expanded={showFilters}
          aria-label="필터 열기/닫기"
        >
          <Filter className="w-3.5 h-3.5" />
          Filters
          {hasActiveFilters && (
            <span className="w-1.5 h-1.5 rounded-full bg-primary-400" />
          )}
          <ChevronDown
            className={`w-3 h-3 transition-transform ${
              showFilters ? 'rotate-180' : ''
            }`}
          />
        </button>

        {/* Sort */}
        <select
          value={`${filters.sort_by}:${filters.sort_order}`}
          onChange={(e) => {
            const [sort_by, sort_order] = e.target.value.split(':') as [
              'created_at' | 'title' | 'year' | 'analyzed_at',
              'asc' | 'desc',
            ];
            setFilters({ sort_by, sort_order });
          }}
          className="input w-auto min-w-[160px]"
        >
          <option value="created_at:desc">Newest first</option>
          <option value="created_at:asc">Oldest first</option>
          <option value="title:asc">Title A-Z</option>
          <option value="title:desc">Title Z-A</option>
          <option value="year:desc">Year (newest)</option>
          <option value="year:asc">Year (oldest)</option>
          <option value="analyzed_at:desc">Recently analyzed</option>
        </select>
      </div>

      {/* Filter panel */}
      {showFilters && (
        <div className="glass rounded-2xl p-4 mb-4 fade-in-up">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold text-surface-300 uppercase tracking-wider">
              Filters
            </h3>
            {hasActiveFilters && (
              <button
                onClick={clearFilters}
                className="text-2xs text-primary-400 hover:text-primary-300"
              >
                Clear all
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-3">
            {/* Domain filter */}
            <div>
              <label className="text-2xs text-surface-500 block mb-1">
                Domain
              </label>
              <select
                value={filters.domain || ''}
                onChange={(e) =>
                  setFilters({ domain: e.target.value || undefined })
                }
                className="input w-auto min-w-[160px]"
              >
                <option value="">All domains</option>
                {DOMAINS.map((domain) => (
                  <option key={domain.key} value={domain.key}>
                    {domain.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Year filter */}
            <div>
              <label className="text-2xs text-surface-500 block mb-1">
                Year
              </label>
              <input
                type="number"
                min={1990}
                max={new Date().getFullYear()}
                placeholder="Any year"
                value={filters.year || ''}
                onChange={(e) =>
                  setFilters({
                    year: e.target.value
                      ? parseInt(e.target.value, 10)
                      : undefined,
                  })
                }
                className="input w-auto min-w-[120px]"
              />
            </div>

            {/* Status filter */}
            <div>
              <label className="text-2xs text-surface-500 block mb-1">
                Status
              </label>
              <select
                value={filters.status || ''}
                onChange={(e) =>
                  setFilters({
                    status: (e.target.value as PaperStatus) || undefined,
                  })
                }
                className="input w-auto min-w-[140px]"
              >
                <option value="">All statuses</option>
                <option value="pending">Pending</option>
                <option value="analyzing">Analyzing</option>
                <option value="completed">Completed</option>
                <option value="error">Error</option>
              </select>
            </div>
          </div>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="flex items-center gap-2 text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 mb-4">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="flex items-center justify-center py-16" role="status" aria-busy="true">
          <div className="flex flex-col items-center gap-3">
            <Loader2 className="w-6 h-6 text-primary-400 animate-spin" />
            <span className="text-sm text-surface-400">Loading papers...</span>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!loading && papers.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <BookOpen className="w-12 h-12 text-surface-600 mb-4" />
          <h3 className="text-lg font-semibold text-surface-300 mb-2">
            {hasActiveFilters ? 'No papers match your filters' : 'No papers yet'}
          </h3>
          <p className="text-sm text-surface-500 max-w-sm mb-4">
            {hasActiveFilters
              ? 'Try adjusting your filters or search query.'
              : 'Upload your first academic paper to get started with AI-powered analysis.'}
          </p>
          {hasActiveFilters && (
            <button onClick={clearFilters} className="btn-secondary text-sm">
              Clear filters
            </button>
          )}
        </div>
      )}

      {/* Paper grid */}
      {!loading && papers.length > 0 && viewMode === 'grid' && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {papers.map((paper) => (
            <PaperCard
              key={paper.id}
              paper={paper}
              onOpen={handleOpenPaper}
              onDelete={handleDeletePaper}
            />
          ))}
        </div>
      )}

      {/* Paper list */}
      {!loading && papers.length > 0 && viewMode === 'list' && (
        <div className="space-y-2">
          {papers.map((paper) => (
            <PaperRow
              key={paper.id}
              paper={paper}
              onOpen={handleOpenPaper}
              onDelete={handleDeletePaper}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {!loading && totalPages > 1 && (
        <div className="flex items-center justify-between mt-6 pt-4 border-t border-surface-700">
          <span className="text-xs text-surface-500">
            Showing {(page - 1) * (filters.page_size || 20) + 1}-
            {Math.min(page * (filters.page_size || 20), total)} of {total}
          </span>

          <div className="flex items-center gap-1">
            <button
              onClick={() => goToPage(page - 1)}
              disabled={page <= 1}
              className="btn-ghost p-1.5 rounded-md"
              aria-label="이전 페이지"
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
                  className={`w-8 h-8 rounded text-xs transition-colors ${
                    pageNum === page
                      ? 'bg-primary-600 text-white'
                      : 'text-surface-400 hover:bg-surface-700 hover:text-surface-200'
                  }`}
                >
                  {pageNum}
                </button>
              );
            })}

            <button
              onClick={() => goToPage(page + 1)}
              disabled={page >= totalPages}
              className="btn-ghost p-1.5 rounded-md"
              aria-label="다음 페이지"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deleteModal.show && (
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 animate-fade-in"
          onClick={cancelDelete}
        >
          <div
            className="bg-surface-800 [.light_&]:bg-white border border-surface-700 [.light_&]:border-surface-200 rounded-2xl p-6 max-w-md w-full mx-4 shadow-2xl animate-slide-up"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-start gap-3 mb-4">
              <div className="p-2 rounded-lg bg-red-500/10 border border-red-500/20">
                <AlertCircle className="w-5 h-5 text-red-400" />
              </div>
              <div className="flex-1">
                <h3 className="text-base font-semibold text-surface-100 [.light_&]:text-surface-900 mb-1">
                  Delete Paper?
                </h3>
                <p className="text-sm text-surface-400 [.light_&]:text-surface-600">
                  This action cannot be undone.
                </p>
              </div>
            </div>

            {/* Content */}
            <div className="mb-6 space-y-3">
              <div className="bg-surface-700/30 [.light_&]:bg-surface-100 border border-surface-700/50 [.light_&]:border-surface-200 rounded-lg p-3">
                <p className="text-sm text-surface-300 [.light_&]:text-surface-700 font-medium mb-1">
                  {deleteModal.paperTitle}
                </p>
                <p className="text-2xs text-surface-500 [.light_&]:text-surface-600">
                  Paper ID: {deleteModal.paperId}
                </p>
              </div>

              <div className="bg-red-500/5 border border-red-500/20 rounded-lg p-3">
                <p className="text-xs text-red-400 [.light_&]:text-red-600 leading-relaxed">
                  <strong>The following will be permanently deleted:</strong>
                  <br />
                  • PDF file and all extracted figures
                  <br />
                  • Analysis results and metadata
                  <br />
                  • Associated folder in library directory
                </p>
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2 justify-end">
              <button
                onClick={cancelDelete}
                disabled={deleting}
                className="btn-ghost text-sm"
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={deleting}
                className="btn-danger text-sm"
              >
                {deleting ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Deleting...
                  </>
                ) : (
                  <>
                    <Trash2 className="w-3.5 h-3.5" />
                    Delete Permanently
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
