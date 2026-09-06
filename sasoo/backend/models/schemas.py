"""
Sasoo - Pydantic Schemas
All request/response models for the API layer.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator



# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PaperStatus(str, Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    ERROR = "error"


class AnalysisPhase(str, Enum):
    SCREENING = "screening"
    CITATION = "citation"
    VISUAL = "visual"
    RECIPE = "recipe"
    DEEP_DIVE = "deep_dive"


class DomainType(str, Enum):
    # 에이전트 .md 레지스트리(backend/agents/*.md)의 domain 값과 1:1로 맞춘다.
    OPTICS = "optics"
    BIO = "bio"
    AI_ML = "ai_ml"
    EE = "ee"
    GENERAL = "general"


class AgentType(str, Enum):
    PHOTON = "photon"       # optics domain
    CELL = "cell"           # bio domain
    NEURAL = "neural"       # ai_ml domain
    CIRCUIT = "circuit"     # ee domain


class VisualState(str, Enum):
    READY = "ready"
    RUNNING = "running"
    ERROR = "error"
    PARTIAL = "partial"


# ---------------------------------------------------------------------------
# Paper Models
# ---------------------------------------------------------------------------

class PaperUpdate(BaseModel):
    """Fields that can be patched on an existing paper."""
    title: Optional[str] = None
    authors: Optional[str] = None
    year: Optional[int] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    domain: Optional[DomainType] = None
    agent_used: Optional[AgentType] = None
    tags: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[PaperStatus] = None
    explanation_level: Optional[str] = None
    analysis_focus: Optional[dict] = None


class PaperResponse(BaseModel):
    """Full paper record returned from the API."""
    id: int
    title: str
    authors: Optional[str] = None
    year: Optional[int] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    domain: str = "optics"
    agent_used: str = "photon"
    folder_name: str
    tags: Optional[str] = None
    status: str = "pending"
    analyzed_at: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None
    text_ready: bool = False
    visual_ready: bool = False
    visual_state: VisualState = VisualState.PARTIAL
    visual_error: Optional[str] = None
    artifacts_ready: bool = False
    explanation_level: Optional[str] = None
    analysis_focus: Optional[str] = None
    pdf_file_uri: Optional[str] = None
    pdf_file_expires_at: Optional[str] = None


class PaperListResponse(BaseModel):
    """Paginated list of papers."""
    papers: list[PaperResponse]
    completed_count: Optional[int] = None
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Figure Models
# ---------------------------------------------------------------------------

class FigureInfo(BaseModel):
    """Metadata for an extracted figure."""
    id: Optional[int] = None
    paper_id: int
    figure_num: Optional[str] = None
    caption: Optional[str] = None
    file_path: Optional[str] = None
    ai_analysis: Optional[str] = None
    quality: Optional[str] = None
    detailed_explanation: Optional[str] = None
    page_number: Optional[int] = None
    bbox: Optional[tuple[float, float, float, float]] = None
    extraction_engine: Optional[str] = None
    confidence: Optional[float] = None
    classifier_label: Optional[str] = None
    classifier_model: Optional[str] = None
    parent_figure_id: Optional[int] = None
    is_composite: Optional[bool] = None
    resolver_version: Optional[str] = None
    extraction_status: Optional[str] = None


class FigureListResponse(BaseModel):
    """List of figures for a paper."""
    figures: list[FigureInfo]
    total: int
    visual_state: VisualState = VisualState.PARTIAL
    visual_error: Optional[str] = None
    artifacts_ready: bool = False
    artifacts_error: Optional[str] = None


class TableInfo(BaseModel):
    """Metadata for an extracted table."""
    id: Optional[int] = None
    paper_id: int
    table_num: Optional[str] = None
    caption: Optional[str] = None
    page_number: Optional[int] = None
    bbox: Optional[tuple[float, float, float, float]] = None
    csv_path: Optional[str] = None
    html_path: Optional[str] = None
    markdown_text: Optional[str] = None
    confidence: Optional[float] = None
    parse_method: Optional[str] = None
    classifier_model: Optional[str] = None
    resolver_version: Optional[str] = None
    extraction_status: Optional[str] = None
    repair_attempted: bool = False
    repair_reason: Optional[str] = None
    repair_confidence: Optional[float] = None
    review_required: bool = False


class TableListResponse(BaseModel):
    """List of extracted tables for a paper."""
    tables: list[TableInfo]
    total: int
    visual_state: VisualState = VisualState.PARTIAL
    visual_error: Optional[str] = None
    artifacts_ready: bool = False
    artifacts_error: Optional[str] = None


class FigureExplanationResponse(BaseModel):
    """Detailed expert explanation of a figure."""
    figure_id: int
    paper_id: int
    figure_num: Optional[str] = None
    caption: Optional[str] = None
    explanation: str  # Markdown formatted detailed explanation
    model_used: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


# ---------------------------------------------------------------------------
# Recipe Models
# ---------------------------------------------------------------------------

class RecipeParameter(BaseModel):
    """A single parameter in a recipe card."""
    name: str
    value: str
    unit: Optional[str] = None
    notes: Optional[str] = None


class RecipeCard(BaseModel):
    """Structured recipe card extracted from a paper."""
    paper_id: int
    title: str
    objective: str
    materials: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    parameters: list[RecipeParameter] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    critical_notes: list[str] = Field(default_factory=list)
    expected_results: Optional[str] = None
    safety_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Analysis Phase Result Models
# ---------------------------------------------------------------------------

class CitationContext(BaseModel):
    """A single citation context occurrence."""
    sentence: str = ""
    section: str = ""


class CitedReference(BaseModel):
    """A single reference with citation analysis."""
    ref_id: str = ""
    authors: str = ""
    title: str = ""
    journal: str = ""
    year: Optional[int] = None
    cite_count: int = 0
    cite_contexts: list[CitationContext] = Field(default_factory=list)
    citation_role: str = ""  # foundational, methodological, comparative, supporting, contrasting
    why_cited: str = ""


# ---------------------------------------------------------------------------
# Analysis Status / Aggregated Results
# ---------------------------------------------------------------------------

class PhaseStatus(BaseModel):
    """Status of a single analysis phase."""
    phase: AnalysisPhase
    status: str = "pending"   # pending | running | completed | error
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    model_used: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    cost_usd: Optional[float] = None
    error_message: Optional[str] = None
    # Task 11(스펙 §D 2단계 조회): 이 phase의 최신 결과가 현재 (provider, model,
    # effort) 설정과 다른 구성으로 만들어졌으면 그 모델명. 같은 구성이거나 결과가
    # 없으면 None. 하위호환 옵셔널 필드 — 기존 클라이언트는 무시해도 된다.
    stale_model: Optional[str] = None


class AnalysisStatus(BaseModel):
    """Aggregate status of all 4 analysis phases."""
    paper_id: int
    overall_status: str = "pending"  # pending | running | completed | error
    phases: list[PhaseStatus] = Field(default_factory=list)
    progress_pct: float = 0.0  # 0..100
    current_phase: Optional[AnalysisPhase] = None
    total_cost_usd: float = 0.0
    total_tokens_in: int = 0
    total_tokens_out: int = 0


class FullAnalysisResponse(BaseModel):
    """Complete analysis results across all phases."""
    paper_id: int
    status: AnalysisStatus
    screening: Optional[dict] = None
    citation: Optional[dict] = None
    visual: Optional[dict] = None
    recipe: Optional[dict] = None
    deep_dive: Optional[dict] = None


# ---------------------------------------------------------------------------
# Mermaid
# ---------------------------------------------------------------------------

class MermaidResult(BaseModel):
    """Mermaid diagram generated for a paper's process flow."""
    paper_id: int
    mermaid_code: str
    diagram_type: str = "flowchart"  # flowchart | sequence | state | class
    description: Optional[str] = None


