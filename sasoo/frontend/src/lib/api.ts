// Sasoo API Client
// Communicates with FastAPI backend at localhost:8000

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Paper {
  id: number;
  title: string;
  authors: string | null;
  year: number | null;
  journal: string | null;
  doi: string | null;
  domain: string;
  agent_used: string;
  folder_name: string;
  tags: string | null;
  status: PaperStatus;
  analyzed_at: string | null;
  notes: string | null;
  created_at: string | null;
}

export type PaperStatus =
  | 'pending'
  | 'analyzing'
  | 'completed'
  | 'error';

export interface PaperFilters {
  domain?: string;
  year?: number;
  tags?: string[];
  status?: PaperStatus;
  search?: string;
  sort_by?: 'created_at' | 'title' | 'year' | 'analyzed_at';
  sort_order?: 'asc' | 'desc';
  page?: number;
  page_size?: number;
}

export interface PaperUpdateData {
  title?: string;
  tags?: string;
  domain?: string;
  notes?: string;
}

export interface PaginatedResponse {
  papers: Paper[];
  total: number;
  page: number;
  page_size: number;
}

// UploadResponse is the same as Paper (backend returns PaperResponse)
export type UploadResponse = Paper;

// Analysis types
export type AnalysisPhase = 'screening' | 'visual' | 'recipe' | 'deep_dive';
export type PhaseStatusValue = 'pending' | 'running' | 'completed' | 'error';

export interface PhaseInfo {
  phase: AnalysisPhase;
  status: PhaseStatusValue;
  started_at: string | null;
  completed_at: string | null;
  model_used: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: number | null;
  error_message: string | null;
}

export interface AnalysisStatus {
  paper_id: number;
  overall_status: string; // pending | running | completed | error
  phases: PhaseInfo[];
  progress_pct: number; // 0-100
  current_phase: AnalysisPhase | null;
  total_cost_usd: number;
  total_tokens_in: number;
  total_tokens_out: number;
}

export interface AnalysisResults {
  paper_id: number;
  status: AnalysisStatus;
  screening: Record<string, unknown> | null;
  visual: Record<string, unknown> | null;
  recipe: Record<string, unknown> | null;
  deep_dive: Record<string, unknown> | null;
}

// Figure types
export interface Figure {
  id: number | null;
  paper_id: number;
  figure_num: string | null;
  caption: string | null;
  file_path: string | null;
  ai_analysis: string | null;
  quality: string | null;
  detailed_explanation: string | null;
}

export interface FigureListResponse {
  figures: Figure[];
  total: number;
}

export interface FigureExplanationResponse {
  figure_id: number;
  paper_id: number;
  figure_num: string | null;
  caption: string | null;
  explanation: string;
  model_used: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
}

// Recipe types
export interface Recipe {
  paper_id: number;
  recipe: Record<string, unknown>;
  model_used: string | null;
  created_at: string | null;
}

// Mermaid diagram types
export interface MermaidDiagram {
  paper_id: number;
  mermaid_code: string;
  diagram_type: string;
  description: string | null;
}

// Report types
export interface Report {
  paper_id: number;
  title: string;
  markdown: string;
  generated_at: string;
}

// PaperBanana types (visual summary)
export interface PaperBanana {
  paper_id: number;
  image_path: string;
  image_url: string;
  width: number;
  height: number;
}

// Visualization plan types (Gemini Pro 3 → up to 5 items)
export interface VisualizationItem {
  id: number;
  title: string;
  tool: 'mermaid' | 'paperbanana';
  diagram_type: string;
  description: string;
  category: string;
  mermaid_code: string | null;
  image_url: string | null;
  image_path: string | null;
  status: 'pending' | 'generating' | 'completed' | 'error';
  error_message: string | null;
}

export interface VisualizationPlan {
  paper_id: number;
  items: VisualizationItem[];
  total_count: number;
  model_used: string;
  planned_at: string | null;
}

// Settings types
export interface Settings {
  gemini_api_key: string;
  anthropic_api_key: string;
  library_path: string;
  theme: 'dark' | 'light';
  default_domain: string;
  auto_analyze: boolean;
  language: string;
  max_concurrent_analyses: number;
  gemini_model: string;
  anthropic_model: string;
}

export interface CostSummary {
  monthly_total: number;
  monthly_budget: number;
  paper_count_this_month: number;
  average_cost_per_paper: number;
  model_breakdown: {
    model: string;
    cost: number;
    calls: number;
  }[];
  daily_costs: {
    date: string;
    cost: number;
  }[];
}

// ---------------------------------------------------------------------------
// API Error
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public details?: unknown
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// ---------------------------------------------------------------------------
// Base request helper
// ---------------------------------------------------------------------------

const API_BASE = '/api';

