"""
Sasoo - Pydantic Schemas
All request/response models for the API layer.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any, Optional

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
    VISUAL = "visual"
    RECIPE = "recipe"
    DEEP_DIVE = "deep_dive"


class DomainType(str, Enum):
    OPTICS = "optics"
    MATERIALS = "materials"
    BIO = "bio"
    ENERGY = "energy"
    QUANTUM = "quantum"
    GENERAL = "general"


class AgentType(str, Enum):
    PHOTON = "photon"       # optics domain
    CRYSTAL = "crystal"     # materials domain
    HELIX = "helix"         # bio domain
    VOLT = "volt"           # energy domain
    QUBIT = "qubit"         # quantum domain
    ATLAS = "atlas"         # general-purpose


class FigureQuality(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNREADABLE = "unreadable"


# ---------------------------------------------------------------------------
# Paper Models
# ---------------------------------------------------------------------------

class PaperCreate(BaseModel):
    """Returned after successful PDF upload and initial metadata extraction."""
    title: str
    authors: Optional[str] = None
    year: Optional[int] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    domain: DomainType = DomainType.OPTICS
    agent_used: AgentType = AgentType.PHOTON
    tags: Optional[str] = None
    notes: Optional[str] = None


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


class PaperListResponse(BaseModel):
    """Paginated list of papers."""
    papers: list[PaperResponse]
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


class FigureListResponse(BaseModel):
    """List of figures for a paper."""
    figures: list[FigureInfo]
    total: int


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

class ScreeningResult(BaseModel):
    """Phase 1: Screening result."""
    paper_id: int
    domain: DomainType
    agent_recommended: AgentType
    relevance_score: float = Field(ge=0.0, le=1.0)
    key_topics: list[str] = Field(default_factory=list)
    methodology_type: Optional[str] = None
    summary: str
    is_experimental: bool = True
    has_figures: bool = True
    estimated_complexity: Optional[str] = None  # low, medium, high


class VisualResult(BaseModel):
    """Phase 2: Visual verification result."""
    paper_id: int
    figures: list[FigureInfo] = Field(default_factory=list)
    figure_count: int = 0
    tables_found: int = 0
    equations_found: int = 0
    diagram_types: list[str] = Field(default_factory=list)  # SEM, TEM, spectrum, graph, etc.
    quality_summary: str = ""
    key_findings_from_visuals: list[str] = Field(default_factory=list)


class RecipeResult(BaseModel):
    """Phase 3: Recipe extraction result."""
    paper_id: int
    recipe: RecipeCard
    confidence: float = Field(ge=0.0, le=1.0)
    missing_info: list[str] = Field(default_factory=list)
    reproducibility_score: float = Field(ge=0.0, le=1.0)


class DeepDiveResult(BaseModel):
    """Phase 4: Deep dive analysis result."""
    paper_id: int
    detailed_analysis: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    novelty_assessment: str = ""
    comparison_to_prior_work: Optional[str] = None
    suggested_improvements: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    practical_applications: list[str] = Field(default_factory=list)


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


class AnalysisResult(BaseModel):
    """Single stored analysis result row."""
    id: int
    paper_id: int
    phase: str
    result: str  # JSON string
    model_used: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    cost_usd: Optional[float] = None
    created_at: Optional[str] = None

    def parsed_result(self) -> dict:
        """Parse the JSON result string."""
        try:
            return json.loads(self.result)
        except (json.JSONDecodeError, TypeError):
            return {"raw": self.result}


class FullAnalysisResponse(BaseModel):
    """Complete analysis results across all phases."""
    paper_id: int
    status: AnalysisStatus
    screening: Optional[dict] = None
    visual: Optional[dict] = None
    recipe: Optional[dict] = None
    deep_dive: Optional[dict] = None


# ---------------------------------------------------------------------------
# VizRouter / Mermaid
# ---------------------------------------------------------------------------

class VizRouterResult(BaseModel):
    """Result from the visualization router."""
    paper_id: int
    recommended_viz: list[str] = Field(default_factory=list)
    mermaid_code: Optional[str] = None
    chart_configs: list[dict] = Field(default_factory=list)


class MermaidResult(BaseModel):
    """Mermaid diagram generated for a paper's process flow."""
    paper_id: int
    mermaid_code: str
    diagram_type: str = "flowchart"  # flowchart | sequence | state | class
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# Domain Classification
# ---------------------------------------------------------------------------

class DomainResult(BaseModel):
    """Domain classification output."""
    domain: DomainType
    confidence: float = Field(ge=0.0, le=1.0)
    agent: AgentType
    reasoning: str = ""
    keywords_matched: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class SettingsModel(BaseModel):
    """Application settings."""
    gemini_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    library_path: str = "./library"
    default_domain: DomainType = DomainType.OPTICS
    auto_analyze: bool = True
    language: str = "ko"           # ko | en
    theme: str = "light"           # light | dark
    max_concurrent_analyses: int = 3
    gemini_model: str = "gemini-3-flash-preview"
    anthropic_model: str = "claude-sonnet-4-20250514"

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
    anthropic_api_key: Optional[str] = None
    library_path: Optional[str] = None
    default_domain: Optional[DomainType] = None
    auto_analyze: Optional[bool] = None
    language: Optional[str] = None
    theme: Optional[str] = None
    max_concurrent_analyses: Optional[int] = None
    gemini_model: Optional[str] = None
    anthropic_model: Optional[str] = None


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