class MermaidRepairRequest(BaseModel):
    """Client-reported parse failure asking the LLM to fix the diagram code."""
    mermaid_code: str
    error_message: str
    viz_id: Optional[int] = None  # visualization item ordinal to persist into; None = don't persist


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class SettingsModel(BaseModel):
    """Application settings."""
    gemini_api_key: Optional[str] = None
    # True when a key IS stored but no available encryption key opens it.
    # Without this the UI shows a bare "not configured" and the user has no
    # way to tell that re-entering the key is what fixes it.
    gemini_key_unreadable: bool = False
    openai_api_key: Optional[str] = None
    openai_key_unreadable: bool = False
    # ai_provider가 공급사 선택의 단일 소스다. image_provider는 이 값을 따라
    # 함께 갱신되는 미러이며, 읽기 권위는 ai_provider에 있다.
    ai_provider: Literal["openai", "gemini"] = "openai"
    # 저장된 선택을 API 키 가용성으로 보정한 값. 키가 하나도 없으면 None이다.
    # 서버가 계산해 내려주며 클라이언트는 읽기만 한다.
    active_provider: Optional[Literal["openai", "gemini"]] = None
    # 키가 사라져 다른 공급사로 자동 전환됐다면 그 대상. 알림용이다.
    switched_to: Optional[Literal["openai", "gemini"]] = None
    image_provider: Literal["openai", "gemini"] = "openai"
    image_quality: Literal["low", "medium", "high"] = "high"
    library_path: str = "./library"
    default_domain: DomainType = DomainType.OPTICS
    auto_analyze: bool = True
    language: str = "ko"           # ko | en
    theme: str = "light"           # light | dark
    max_concurrent_analyses: int = 3
    pdf_parser_mode: str = "java"
    extraction_pipeline_version: str = "resolver_v1"
    # Figure 추출(visual) 단계 엔진: gemini(고품질·유료) | odl(무료). text 단계는
    # UI에 노출하지 않고 env(SASOO_PDF_TEXT_ENGINE)로만 조정한다.
    pdf_visual_engine: str = "gemini"
    research_context: str = ""
    default_explanation_level: str = "masters"
    research_areas: list[str] = Field(default_factory=list)
    field_expertise: str = "major"
    reading_experience: str = "regular"
    research_role: str = "grad_student"

    @field_validator("library_path", mode="before")
    @classmethod
    def expand_home(cls, v: str) -> str:
        from pathlib import Path as _P
        if isinstance(v, str) and v.startswith("~"):
            return str(_P(v).expanduser())
        return v


