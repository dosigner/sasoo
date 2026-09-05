import { useState, useEffect, useCallback, useRef } from 'react';
import { S } from '@/lib/strings';
import {
  type Paper,
  type PaperFilters,
  type PaperUpdateData,
  getPapers,
  getPaper,
  deletePaper as apiDeletePaper,
  updatePaper as apiUpdatePaper,
  ApiError,
} from '@/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface UsePapersReturn {
  /** List of papers matching current filters */
  papers: Paper[];
  /** Total count of papers matching filters */
  total: number;
  /** Server-side count of completed papers under the same (filter-free) scope.
   * Null while a search/filter is active (denominator would not match `total`) or on fetch failure. */
  completedTotal: number | null;
  /** Current page number */
  page: number;
  /** Total pages */
  totalPages: number;
  /** Whether papers are loading */
  loading: boolean;
  /** Error message */
  error: string | null;
  /** Current active filters */
  filters: PaperFilters;
  /** Update filters (triggers refetch) */
  setFilters: (filters: Partial<PaperFilters>) => void;
  /** Set search query (debounced) */
  setSearch: (query: string) => void;
  /** Go to a specific page */
  goToPage: (page: number) => void;
  /** Refresh paper list */
  refresh: () => Promise<void>;
  /** Delete a paper by ID */
  deletePaper: (id: string) => Promise<void>;
  /** Update a paper */
  updatePaper: (id: string, data: PaperUpdateData) => Promise<Paper>;
  /** Get a single paper (cached from list or fetched) */
  getPaperById: (id: string) => Promise<Paper>;
  /** All unique tags across loaded papers */
  availableTags: string[];
  /** All unique domains across loaded papers */
  availableDomains: string[];
}

// ---------------------------------------------------------------------------
// Debounce helper
// ---------------------------------------------------------------------------

function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debouncedValue;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function usePapers(initialFilters?: PaperFilters): UsePapersReturn {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [total, setTotal] = useState(0);
  const [completedTotal, setCompletedTotal] = useState<number | null>(null);
  const [totalPages, setTotalPages] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFiltersState] = useState<PaperFilters>({
    page: 1,
    page_size: 20,
    sort_by: 'created_at',
    sort_order: 'desc',
    ...initialFilters,
  });
  const [searchInput, setSearchInput] = useState(
    initialFilters?.search || ''
  );

  const mountedRef = useRef(true);
  const debouncedSearch = useDebounce(searchInput, 300);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Update filters when debounced search changes
  useEffect(() => {
    setFiltersState((prev) => ({
      ...prev,
      search: debouncedSearch || undefined,
      page: 1, // Reset to first page on search
    }));
  }, [debouncedSearch]);

  // -----------------------------------------------------------------------
  // Fetch papers
  // -----------------------------------------------------------------------
  const fetchPapers = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await getPapers(filters);
      if (!mountedRef.current) return;

      setPapers(response.papers);
      setTotal(response.total);
      setTotalPages(Math.ceil(response.total / (filters.page_size || 20)));
    } catch (err) {
      if (!mountedRef.current) return;
      if (err instanceof Error) console.warn('[papers] load error:', err.message);
      setError(S.error.loadPapersFailed);
    } finally {
      if (mountedRef.current) setLoading(false);
    }

    // 분석 완료 수는 서버 total 기준. 검색·필터가 걸린 상태에선 위 total과 분모가
    // 달라지므로(각각 다른 조건의 결과 수) 조회하지 않고 칩을 숨긴다.
    const hasActiveFilters = Boolean(
      filters.domain ||
        filters.year ||
        filters.status ||
        filters.search ||
        (filters.tags && filters.tags.length > 0)
    );
    if (hasActiveFilters) {
      if (mountedRef.current) setCompletedTotal(null);
      return;
    }
    try {
      const completedResponse = await getPapers({ status: 'completed', page: 1, page_size: 1 });
      if (mountedRef.current) setCompletedTotal(completedResponse.total);
    } catch {
      if (mountedRef.current) setCompletedTotal(null);
    }
  }, [filters]);

  // Fetch whenever filters change
  useEffect(() => {
    fetchPapers();
  }, [fetchPapers]);

  // -----------------------------------------------------------------------
  // Public methods
  // -----------------------------------------------------------------------

  const setFilters = useCallback((partial: Partial<PaperFilters>) => {
    setFiltersState((prev) => ({
      ...prev,
      ...partial,
      // Reset page to 1 when filters change (unless page is explicitly set)
      page: partial.page ?? 1,
    }));
  }, []);

  const setSearch = useCallback((query: string) => {
    setSearchInput(query);
  }, []);

  const goToPage = useCallback((page: number) => {
    setFiltersState((prev) => ({ ...prev, page }));
  }, []);

  const refresh = useCallback(async () => {
    await fetchPapers();
  }, [fetchPapers]);

  const deletePaper = useCallback(
    async (id: string) => {
      try {
        await apiDeletePaper(id);
        if (!mountedRef.current) return;
        // Remove from local state immediately
        setPapers((prev) => prev.filter((p) => String(p.id) !== id));
        setTotal((prev) => prev - 1);
      } catch (err) {
        throw err instanceof ApiError
          ? err
          : new Error(S.error.deletePaperFailed);
      }
    },
    []
  );

  const updatePaper = useCallback(
    async (id: string, data: PaperUpdateData): Promise<Paper> => {
      try {
        const updated = await apiUpdatePaper(id, data);
        if (!mountedRef.current) return updated;
        // Update in local state
        setPapers((prev) =>
          prev.map((p) => (String(p.id) === id ? updated : p))
        );
        return updated;
      } catch (err) {
        throw err instanceof ApiError
          ? err
          : new Error(S.error.updatePaperFailed);
      }
    },
    []
  );

  const getPaperById = useCallback(
    async (id: string): Promise<Paper> => {
      // Try to find in current papers first
      const cached = papers.find((p) => String(p.id) === id);
      if (cached) return cached;
      // Otherwise fetch from API
      return getPaper(id);
    },
    [papers]
  );

  // -----------------------------------------------------------------------
  // Derived data
  // -----------------------------------------------------------------------

  const availableTags = Array.from(
    new Set(
      papers
        .map((p) => p.tags)
        .filter((t): t is string => t !== null)
        .flatMap((t) => t.split(',').map((s) => s.trim()))
        .filter(Boolean)
    )
  ).sort();

  const availableDomains = Array.from(
    new Set(papers.map((p) => p.domain).filter(Boolean))
  ).sort();

  return {
    papers,
    total,
    completedTotal,
    page: filters.page || 1,
    totalPages,
    loading,
    error,
    filters,
    setFilters,
    setSearch,
    goToPage,
    refresh,
    deletePaper,
    updatePaper,
    getPaperById,
    availableTags,
    availableDomains,
  };
}
