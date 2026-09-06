// Sasoo API Client
// Communicates with FastAPI backend

const BACKEND_PORT = 8000;
const NETWORK_RETRY_DELAYS_MS = [300, 900, 1800];
const ELECTRON_NETWORK_RETRY_DELAYS_MS = [500, 1000, 2000, 4000, 8000];

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
  explanation_level?: string | null;
  folder_name: string;
  tags: string | null;
  status: PaperStatus;
  analyzed_at: string | null;
  notes: string | null;
  created_at: string | null;
  text_ready: boolean;
  visual_ready: boolean;
  visual_state: VisualState;
  visual_error: string | null;
  artifacts_ready: boolean;
}

export type ArtifactStatus = Pick<Paper, 'text_ready' | 'visual_ready' | 'visual_state'>;

export type PaperStatus =
  | 'pending'
  | 'analyzing'
  | 'completed'
  | 'error'
  | 'cancelled';

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
  explanation_level?: string;
  analysis_focus?: { chips: string[]; note: string };
}

interface PaginatedResponse {
  completed_count?: number;
  papers: Paper[];
  total: number;
  page: number;
  page_size: number;
}

// UploadResponse is the same as Paper (backend returns PaperResponse)
export type UploadResponse = Paper;

// Analysis types
export type AnalysisPhase = 'screening' | 'citation' | 'visual' | 'recipe' | 'deep_dive';
export type PhaseStatusValue = 'pending' | 'running' | 'completed' | 'error';
export type VisualState = 'ready' | 'running' | 'error' | 'partial';
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
  /** 이 phase의 최신 결과가 현재 설정과 다른 (provider, model, effort)로 만들어졌으면 그 모델명. */
  stale_model?: string | null;
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
  citation: Record<string, unknown> | null;
  visual: Record<string, unknown> | null;
  recipe: Record<string, unknown> | null;
  deep_dive: Record<string, unknown> | null;
}

// Figure types
export interface Figure {
  id: number | null;
  paper_id: number;
  figure_num: string | null;
  page_number?: number | null;
  bbox?: [number, number, number, number] | null;
  caption: string | null;
  file_path: string | null;
  ai_analysis: string | null;
  quality: string | null;
  detailed_explanation: string | null;
  extraction_engine?: 'odl-java' | 'odl-hybrid' | null;
  confidence?: number | null;
  classifier_label?: string | null;
  classifier_model?: string | null;
  parent_figure_id?: number | null;
  is_composite?: boolean | null;
  resolver_version?: string | null;
  extraction_status?: string | null;
}

export interface PdfNavigationRequest {
  page: number;
  requestId: string;
  source: 'figure' | 'table' | 'citation' | 'recipe' | 'guide';
  /** 선택 — bbox는 PDF 포인트·좌하단 원점. 없으면 페이지 이동만 한다. */
  highlight?: { bbox: [number, number, number, number] } | null;
}

export interface FigureListResponse {
  figures: Figure[];
  total: number;
  visual_state: VisualState;
  visual_error?: string | null;
  artifacts_ready: boolean;
  artifacts_error?: string | null;
}

export interface Table {
  id: number | null;
  paper_id: number;
  table_num: string | null;
  caption: string | null;
  page_number?: number | null;
  bbox?: [number, number, number, number] | null;
  csv_path?: string | null;
  html_path?: string | null;
  markdown_text?: string | null;
  confidence?: number | null;
  parse_method?: 'odl' | 'pdfplumber' | 'hybrid' | 'vlm_repaired' | null;
  classifier_model?: string | null;
  resolver_version?: string | null;
  extraction_status?: string | null;
  repair_attempted?: boolean;
  repair_reason?: string | null;
  repair_confidence?: number | null;
  review_required?: boolean;
}

export interface EfficiencyMetrics {
  phase_call_counts: Record<string, number>;
  estimated_cached_calls_saved: number;
  estimated_cached_cost_usd_saved: number;
  uncertain_table_repair_calls: number;
  review_required_tables: number;
}