class SettingsUpdate(BaseModel):
    """Partial settings update."""
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    ai_provider: Optional[Literal["openai", "gemini"]] = None
    image_provider: Optional[Literal["openai", "gemini"]] = None
    image_quality: Optional[Literal["low", "medium", "high"]] = None
    library_path: Optional[str] = None
    default_domain: Optional[DomainType] = None
    auto_analyze: Optional[bool] = None
    language: Optional[str] = None
    theme: Optional[str] = None
    max_concurrent_analyses: Optional[int] = None
    pdf_parser_mode: Optional[str] = None
    extraction_pipeline_version: Optional[str] = None
    pdf_visual_engine: Optional[str] = None
    research_context: Optional[str] = None
    default_explanation_level: Optional[str] = None
    research_areas: Optional[list[str]] = None
    field_expertise: Optional[str] = None
    reading_experience: Optional[str] = None
    research_role: Optional[str] = None


# ---------------------------------------------------------------------------
# Cost Tracking
# ---------------------------------------------------------------------------

class CostEntry(BaseModel):
    """Single cost entry."""
    date: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float


class CostSummary(BaseModel):
    """Monthly API cost summary."""
    month: str  # YYYY-MM
    total_cost_usd: float
    total_tokens_in: int
    total_tokens_out: int
    by_model: dict[str, float] = Field(default_factory=dict)
    by_phase: dict[str, float] = Field(default_factory=dict)
    entries: list[CostEntry] = Field(default_factory=list)
    daily_breakdown: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

class ReportResponse(BaseModel):
    """Integrated markdown report."""
    paper_id: int
    title: str
    markdown: str
    generated_at: str


# ---------------------------------------------------------------------------
# PaperBanana
# ---------------------------------------------------------------------------

class PaperBananaRequest(BaseModel):
    """Request to generate a PaperBanana visual summary."""
    style: str = "default"         # default | minimal | detailed
    language: str = "ko"           # ko | en
    include_recipe: bool = True
    include_figures: bool = True


class PaperBananaResponse(BaseModel):
    """PaperBanana generation result."""
    paper_id: int
    image_path: str
    image_url: str
    width: int = 0
    height: int = 0


# ---------------------------------------------------------------------------
# Visualization Plan (Gemini Pro 3 → up to 5 diagrams/figures)
# ---------------------------------------------------------------------------

class VisualizationItem(BaseModel):
    """A single visualization item planned by Gemini Pro 3."""
    id: int = 0                             # ordinal index (1-5)
    title: str                              # short descriptive title
    tool: str = "mermaid"                   # "mermaid" or "paperbanana"
    diagram_type: str = "flowchart"         # flowchart, sequence, mindmap, methodology, etc.
    description: str = ""                   # why this viz helps understand the method
    category: str = ""                      # from DiagramCategory taxonomy
    # Mermaid-specific
    mermaid_code: Optional[str] = None
    # PaperBanana-specific
    image_url: Optional[str] = None
    image_path: Optional[str] = None
    # Status
    status: str = "pending"                 # pending | generating | completed | error
    error_message: Optional[str] = None


class VisualizationPlanResponse(BaseModel):
    """Complete visualization plan: up to 5 items, each Mermaid or PaperBanana."""
    paper_id: int
    items: list[VisualizationItem] = Field(default_factory=list)
    total_count: int = 0
    model_used: str = ""
    planned_at: Optional[str] = None