async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE}${endpoint}`;

  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  // Don't set Content-Type for FormData (browser sets boundary automatically)
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorMessage = `Request failed: ${response.statusText}`;
    let details: unknown = undefined;
    try {
      const errorBody = await response.json();
      errorMessage = errorBody.detail || errorBody.message || errorMessage;
      details = errorBody;
    } catch {
      // Response body is not JSON
    }
    throw new ApiError(response.status, errorMessage, details);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

// ---------------------------------------------------------------------------
// Paper endpoints
// ---------------------------------------------------------------------------

export async function uploadPaper(
  file: File,
  onProgress?: (progress: number) => void
): Promise<UploadResponse> {
  // Use XMLHttpRequest for progress tracking
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const formData = new FormData();
    formData.append('file', file);

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable && onProgress) {
        const progress = Math.round((event.loaded / event.total) * 100);
        onProgress(progress);
      }
    });

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          reject(new ApiError(xhr.status, 'Invalid response'));
        }
      } else {
        let message = 'Upload failed';
        try {
          const body = JSON.parse(xhr.responseText);
          message = body.detail || body.message || message;
        } catch {
          // ignore parse error
        }
        reject(new ApiError(xhr.status, message));
      }
    });

    xhr.addEventListener('error', () => {
      reject(new ApiError(0, 'Network error during upload'));
    });

    xhr.addEventListener('abort', () => {
      reject(new ApiError(0, 'Upload aborted'));
    });

    xhr.open('POST', `${API_BASE}/papers/upload`);
    xhr.send(formData);
  });
}

export async function getPapers(
  filters?: PaperFilters
): Promise<PaginatedResponse> {
  const params = new URLSearchParams();

  if (filters) {
    if (filters.domain) params.set('domain', filters.domain);
    if (filters.year) params.set('year', String(filters.year));
    if (filters.status) params.set('status', filters.status);
    if (filters.search) params.set('search', filters.search);
    if (filters.sort_by) params.set('sort_by', filters.sort_by);
    if (filters.sort_order) params.set('sort_order', filters.sort_order);
    if (filters.page) params.set('page', String(filters.page));
    if (filters.page_size) params.set('page_size', String(filters.page_size));
  }

  const query = params.toString();
  return request<PaginatedResponse>(
    `/papers${query ? `?${query}` : ''}`
  );
}

export async function getPaper(id: string | number): Promise<Paper> {
  return request<Paper>(`/papers/${id}`);
}

export async function deletePaper(id: string | number): Promise<void> {
  return request<void>(`/papers/${id}`, { method: 'DELETE' });
}

export async function updatePaper(
  id: string | number,
  data: PaperUpdateData
): Promise<Paper> {
  return request<Paper>(`/papers/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

// ---------------------------------------------------------------------------
// Analysis endpoints
// ---------------------------------------------------------------------------

export async function runAnalysis(paperId: string): Promise<AnalysisStatus> {
  return request<AnalysisStatus>(`/analysis/${paperId}/run`, {
    method: 'POST',
  });
}

export async function getAnalysisStatus(
  paperId: string
): Promise<AnalysisStatus> {
  return request<AnalysisStatus>(`/analysis/${paperId}/status`);
}

export async function getAnalysisResults(
  paperId: string
): Promise<AnalysisResults> {
  return request<AnalysisResults>(`/analysis/${paperId}/results`);
}

// ---------------------------------------------------------------------------
// Result sub-resource endpoints
// ---------------------------------------------------------------------------

export async function getFigures(paperId: string): Promise<FigureListResponse> {
  return request<FigureListResponse>(`/analysis/${paperId}/figures`);
}

export async function generateFigureExplanation(
  paperId: string,
  figureId: number
): Promise<FigureExplanationResponse> {
  return request<FigureExplanationResponse>(
    `/analysis/${paperId}/figures/${figureId}/explain`,
    { method: 'POST' }
  );
}

export async function getRecipe(paperId: string): Promise<Recipe> {
  return request<Recipe>(`/analysis/${paperId}/recipe`);
}

export async function getMermaid(paperId: string): Promise<MermaidDiagram> {
  return request<MermaidDiagram>(`/analysis/${paperId}/mermaid`);
}

export async function getReport(paperId: string): Promise<Report> {
  return request<Report>(`/analysis/${paperId}/report`);
}

export async function getVisualizations(
  paperId: string
): Promise<VisualizationPlan> {
  return request<VisualizationPlan>(`/analysis/${paperId}/visualizations`);
}

export async function generatePaperBanana(
  paperId: string
): Promise<PaperBanana> {
  return request<PaperBanana>(`/analysis/${paperId}/paperbanana`, {
    method: 'POST',
  });
}

// ---------------------------------------------------------------------------
// Settings endpoints
// ---------------------------------------------------------------------------

export async function getSettings(): Promise<Settings> {
  return request<Settings>('/settings');
}

export async function updateSettings(
  data: Partial<Settings>
): Promise<Settings> {
  return request<Settings>('/settings', {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function getCostSummary(): Promise<CostSummary> {
  return request<CostSummary>('/settings/cost');
}

// ---------------------------------------------------------------------------
// PDF URL helper
// ---------------------------------------------------------------------------

export function getPdfUrl(paperId: string): string {
  return `${API_BASE}/papers/${paperId}/pdf`;
}

// ---------------------------------------------------------------------------
// Domain list helper
// ---------------------------------------------------------------------------

export const DOMAINS = [
  { key: 'optics', label: 'Optics & Photonics', labelKo: '광학/포토닉스', agent: 'photon' },
  { key: 'bio', label: 'Biology & Biochemistry', labelKo: '생물/생화학', agent: 'cell' },
  { key: 'ai_ml', label: 'AI & Machine Learning', labelKo: '인공지능/머신러닝', agent: 'neural' },
  { key: 'ee', label: 'Electrical Engineering', labelKo: '전기/전자공학', agent: 'circuit' },
] as const;

export type Domain = (typeof DOMAINS)[number]['key'];