export interface TableListResponse {
  tables: Table[];
  total: number;
  visual_state: VisualState;
  visual_error?: string | null;
  artifacts_ready: boolean;
  artifacts_error?: string | null;
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
export type EvidenceDisplayStatus =
  | 'VERIFIED'
  | 'UNVERIFIED_PAGE_MISMATCH'
  | 'UNVERIFIED_VALUE_MISMATCH'
  | 'UNVERIFIED_INFERRED'
  | 'UNVERIFIED_PARTIAL'
  | 'UNVERIFIED_AMBIGUOUS'
  | 'UNVERIFIED_NOT_FOUND'
  | 'UNVERIFIED_NO_QUOTE'
  | 'UNVERIFIED_NO_TEXT_LAYER'
  | 'UNVERIFIED_STALE_SOURCE'
  | 'UNVERIFIED_ERROR'
  /** 앵커 자체가 없는 경우. 백엔드는 이 값을 저장하지 않고 프론트가 합성한다. */
  | 'UNVERIFIED_NOT_RUN';

/** 결정론적 검증기(evidence-verifier)가 만든 파라미터별 근거 앵커. LLM 출력이 아니다. */
export interface EvidenceAnchor {
  target_index: number;
  target_key: string;
  target_label: string;
  source_tag: string | null;
  /** LLM이 주장한 인용 — 확인되지 않았을 수 있다. */
  claimed_quote: string | null;
  claimed_page: number | null;
  quote_status: string;
  page_status: string;
  value_status: string;
  display_status: EvidenceDisplayStatus;
  match_method: string | null;
  match_ratio: number | null;
  /** 원문에서 실제로 확인된 span. 확인 실패 시 null. */
  matched_quote: string | null;
  matched_page: number | null;
  /** [x0, y_bottom, x1, y_top] PDF 포인트, 좌하단 원점. */
  bbox: [number, number, number, number] | null;
  corpus: string;
  failure_detail: string | null;
  verifier_version: string;
  normalizer_version: string;
}

export interface RecipeEvidence {
  verifier_version: string;
  normalizer_version: string;
  summary: {
    total: number;
    verified: number;
    by_display_status: Record<string, number>;
  };
  anchors: EvidenceAnchor[];
}

export interface Recipe {
  paper_id: number;
  recipe: Record<string, unknown>;
  model_used: string | null;
  created_at: string | null;
  /** null이면 "검증 기록 없음"이지 "검증됨"이 아니다. */
  evidence?: RecipeEvidence | null;
}

// Mermaid diagram types
export interface MermaidDiagram {
  paper_id: number;
  mermaid_code: string;
  diagram_type: string;
  description: string | null;
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
  gemini_key_unreadable: boolean;
  openai_api_key: string;
  openai_key_unreadable: boolean;
  /** 공급사 선택의 단일 소스. image_provider는 백엔드가 갱신하는 미러다. */
  ai_provider?: 'openai' | 'gemini';
  /** 저장된 선택을 키 가용성으로 보정한 실사용 값. 키가 없으면 null. 읽기 전용. */
  active_provider?: 'openai' | 'gemini' | null;
  /** 키가 사라져 자동 전환됐다면 그 대상. 알림용. 읽기 전용. */
  switched_to?: 'openai' | 'gemini' | null;
  image_provider: 'openai' | 'gemini';
  image_quality: 'low' | 'medium' | 'high';
  library_path: string;
  theme: 'dark' | 'light';
  default_domain: string;
  auto_analyze: boolean;
  language: string;
  max_concurrent_analyses: number;
  pdf_parser_mode: 'java';
  extraction_pipeline_version: 'resolver_v1';
  pdf_visual_engine: 'gemini' | 'odl';
  research_context: string;
  default_explanation_level: string;
  research_areas: string[];
  field_expertise: string;
  reading_experience: string;
  research_role: string;
}

export interface ModelStats {
  model: string;
  calls: number;
  cost_usd: number;
  tokens_in: number;
  tokens_out: number;
}

export interface CostSummary {
  monthly_costs: {
    month: string;
    total_usd: number;
    papers_analyzed: number;
    tokens_in: number;
    tokens_out: number;
    by_model: Record<string, number>;
  }[];
  per_paper_costs: {
    paper_id: number;
    title: string;
    total_usd: number;
    tokens_in: number;
    tokens_out: number;
    phases: Record<string, number>;
  }[];
  by_model: ModelStats[];
  current_month: {
    month: string;
    cost_usd: number;
    tokens_in: number;
    tokens_out: number;
    papers_analyzed: number;
  };
  totals: {
    total_papers: number;
    total_cost_usd: number;
    avg_cost_per_paper: number;
    total_tokens_in: number;
    total_tokens_out: number;
  };
  efficiency: EfficiencyMetrics;
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

// In Electron production (file:// protocol), use absolute URL
// In development (http://), use relative URL (Vite proxy handles it)
export function getApiBase(): string {
  const isFileProtocol = typeof window !== 'undefined' && window.location.protocol === 'file:';
  if (!isFileProtocol) {
    return '/api';
  }

  const bundledPort = window.electronAPI?.getBackendPort?.() || BACKEND_PORT;
  return `http://127.0.0.1:${bundledPort}/api`;
}

// For static URL helper
function isFileProtocolCheck(): boolean {
  return typeof window !== 'undefined' && window.location.protocol === 'file:';
}

async function getBackendAuthToken(): Promise<string> {
  return (await window.electronAPI?.getBackendAuthToken?.()) ?? '';
}

export async function getBackendAuthorizationHeaders(): Promise<Record<string, string>> {
  const token = await getBackendAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function appendBackendAssetToken(url: string): string {
  let requestPath: string;
  try {
    requestPath = decodeURIComponent(new URL(url, window.location.origin).pathname);
  } catch {
    return url;
  }
  const token = window.electronAPI?.getBackendAssetToken?.(requestPath);
  if (!token) return url;
  return `${url}${url.includes('?') ? '&' : '?'}sasoo_asset_token=${encodeURIComponent(token)}`;
}

async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${getApiBase()}${endpoint}`;
  const method = (options.method ?? 'GET').toUpperCase();
  const shouldRetryNetworkError = method === 'GET' || method === 'HEAD';
  const retryDelays = isFileProtocolCheck()
    ? ELECTRON_NETWORK_RETRY_DELAYS_MS
    : NETWORK_RETRY_DELAYS_MS;

  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  Object.assign(headers, await getBackendAuthorizationHeaders());

  // Don't set Content-Type for FormData (browser sets boundary automatically)
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  let response: Response;

  for (let attempt = 0; ; attempt += 1) {
    try {
      response = await fetch(url, {
        ...options,
        headers,
      });
      break;
    } catch (error) {
      const retryDelay = retryDelays[attempt];
      if (!shouldRetryNetworkError || retryDelay === undefined) {
        throw error;
      }
      await new Promise((resolve) => setTimeout(resolve, retryDelay));
    }
  }

  if (!response.ok) {
    let errorMessage =
      response.status >= 500
        ? '서버 응답을 기다리는 동안 문제가 생겼어요.'
        : response.status === 404
          ? '요청한 항목을 찾지 못했어요.'
          : '요청을 처리하지 못했어요.';
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

    xhr.open('POST', `${getApiBase()}/papers/upload`);
    void getBackendAuthToken().then((token) => {
      if (token) {
        xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      }
      xhr.send(formData);
    }).catch(reject);
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

// 백엔드 /run은 본문을 받지 않는다(analysis_routes.run_analysis 시그니처에 body 인자가 없다).
// 본문을 실어 보내면 FastAPI가 조용히 버리므로, 보내는 쪽에서 아예 만들지 않는다.
export async function runAnalysis(paperId: string): Promise<AnalysisStatus> {
  return request<AnalysisStatus>(`/analysis/${paperId}/run`, { method: 'POST' });
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

export async function cancelAnalysis(paperId: string): Promise<void> {
  return request<void>(`/analysis/${paperId}/cancel`, {
    method: 'POST',
  });
}

// ---------------------------------------------------------------------------
// Result sub-resource endpoints
// ---------------------------------------------------------------------------

export async function getFigures(paperId: string): Promise<FigureListResponse> {
  return request<FigureListResponse>(`/analysis/${paperId}/figures`);
}

export async function getTables(paperId: string): Promise<TableListResponse> {
  return request<TableListResponse>(`/analysis/${paperId}/tables`);
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


export interface MermaidRepairRequest {
  mermaid_code: string;
  error_message: string;
  viz_id?: number | null;
}

export async function repairMermaid(
  paperId: string | number,
  data: MermaidRepairRequest
): Promise<MermaidDiagram> {
  return request<MermaidDiagram>(`/analysis/${paperId}/mermaid/repair`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function regenerateVisualization(
  paperId: string | number,
  vizId: number
): Promise<VisualizationItem> {
  return request<VisualizationItem>(
    `/analysis/${paperId}/visualizations/${vizId}/regenerate`,
    { method: 'POST' }
  );
}

export async function getVisualizations(
  paperId: string
): Promise<VisualizationPlan> {
  return request<VisualizationPlan>(`/analysis/${paperId}/visualizations`);
}

// ---------------------------------------------------------------------------
// Experiment Planner endpoints
// ---------------------------------------------------------------------------

export interface ExperimentPlan {
  id: number;
  paper_id: number;
  content: Record<string, unknown>;
  model_used: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  created_at?: string;
}

export async function getExperimentPlan(
  paperId: string
): Promise<ExperimentPlan> {
  return request<ExperimentPlan>(`/analysis/${paperId}/experiment-plan`);
}

export async function generateExperimentPlan(
  paperId: string
): Promise<ExperimentPlan> {
  return request<ExperimentPlan>(`/analysis/${paperId}/experiment-plan`, {
    method: 'POST',
  });
}

// ---------------------------------------------------------------------------
// Agent Chat (SSE streaming)
// ---------------------------------------------------------------------------

/** Lifecycle of a single chat turn, tracked per message so several can coexist. */
export type ChatMessageStatus = 'pending' | 'streaming' | 'done' | 'error';

export interface ChatMessage {
  id: string;
  role: 'user' | 'agent';
  content: string;
  status: ChatMessageStatus;
  error?: string;
}

export interface ChatDoneMeta {
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
}

/** Raised when the backend reports a failure through the SSE `error` event. */
export class ChatStreamError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ChatStreamError';
  }
}

/**
 * `history` must NOT contain `message` — the backend appends it as the final
 * user turn, so including it here would send the question to Gemini twice.
 */
export async function chatWithAgent(
  paperId: string,
  message: string,
  history: ChatMessage[],
  onToken: (text: string) => void,
  onDone: (meta: ChatDoneMeta) => void,
  signal?: AbortSignal,
): Promise<void> {
  const url = `${getApiBase()}/analysis/${paperId}/chat`;

  const authHeaders = await getBackendAuthorizationHeaders();
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders,
    },
    signal,
    body: JSON.stringify({
      message,
      history: history.map((m) => ({
        role: m.role === 'agent' ? 'model' : 'user',
        content: m.content,
      })),
    }),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Chat failed' }));
    throw new ApiError(response.status, err.detail || 'Chat failed');
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error('No response body');

  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;

        let data: {
          type?: string;
          content?: string;
          message?: string;
          tokens_in?: number;
          tokens_out?: number;
          cost_usd?: number;
        };
        try {
          data = JSON.parse(line.slice(6));
        } catch {
          throw new ChatStreamError('응답 스트림을 해석하지 못했습니다.');
        }

        if (data.type === 'token') {
          onToken(data.content ?? '');
        } else if (data.type === 'done') {
          onDone({
            tokens_in: data.tokens_in ?? 0,
            tokens_out: data.tokens_out ?? 0,
            cost_usd: data.cost_usd ?? 0,
          });
          return;
        } else if (data.type === 'error') {
          throw new ChatStreamError(data.message || 'Chat failed');
        }
      }
    }
  } finally {
    // Frees the connection when we return on `done`, throw, or the caller aborts.
    void reader.cancel().catch(() => {});
  }
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
  return appendBackendAssetToken(`${getApiBase()}/papers/${paperId}/pdf`);
}

// ---------------------------------------------------------------------------
// Static file URL helper
// ---------------------------------------------------------------------------

/**
 * Transform a relative static URL (e.g., /static/library/...) to an absolute URL
 * when running in Electron production mode (file:// protocol).
 */
export function getStaticUrl(relativeUrl: string | null | undefined): string {
  if (!relativeUrl) return '';
  // In Electron production (file:// protocol), use absolute backend URL
  if (isFileProtocolCheck() && relativeUrl.startsWith('/static/')) {
    const bundledPort = window.electronAPI?.getBackendPort?.() || BACKEND_PORT;
    return appendBackendAssetToken(`http://127.0.0.1:${bundledPort}${relativeUrl}`);
  }
  return relativeUrl.startsWith('/static/') ? appendBackendAssetToken(relativeUrl) : relativeUrl;
}

export function getLibraryAssetUrl(assetPath: string | null | undefined): string {
  if (!assetPath) return '';

  const normalized = assetPath.replace(/\\/g, '/');
  const libraryIdx = normalized.indexOf('/library/');
  if (libraryIdx >= 0) {
    const relative = normalized.substring(libraryIdx + '/library/'.length);
    return getStaticUrl(`/static/library/${encodeURI(relative)}`);
  }

  return getStaticUrl(assetPath);
}
