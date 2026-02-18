"""
Sasoo - Analysis API Router
Endpoints for running, monitoring, and retrieving the 4-phase analysis pipeline.

Phases:
  1. Screening       - Domain classification, relevance scoring, topic extraction
  2. Visual          - Figure extraction, quality assessment, diagram identification
  3. Recipe          - Experimental procedure extraction into structured recipe card
  4. Deep Dive       - Comprehensive analysis, strengths/weaknesses, novelty assessment
"""

import asyncio
import json
import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

logger = logging.getLogger(__name__)

from models.database import (
    execute_insert,
    execute_update,
    fetch_all,
    fetch_one,
    get_db,
    get_figures_dir,
    get_paper_dir,
    get_paperbanana_dir,
)
from models.schemas import (
    AnalysisPhase,
    AnalysisResult,
    AnalysisStatus,
    DomainResult,
    FigureExplanationResponse,
    FigureInfo,
    FigureListResponse,
    FullAnalysisResponse,
    MermaidResult,
    PaperBananaRequest,
    PaperBananaResponse,
    PhaseStatus,
    RecipeCard,
    ReportResponse,
    VisualizationItem,
    VisualizationPlanResponse,
)
from services.pricing import calc_cost
from services.pdf_cache import get_pdf_text

from api.analysis_state import _running_analyses, _cancel_events, _analyses_lock
from api.analysis_helpers import (
    _call_gemini,
    _call_anthropic,
    _clean_llm_json,
    _is_error_result,
)
from api.report_service import (
    _format_phase_data,
    _generate_paperbanana_image,
    _wrap_text,
)
from api.figure_service import explain_figure_handler

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

# ---------------------------------------------------------------------------
# Phase execution functions
# ---------------------------------------------------------------------------

async def _run_screening(paper_id: int, text: str, status: AnalysisStatus) -> dict:
    """Phase 1: Screening - classify domain, score relevance, extract topics."""
    phase_status = PhaseStatus(
        phase=AnalysisPhase.SCREENING,
        status="running",
        started_at=datetime.utcnow().isoformat(),
    )
    status.phases.append(phase_status)
    status.current_phase = AnalysisPhase.SCREENING

    prompt = f"""너는 Sasoo(사수)라는 AI Co-Scientist야. 이 연구 논문을 분석해서 스크리닝 평가를 해줘.

모든 텍스트 내용(summary, key_topics 등)은 반드시 한국어로 작성해.
JSON key 이름만 영어로 유지하고, value는 전부 한국어로 써줘.

Return ONLY valid JSON (마크다운 펜스 없이):
{{
  "domain": "optics|materials|bio|energy|quantum|general",
  "agent_recommended": "photon|crystal|helix|volt|qubit|atlas",
  "relevance_score": 0.0-1.0,
  "key_topics": ["주제1", "주제2", ...],
  "methodology_type": "experimental|computational|theoretical|review",
  "summary": "2-3문장 요약 (한국어)",
  "is_experimental": true/false,
  "has_figures": true/false,
  "estimated_complexity": "low|medium|high"
}}

논문 텍스트:
{text[:8000]}
"""

    result = await _call_gemini(prompt)
    # Clean markdown fences from JSON response
    cleaned_text = _clean_llm_json(result["text"])

    # Validate JSON before storing
    try:
        json.loads(cleaned_text)
        result["text"] = cleaned_text
    except json.JSONDecodeError as exc:
        logger.warning("Phase 1 JSON validation failed: %s", exc)
        result["text"] = json.dumps({"_raw": cleaned_text, "_parse_error": str(exc)})

    cost = calc_cost(result["model"], result["tokens_in"], result["tokens_out"])

    # Store in DB
    await execute_insert(
        """INSERT INTO analysis_results (paper_id, phase, result, model_used, tokens_in, tokens_out, cost_usd)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (paper_id, "screening", result["text"], result["model"],
         result["tokens_in"], result["tokens_out"], cost),
    )

    # Update status
    phase_status.status = "completed"
    phase_status.completed_at = datetime.utcnow().isoformat()
    phase_status.model_used = result["model"]
    phase_status.tokens_in = result["tokens_in"]
    phase_status.tokens_out = result["tokens_out"]
    phase_status.cost_usd = cost
    status.progress_pct = max(status.progress_pct, 20.0)
    status.total_cost_usd += cost
    status.total_tokens_in += result["tokens_in"]
    status.total_tokens_out += result["tokens_out"]

    return result


async def _run_visual(paper_id: int, text: str, folder_name: str, status: AnalysisStatus) -> dict:
    """Phase 2: Visual verification - analyze figures, assess quality."""
    phase_status = PhaseStatus(
        phase=AnalysisPhase.VISUAL,
        status="running",
        started_at=datetime.utcnow().isoformat(),
    )
    status.phases.append(phase_status)
    status.current_phase = AnalysisPhase.VISUAL

    # Get existing figures from DB
    figures = await fetch_all(
        "SELECT * FROM figures WHERE paper_id = ?", (paper_id,)
    )

    figure_desc = ""
    if figures:
        figure_desc = f"\n\nExtracted {len(figures)} figures from the paper."
        for fig in figures:
            figure_desc += f"\n- {fig['figure_num']}: quality={fig['quality']}"

    prompt = f"""너는 Sasoo(사수)라는 AI Co-Scientist야. 이 연구 논문의 시각적 요소를 분석해줘.

모든 텍스트 내용(quality_summary, key_findings_from_visuals 등)은 반드시 한국어로 작성해.
JSON key 이름만 영어로 유지하고, value는 전부 한국어로 써줘.

Return ONLY valid JSON (마크다운 펜스 없이):
{{
  "figure_count": <int>,
  "tables_found": <int>,
  "equations_found": <int>,
  "diagram_types": ["SEM", "TEM", "spectrum", "graph", "photograph", "schematic", ...],
  "quality_summary": "그림 품질에 대한 전체 평가 (한국어)",
  "key_findings_from_visuals": ["시각자료에서 발견한 핵심 사항1", "핵심 사항2", ...]
}}

논문 텍스트:
{text[:6000]}
{figure_desc}
"""

    result = await _call_gemini(prompt)
    cleaned_text = _clean_llm_json(result["text"])

    # Validate JSON before storing
    try:
        json.loads(cleaned_text)
        result["text"] = cleaned_text
    except json.JSONDecodeError as exc:
        logger.warning("Phase 2 JSON validation failed: %s", exc)
        result["text"] = json.dumps({"_raw": cleaned_text, "_parse_error": str(exc)})

    cost = calc_cost(result["model"], result["tokens_in"], result["tokens_out"])

    await execute_insert(
        """INSERT INTO analysis_results (paper_id, phase, result, model_used, tokens_in, tokens_out, cost_usd)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (paper_id, "visual", result["text"], result["model"],
         result["tokens_in"], result["tokens_out"], cost),
    )

    phase_status.status = "completed"
    phase_status.completed_at = datetime.utcnow().isoformat()
    phase_status.model_used = result["model"]
    phase_status.tokens_in = result["tokens_in"]
    phase_status.tokens_out = result["tokens_out"]
    phase_status.cost_usd = cost
    status.progress_pct = max(status.progress_pct, 40.0)
    status.total_cost_usd += cost
    status.total_tokens_in += result["tokens_in"]
    status.total_tokens_out += result["tokens_out"]

    return result


async def _run_recipe(paper_id: int, text: str, status: AnalysisStatus) -> dict:
    """Phase 3: Recipe extraction - extract structured experimental procedure."""
    phase_status = PhaseStatus(
        phase=AnalysisPhase.RECIPE,
        status="running",
        started_at=datetime.utcnow().isoformat(),
    )
    status.phases.append(phase_status)
    status.current_phase = AnalysisPhase.RECIPE

    # --------------- Smart text extraction ---------------
    # The Methods/Experimental section is usually in the middle-to-end of the paper.
    # Send a smarter excerpt: first 3K (intro/abstract) + last 15K (methods, results, refs)
    text_lower = text.lower()
    # Try to find the start of the Methods/Experimental section
    methods_markers = [
        "methods", "methodology", "experimental", "materials and methods",
        "experimental setup", "experimental procedure", "experimental details",
        "fabrication", "sample preparation", "measurement",
        "simulation setup", "simulation method", "computational method",
        "numerical method", "synthesis", "characterization",
        "실험", "방법", "실험 방법", "실험 절차", "재료 및 방법",
        "시뮬레이션", "합성", "측정",
    ]
    methods_start = -1
    for marker in methods_markers:
        idx = text_lower.find(marker)
        if idx > 0 and (methods_start < 0 or idx < methods_start):
            methods_start = idx

    if methods_start > 0:
        # Include some context before + full methods section onward
        context_start = max(0, methods_start - 500)
        paper_excerpt = text[:3000] + "\n\n...(중략)...\n\n" + text[context_start:context_start + 18000]
    else:
        # Fallback: send more text than before (20K instead of 10K)
        paper_excerpt = text[:20000]

    # --------------- Domain-specific parameter hints ---------------
    # Look up the screening result to get domain info
    screening_row = await fetch_one(
        "SELECT result FROM analysis_results WHERE paper_id = ? AND phase = 'screening' ORDER BY created_at DESC LIMIT 1",
        (paper_id,),
    )
    domain_hint = ""
    if screening_row:
        try:
            screening_data = json.loads(_clean_llm_json(screening_row["result"]))
            domain = screening_data.get("domain", "")
            if domain in ("optics", "photonics"):
                domain_hint = """
DOMAIN-SPECIFIC PARAMETERS (Optics/Photonics) — extract ALL of these if mentioned:
wavelength (nm), laser_power (W/mW), pulse_duration (fs/ps/ns), repetition_rate (Hz/MHz),
beam_diameter (mm/um), numerical_aperture (NA), focal_length (mm), magnification,
cavity_finesse, cavity_Q_factor, fiber_type (SMF/MMF), coupling_efficiency (%),
beam_quality_M2, polarization, modulation_frequency, detection_method,
signal_to_noise_ratio (dB), dark_count_rate, BER (bit error rate),
turbulence_strength (Cn2), propagation_distance (m/km), aperture_diameter,
pixel_pitch, resolution, phase_mask_levels, diffraction_efficiency"""
            elif domain in ("bio", "biology"):
                domain_hint = """
DOMAIN-SPECIFIC PARAMETERS (Biology/Biomedical) — extract ALL of these if mentioned:
cell_type, passage_number, seeding_density (cells/cm2), culture_medium,
incubation_temperature (C), incubation_duration (h/days), CO2_concentration (%),
assay_type, antibody_primary, antibody_secondary, staining_protocol,
detection_method, sample_size_n, cell_viability (%), drug_concentration,
exposure_time, imaging_modality, magnification, resolution"""
            elif domain in ("ai_ml", "neural", "computer_science"):
                domain_hint = """
DOMAIN-SPECIFIC PARAMETERS (AI/ML) — extract ALL of these if mentioned:
architecture, num_layers, hidden_units, activation_function, optimizer,
learning_rate, batch_size, epochs, training_time, regularization,
dropout_rate, weight_initialization, training_data_size, test_data_split,
loss_function, evaluation_metric, GPU_type, precision (fp16/fp32),
augmentation_method, pretrained_model, fine_tuning_strategy"""
            elif domain in ("materials", "crystal"):
                domain_hint = """
DOMAIN-SPECIFIC PARAMETERS (Materials Science) — extract ALL of these if mentioned:
substrate_type, substrate_temperature (C/K), deposition_rate (nm/s, A/s), chamber_pressure (Pa/Torr),
film_thickness (nm/um), annealing_temperature (C/K), annealing_duration (min/h), annealing_atmosphere,
precursor_materials, target_composition, sputtering_power (W), RF_frequency (MHz),
grain_size (nm/um), crystal_structure, lattice_parameter (A/nm), surface_roughness (nm),
hardness (GPa), Young_modulus (GPa), thermal_conductivity (W/mK), electrical_resistivity (ohm*cm),
XRD_peaks (2theta), FWHM, crystallinity (%), porosity (%)"""
            elif domain in ("energy", "volt"):
                domain_hint = """
DOMAIN-SPECIFIC PARAMETERS (Energy) — extract ALL of these if mentioned:
cell_efficiency (%), open_circuit_voltage (V), short_circuit_current (mA/cm2),
fill_factor, bandgap (eV), absorber_thickness (nm/um), electrode_material,
electrolyte_composition, charge_capacity (mAh/g), discharge_rate (C),
cycle_number, capacity_retention (%), coulombic_efficiency (%),
power_density (W/kg), energy_density (Wh/kg), internal_resistance (ohm),
operating_temperature (C), illumination_intensity (mW/cm2, sun),
active_area (cm2), HTL_material, ETL_material, perovskite_composition"""
            elif domain in ("quantum", "qubit"):
                domain_hint = """
DOMAIN-SPECIFIC PARAMETERS (Quantum) — extract ALL of these if mentioned:
qubit_type, coherence_time_T1 (us/ms), coherence_time_T2 (us/ms), gate_fidelity (%),
readout_fidelity (%), operating_temperature (mK/K), coupling_strength (MHz/GHz),
resonator_frequency (GHz), anharmonicity (MHz), quantum_volume,
error_rate, circuit_depth, number_of_qubits, connectivity,
magnetic_field (T/mT), microwave_frequency (GHz), microwave_power (dBm),
Rabi_frequency (MHz), detuning (MHz), photon_number, squeezing_parameter (dB)"""
            else:
                domain_hint = """
Look for ALL quantitative parameters: temperatures, pressures, durations, concentrations,
voltages, currents, frequencies, distances, speeds, sizes, ratios, percentages, etc."""
        except (json.JSONDecodeError, TypeError):
            pass

    prompt = f"""너는 Sasoo(사수)라는 AI Co-Scientist야. 이 연구 논문에서 실험 레시피를 완전하고 철저하게 추출해줘.

모든 텍스트 내용은 반드시 한국어로 작성해. JSON key 이름만 영어로 유지해.

핵심 지시사항:
1. 논문에 언급된 모든 정량적 파라미터를 추출해. Results나 Discussion에 있는 것도 포함.
2. 각 파라미터마다 name, value, unit, notes(출처/컨텍스트)를 반드시 포함.
3. 값이 불명확해도 notes="추정값" 또는 notes="근사값"으로 포함시켜.
4. 사소해 보이는 파라미터도 절대 건너뛰지 마 — 재현성을 위해 모든 세부사항 필요.
5. Methods 섹션뿐 아니라 논문 전체에서 파라미터를 찾아.
{domain_hint}

Return ONLY valid JSON (마크다운 펜스 없이, 설명 없이):
{{
  "title": "레시피 제목 (뭘 하는 실험인지, 한국어)",
  "objective": "이 실험의 목적 (한국어)",
  "materials": ["재료1 (규격 포함)", "재료2 (제조사, 순도, 등급)", ...],
  "equipment": ["장비1 (모델번호 포함)", "장비2", ...],
  "parameters": [
    {{"name": "파라미터 이름", "value": "수치 값", "unit": "단위", "notes": "출처/컨텍스트 (한국어)"}},
    {{"name": "다른 파라미터", "value": "값", "unit": "단위", "notes": ""}},
    ...
  ],
  "steps": [
    "단계 1: 구체적인 설정 포함한 상세 설명 (한국어)...",
    "단계 2: 온도, 시간, 속도 등 포함 (한국어)...",
    ...
  ],
  "critical_notes": ["재현을 위한 중요 참고사항 (한국어)", ...],
  "expected_results": "예상되는 결과 (한국어)",
  "safety_notes": "안전 주의사항 (한국어)",
  "confidence": 0.0-1.0,
  "missing_info": ["논문에서 찾지 못한 파라미터나 세부사항 (한국어)"],
  "reproducibility_score": 0.0-1.0
}}

중요: "parameters" 배열에 최소 8-15개 항목이 있어야 해.
5개 미만이면 텍스트를 다시 꼼꼼히 읽어 — 분명 놓친 게 있을 거야.

논문 텍스트:
{paper_excerpt}
"""

    try:
        result = await _call_anthropic(prompt)
    except Exception:
        # Fallback to Gemini if Anthropic fails
        result = await _call_gemini(prompt)

    cleaned_text = _clean_llm_json(result["text"])

    # Validate JSON before storing
    try:
        json.loads(cleaned_text)
        result["text"] = cleaned_text
    except json.JSONDecodeError as exc:
        logger.warning("Phase 3 JSON validation failed: %s", exc)
        result["text"] = json.dumps({"_raw": cleaned_text, "_parse_error": str(exc)})

    cost = calc_cost(result["model"], result["tokens_in"], result["tokens_out"])

    await execute_insert(
        """INSERT INTO analysis_results (paper_id, phase, result, model_used, tokens_in, tokens_out, cost_usd)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (paper_id, "recipe", result["text"], result["model"],
         result["tokens_in"], result["tokens_out"], cost),
    )

    phase_status.status = "completed"
    phase_status.completed_at = datetime.utcnow().isoformat()
    phase_status.model_used = result["model"]
    phase_status.tokens_in = result["tokens_in"]
    phase_status.tokens_out = result["tokens_out"]
    phase_status.cost_usd = cost
    status.progress_pct = max(status.progress_pct, 60.0)
    status.total_cost_usd += cost
    status.total_tokens_in += result["tokens_in"]
    status.total_tokens_out += result["tokens_out"]

    return result


async def _run_deep_dive(paper_id: int, text: str, previous_results: list[str], status: AnalysisStatus) -> dict:
    """Phase 4: Deep dive - comprehensive analysis using Claude."""
    phase_status = PhaseStatus(
        phase=AnalysisPhase.DEEP_DIVE,
        status="running",
        started_at=datetime.utcnow().isoformat(),
    )
    status.phases.append(phase_status)
    status.current_phase = AnalysisPhase.DEEP_DIVE

    prev_context = "\n\n".join(previous_results[:3]) if previous_results else ""

    prompt = f"""너는 Sasoo(사수)라는 AI Co-Scientist야. 이 연구 논문에 대한 심층 분석을 해줘.

모든 텍스트 내용은 반드시 한국어로 작성해. JSON key 이름만 영어로 유지해.
전문적이면서도 이해하기 쉽게, 마치 선배 연구자가 후배에게 설명하듯이 써줘.

이전 분석 단계의 결과:
{prev_context[:3000]}

위 정보를 바탕으로 포괄적인 심층 분석을 제공해줘.

Return ONLY valid JSON (마크다운 펜스 없이):
{{
  "detailed_analysis": "논문의 기여도, 방법론, 결과에 대한 상세 분석 (여러 문단, 한국어)",
  "strengths": ["강점1 (한국어)", "강점2", ...],
  "weaknesses": ["약점1 (한국어)", "약점2", ...],
  "novelty_assessment": "이 연구의 새로움 평가 (한국어)",
  "comparison_to_prior_work": "기존 연구 대비 비교 (한국어)",
  "suggested_improvements": ["개선 제안1 (한국어)", ...],
  "follow_up_questions": ["후속 질문1 (한국어)", ...],
  "practical_applications": ["실용적 응용1 (한국어)", ...]
}}

논문 텍스트:
{text[:10000]}
"""

    try:
        result = await _call_anthropic(prompt)
    except Exception:
        result = await _call_gemini(prompt)

    cleaned_text = _clean_llm_json(result["text"])

    # Validate JSON before storing
    try:
        json.loads(cleaned_text)
        result["text"] = cleaned_text
    except json.JSONDecodeError as exc:
        logger.warning("Phase 4 JSON validation failed: %s", exc)
        result["text"] = json.dumps({"_raw": cleaned_text, "_parse_error": str(exc)})

    cost = calc_cost(result["model"], result["tokens_in"], result["tokens_out"])

    await execute_insert(
        """INSERT INTO analysis_results (paper_id, phase, result, model_used, tokens_in, tokens_out, cost_usd)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (paper_id, "deep_dive", result["text"], result["model"],
         result["tokens_in"], result["tokens_out"], cost),
    )

    phase_status.status = "completed"
    phase_status.completed_at = datetime.utcnow().isoformat()
    phase_status.model_used = result["model"]
    phase_status.tokens_in = result["tokens_in"]
    phase_status.tokens_out = result["tokens_out"]
    phase_status.cost_usd = cost
    # 80% — visualization step still needs to run after deep_dive
    status.progress_pct = max(status.progress_pct, 80.0)
    status.total_cost_usd += cost
    status.total_tokens_in += result["tokens_in"]
    status.total_tokens_out += result["tokens_out"]

    return result


# ---------------------------------------------------------------------------
# Phase 5: Visualization Planning & Generation  (Gemini Pro 3)
# ---------------------------------------------------------------------------

_MERMAID_SYNTAX_RULES = """CRITICAL RULES (Mermaid v10.x compatibility):
1. Start with the diagram type keyword (flowchart TD, flowchart LR, sequenceDiagram, mindmap, etc.).
2. NEVER use --- frontmatter blocks or accTitle/accDescr.
3. Use simple alphanumeric node IDs (A, B, step1). NEVER use Korean in node IDs.
4. ALWAYS wrap labels containing special characters in double quotes: A["레이저 소스 (1064nm)"].
5. Special characters that MUST be quoted: parentheses (), colons :, semicolons ;, pipes |, angles <>.
6. For edge labels use: A -->|"label text"| B
7. Keep labels concise (under 30 chars). Use Korean for all labels.
8. Do NOT use HTML tags except <br/> for line breaks.
9. Return ONLY the Mermaid code. No markdown fences, no explanation."""


async def _plan_visualizations(
    paper_id: int,
    text: str,
    previous_results: list[str],
    status: AnalysisStatus,
) -> list[dict]:
    """
    Use Gemini Pro 3 to decide which visualizations (up to 5) will best help
    understand the paper's methodology. Returns a plan as a list of dicts.
    """
    phase_status = PhaseStatus(
        phase=AnalysisPhase.DEEP_DIVE,  # piggyback on deep_dive phase for status
        status="running",
        started_at=datetime.utcnow().isoformat(),
    )
    # Don't append a new phase — we update the existing deep_dive phase's progress

    prev_context = "\n---\n".join(previous_results[:4])

    prompt = f"""너는 연구 논문 분석 시스템의 시각화 기획자야.

아래 분석 결과를 모두 읽고, 이 논문의 방법론과 기여를 완전히 이해하는 데
가장 도움이 될 다이어그램/그림을 결정해줘.

반드시 3~5개의 시각화 항목을 반환해. 가장 임팩트 있는 것을 선택해.

각 시각화를 두 가지 도구 중 하나로 분류해:
- "mermaid": 구조적/논리적 다이어그램 (플로우차트, 시퀀스, 마인드맵, 타임라인, 비교)
- "paperbanana": 물리적/시각적 일러스트 (장비 셋업, 광학 레이아웃, 세포/분자 도식, 개념도)

Return ONLY valid JSON (마크다운 펜스 없이). 아래 구조를 정확히 따라:
{{
  "visualizations": [
    {{
      "title": "짧은 설명 제목 (한국어)",
      "tool": "mermaid" or "paperbanana",
      "diagram_type": "flowchart|sequence|mindmap|timeline|methodology|conceptual|comparison",
      "description": "이 시각화가 왜 필요한지, 무엇을 보여주는지 2-3문장 설명 (한국어)",
      "category": "experimental_protocol|algorithm_flow|signal_flow|system_architecture|component_relationships|timeline|comparison|equipment_appearance|optical_table_layout|cell_molecule_schematic|physical_setup|conceptual_illustration"
    }}
  ]
}}

실험 방법을 최대한 이해할 수 있는 시각화를 우선시해.
고려할 것: 프로세스 흐름, 파라미터 관계, 장비 구성, 신호 경로, 비교표.

--- 분석 결과 (Phase 1-4) ---
{prev_context[:12000]}

--- 논문 텍스트 ---
{text[:5000]}
"""

    result = await _call_gemini(prompt, model="gemini-3-pro-preview")
    cost = calc_cost(result["model"], result["tokens_in"], result["tokens_out"])

    status.total_cost_usd += cost
    status.total_tokens_in += result["tokens_in"]
    status.total_tokens_out += result["tokens_out"]

    # Parse the plan
    raw = result["text"].strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines).strip()

    try:
        plan_data = json.loads(raw)
        items = plan_data.get("visualizations", [])
    except (json.JSONDecodeError, TypeError):
        # Fallback: create a single default flowchart
        items = [{
            "title": "실험 프로세스 흐름도",
            "tool": "mermaid",
            "diagram_type": "flowchart",
            "description": "논문의 실험 방법론 전체 흐름을 보여주는 플로우차트",
            "category": "experimental_protocol",
        }]

    # Cap at 5
    items = items[:5]

    # Store the plan in DB
    await execute_insert(
        """INSERT INTO analysis_results (paper_id, phase, result, model_used, tokens_in, tokens_out, cost_usd)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (paper_id, "viz_plan", json.dumps({"visualizations": items}, ensure_ascii=False),
         result["model"], result["tokens_in"], result["tokens_out"], cost),
    )

    return items


async def _generate_single_mermaid(paper_id: int, viz_item: dict, text: str, previous_results: list[str]) -> str:
    """Generate Mermaid code for a single visualization item using Gemini Pro 3."""
    import re as _re

    title = viz_item.get("title", "Diagram")
    diagram_type = viz_item.get("diagram_type", "flowchart")
    description = viz_item.get("description", "")

    prev_context = "\n---\n".join(previous_results[:4])

    prompt = f"""아래 시각화에 맞는 Mermaid {diagram_type} 다이어그램을 생성해줘.

제목: {title}
설명: {description}

{_MERMAID_SYNTAX_RULES}
추가 규칙: 모든 노드 레이블과 엣지 레이블을 반드시 한국어로 작성해.

분석 데이터와 논문 텍스트를 소스로 사용해:

--- 분석 데이터 ---
{prev_context[:6000]}

--- 논문 텍스트 ---
{text[:4000]}

다이어그램 타입 키워드로 시작하는 유효한 Mermaid 코드만 반환해.
"""

    result = await _call_gemini(prompt, model="gemini-3-pro-preview")

    mermaid_code = result["text"].strip()
    # Remove markdown fences
    if mermaid_code.startswith("```"):
        lines = mermaid_code.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        mermaid_code = "\n".join(lines).strip()

    # Sanitize: remove frontmatter + accTitle
    fm_match = _re.match(r"^\s*---\s*\n.*?\n\s*---\s*\n?", mermaid_code, _re.DOTALL)
    if fm_match:
        mermaid_code = mermaid_code[fm_match.end():]
    mermaid_code = _re.sub(r"^\s*accTitle\s*:.*$", "", mermaid_code, flags=_re.MULTILINE)
    mermaid_code = _re.sub(r"^\s*accDescr\s*:.*$", "", mermaid_code, flags=_re.MULTILINE)
    mermaid_code = mermaid_code.strip()

    return mermaid_code


async def _generate_single_paperbanana(paper_id: int, viz_item: dict, text: str, folder_name: str) -> dict:
    """
    Generate a PaperBanana illustration for a single visualization item.
    Returns {"image_url": ..., "image_path": ...} or empty dict on failure.
    """
    import logging as _logging
    _logger = _logging.getLogger(__name__)

    title = viz_item.get("title", "Illustration")
    description = viz_item.get("description", "")
    category = viz_item.get("category", "conceptual_illustration")

    # Try using the PaperBanana bridge (fully async — no thread needed)
    try:
        from services.viz.paperbanana_bridge import PaperBananaBridge
        bridge = PaperBananaBridge()
        _logger.info("PaperBanana bridge.is_available: %s for '%s'", bridge.is_available, title)
        if bridge.is_available:
            paper_dir = str(get_paper_dir(folder_name))

            path = await asyncio.wait_for(
                bridge.generate_illustration(viz_item, paper_dir),
                timeout=300.0,  # 5 minute timeout per illustration
            )
            if path:
                # Bridge saves to library/{folder}/paperbanana/{file}
                url = f"/static/library/{folder_name}/paperbanana/{Path(path).name}"
                return {"image_path": path, "image_url": url}
    except asyncio.TimeoutError:
        _logger.warning("PaperBanana generation timed out for '%s'", title)
    except Exception as exc:
        _logger.warning("PaperBanana bridge failed for '%s': %s", title, exc)
        _logger.warning("Traceback: %s", traceback.format_exc())

    # Fallback: Generate with PIL (simple diagram placeholder)
    _logger.info("Using PIL fallback for '%s'", title)
    try:
        output_dir = get_paperbanana_dir(folder_name)
        output_dir.mkdir(parents=True, exist_ok=True)

        from PIL import Image, ImageDraw, ImageFont
        import re as _re

        safe_title = _re.sub(r"[^\w\s-]", "", title).strip()
        safe_title = _re.sub(r"[-\s]+", "_", safe_title).lower() or "illustration"
        output_path = output_dir / f"{safe_title}_{paper_id}.png"

        width, height = 800, 600
        img = Image.new("RGB", (width, height), (30, 41, 59))
        draw = ImageDraw.Draw(img)

        # Try fonts with Korean support (platform-specific)
        font_lg = None
        font_sm = None
        font_candidates = [
            # Windows (Malgun Gothic - all Korean Windows)
            "C:/Windows/Fonts/malgunbd.ttf",
            "C:/Windows/Fonts/malgun.ttf",
            # macOS
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            # Linux
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        for fpath in font_candidates:
            try:
                font_lg = ImageFont.truetype(fpath, 24)
                font_sm = ImageFont.truetype(fpath, 16)
                break
            except (OSError, IOError):
                continue
        if font_lg is None:
            font_lg = ImageFont.load_default()
            font_sm = ImageFont.load_default()

        # Header
        draw.rectangle([(0, 0), (width, 60)], fill=(79, 70, 229))
        draw.text((20, 16), f"PaperBanana: {title[:40]}", fill=(255, 255, 255), font=font_lg)

        # Category badge
        draw.text((20, 80), f"Category: {category}", fill=(148, 163, 184), font=font_sm)

        # Description
        y = 120
        for line in _wrap_text(description, font_sm, width - 40):
            draw.text((20, y), line, fill=(226, 232, 240), font=font_sm)
            y += 24
            if y > height - 60:
                break

        # Footer
        draw.rectangle([(0, height - 40), (width, height)], fill=(79, 70, 229))
        draw.text((20, height - 32), "Generated by Sasoo (placeholder)", fill=(200, 200, 255), font=font_sm)

        img.save(str(output_path), "PNG")
        # PIL fallback saves to library/{folder}/paperbanana/ — use /static/library/ mount
        url = f"/static/library/{folder_name}/paperbanana/{output_path.name}"
        return {"image_path": str(output_path), "image_url": url}
    except Exception:
        return {}


async def _run_visualizations(
    paper_id: int,
    text: str,
    folder_name: str,
    previous_results: list[str],
    status: AnalysisStatus,
) -> list[dict]:
    """
    Full visualization pipeline:
    1. Gemini Pro 3 plans up to 5 visualizations
    2. Generate each (Mermaid or PaperBanana) in parallel
    3. Store results in DB
    """
    # Step 1: Plan
    viz_plan = await _plan_visualizations(paper_id, text, previous_results, status)

    # Step 2: Generate all in parallel
    async def generate_one(idx: int, item: dict) -> dict:
        tool = item.get("tool", "mermaid")
        result_item = {
            "id": idx + 1,
            "title": item.get("title", f"Visualization {idx + 1}"),
            "tool": tool,
            "diagram_type": item.get("diagram_type", "flowchart"),
            "description": item.get("description", ""),
            "category": item.get("category", ""),
            "status": "generating",
        }
        try:
            if tool == "mermaid":
                code = await _generate_single_mermaid(paper_id, item, text, previous_results)
                result_item["mermaid_code"] = code
                result_item["status"] = "completed"
            elif tool == "paperbanana":
                pb_result = await _generate_single_paperbanana(paper_id, item, text, folder_name)
                result_item["image_url"] = pb_result.get("image_url")
                result_item["image_path"] = pb_result.get("image_path")
                result_item["status"] = "completed" if pb_result else "error"
            else:
                result_item["status"] = "error"
                result_item["error_message"] = f"Unknown tool: {tool}"
        except Exception as e:
            result_item["status"] = "error"
            result_item["error_message"] = str(e)
        return result_item

    # Separate mermaid (can run in parallel) from paperbanana (run sequentially to avoid rate limits)
    mermaid_items = [(i, item) for i, item in enumerate(viz_plan) if item.get("tool") == "mermaid"]
    paperbanana_items = [(i, item) for i, item in enumerate(viz_plan) if item.get("tool") == "paperbanana"]
    other_items = [(i, item) for i, item in enumerate(viz_plan)
                   if item.get("tool") not in ("mermaid", "paperbanana")]

    # Run mermaid generations in parallel
    mermaid_tasks = [generate_one(i, item) for i, item in mermaid_items]
    mermaid_results = await asyncio.gather(*mermaid_tasks, return_exceptions=False) if mermaid_tasks else []

    # Run paperbanana generations sequentially to avoid API rate limits
    paperbanana_results = []
    for idx, (i, item) in enumerate(paperbanana_items):
        result = await generate_one(i, item)
        paperbanana_results.append(result)
        # Small delay between PaperBanana calls to avoid rate limiting
        if idx < len(paperbanana_items) - 1:
            await asyncio.sleep(2.0)

    # Run other tool types in parallel
    other_tasks = [generate_one(i, item) for i, item in other_items]
    other_results = await asyncio.gather(*other_tasks, return_exceptions=False) if other_tasks else []

    # Combine and sort by original index
    all_results = list(mermaid_results) + paperbanana_results + list(other_results)
    generated_items = sorted(all_results, key=lambda x: x.get("id", 0))

    # Step 3: Store all visualization results in DB
    viz_result = {
        "items": list(generated_items),
        "total_count": len(generated_items),
        "model_used": "gemini-3-pro-preview",
        "planned_at": datetime.utcnow().isoformat(),
    }
    await execute_insert(
        """INSERT INTO analysis_results (paper_id, phase, result, model_used, tokens_in, tokens_out, cost_usd)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (paper_id, "visualization", json.dumps(viz_result, ensure_ascii=False),
         "gemini-3-pro-preview", 0, 0, 0.0),
    )

    # Visualization complete — set progress to 100%
    status.progress_pct = 100.0

    return list(generated_items)


# ---------------------------------------------------------------------------
# Background analysis pipeline
# ---------------------------------------------------------------------------

async def _run_full_analysis(paper_id: int):
    """
    Execute the complete 4-phase analysis pipeline in background.
    Updates paper status and in-memory tracking as it progresses.
    """
    status = AnalysisStatus(
        paper_id=paper_id,
        overall_status="running",
        phases=[],
        progress_pct=0.0,
    )

    async with _analyses_lock:
        _running_analyses[paper_id] = status

    # Create cancellation event
    cancel_event = asyncio.Event()
    _cancel_events[paper_id] = cancel_event

    try:
        # Mark paper as analyzing
        await execute_update(
            "UPDATE papers SET status = ? WHERE id = ?",
            ("analyzing", paper_id),
        )

        # Load paper text
        paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
        if paper is None:
            raise ValueError(f"Paper {paper_id} not found")

        folder_name = paper["folder_name"]
        paper_dir = get_paper_dir(folder_name)

        # Read PDF text (cached)
        full_text = get_pdf_text(paper_dir)

        # Check for cancellation
        if cancel_event.is_set():
            status.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return

        # Phase 1 + 2: Run Screening and Visual in parallel (independent)
        r1, r2 = await asyncio.gather(
            _run_screening(paper_id, full_text, status),
            _run_visual(paper_id, full_text, folder_name, status),
        )

        # Check for cancellation
        if cancel_event.is_set():
            status.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return

        # Collect only successful results for downstream use
        previous = []
        if r1.get("text") and not _is_error_result(r1["text"]):
            previous.append(r1["text"])
        if r2.get("text") and not _is_error_result(r2["text"]):
            previous.append(r2["text"])

        # Phase 3: Recipe Extraction (depends on text only)
        r3 = await _run_recipe(paper_id, full_text, status)

        # Check for cancellation
        if cancel_event.is_set():
            status.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return

        if r3.get("text") and not _is_error_result(r3["text"]):
            previous.append(r3["text"])

        # Phase 4: Deep Dive (depends on all previous results)
        r4 = await _run_deep_dive(paper_id, full_text, previous, status)

        # Check for cancellation
        if cancel_event.is_set():
            status.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return

        if r4.get("text") and not _is_error_result(r4["text"]):
            previous.append(r4["text"])

        # Phase 5: Visualization Planning & Generation (Gemini Pro 3)
        # Gemini Pro 3 decides up to 5 visualizations, each Mermaid or PaperBanana
        all_results = []
        if r1.get("text") and not _is_error_result(r1["text"]):
            all_results.append(r1["text"])
        if r2.get("text") and not _is_error_result(r2["text"]):
            all_results.append(r2["text"])
        if r3.get("text") and not _is_error_result(r3["text"]):
            all_results.append(r3["text"])
        if r4.get("text") and not _is_error_result(r4["text"]):
            all_results.append(r4["text"])

        try:
            await _run_visualizations(
                paper_id, full_text, folder_name, all_results, status
            )
        except Exception as viz_err:
            # Visualization failure should NOT block the analysis from completing
            import logging
            logging.getLogger(__name__).warning(
                "Visualization generation failed for paper %d: %s", paper_id, viz_err
            )

        # Check for cancellation one last time
        if cancel_event.is_set():
            status.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return

        # Mark paper as completed
        await execute_update(
            "UPDATE papers SET status = ?, analyzed_at = ? WHERE id = ?",
            ("completed", datetime.utcnow().isoformat(), paper_id),
        )
        status.overall_status = "completed"

    except Exception as e:
        # Mark as error
        error_msg = f"{type(e).__name__}: {str(e)}"
        await execute_update(
            "UPDATE papers SET status = ? WHERE id = ?",
            ("error", paper_id),
        )
        status.overall_status = "error"

        # Record error in the current phase
        if status.phases:
            status.phases[-1].status = "error"
            status.phases[-1].error_message = error_msg

        # Store error as analysis result for debugging
        await execute_insert(
            """INSERT INTO analysis_results (paper_id, phase, result, model_used)
               VALUES (?, ?, ?, ?)""",
            (paper_id, "error", json.dumps({"error": error_msg, "traceback": traceback.format_exc()}), "system"),
        )

    finally:
        # Clean up cancellation event
        _cancel_events.pop(paper_id, None)
        # Schedule cleanup of stale analyses after 1 hour
        async def _cleanup_stale():
            await asyncio.sleep(3600)  # 1 hour
            async with _analyses_lock:
                if paper_id in _running_analyses:
                    status = _running_analyses[paper_id]
                    if status.overall_status != "running":
                        del _running_analyses[paper_id]
        asyncio.create_task(_cleanup_stale())


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/{paper_id}/run", status_code=202)
async def run_analysis(paper_id: int, background_tasks: BackgroundTasks):
    """
    Start the 4-phase analysis pipeline for a paper.
    Runs in background. Poll /status for progress.
    """
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    async with _analyses_lock:
        # Check if already running
        if paper_id in _running_analyses:
            running = _running_analyses[paper_id]
            if running.overall_status == "running":
                raise HTTPException(
                    status_code=409,
                    detail=f"Analysis for paper {paper_id} is already running.",
                )

        # Clear in-memory state from previous run
        if paper_id in _running_analyses:
            del _running_analyses[paper_id]

    # Check budget before starting
    from api.settings import _get_all_settings
    settings = await _get_all_settings()
    monthly_limit = float(settings.get("monthly_budget_limit", "50.0"))

    # Calculate current month spending
    current_month = datetime.utcnow().strftime("%Y-%m")
    month_start = f"{current_month}-01"
    month_num = int(current_month.split("-")[1])
    year = int(current_month.split("-")[0])
    if month_num == 12:
        month_end = f"{year + 1}-01-01"
    else:
        month_end = f"{year}-{month_num + 1:02d}-01"

    cost_rows = await fetch_all(
        "SELECT cost_usd FROM analysis_results WHERE created_at >= ? AND created_at < ? AND phase != 'error'",
        (month_start, month_end),
    )
    current_spending = sum(r.get("cost_usd") or 0.0 for r in cost_rows)

    if current_spending >= monthly_limit:
        raise HTTPException(
            status_code=402,
            detail=f"Monthly budget limit exceeded (${current_spending:.2f} / ${monthly_limit:.2f}). "
                   f"Increase your budget in Settings to continue.",
        )

    # Clear previous results if re-running
    db = await get_db()
    await db.execute("DELETE FROM analysis_results WHERE paper_id = ?", (paper_id,))
    await db.commit()

    # Launch background analysis
    background_tasks.add_task(_run_full_analysis, paper_id)

    return {
        "paper_id": paper_id,
        "status": "started",
        "message": "Analysis pipeline started. Poll /status for progress.",
    }


@router.post("/{paper_id}/cancel", status_code=200)
async def cancel_analysis(paper_id: int):
    """
    Cancel a running analysis for a paper.
    """
    # Check if there's a cancel event for this paper
    if paper_id in _cancel_events:
        _cancel_events[paper_id].set()
        return {"paper_id": paper_id, "status": "cancelling"}

    # Check if the paper is running and update its status
    if paper_id in _running_analyses:
        running = _running_analyses[paper_id]
        if running.overall_status == "running":
            running.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return {"paper_id": paper_id, "status": "cancelled"}

    raise HTTPException(status_code=404, detail=f"No running analysis for paper {paper_id}")


@router.get("/{paper_id}/status", response_model=AnalysisStatus)
async def get_analysis_status(paper_id: int):
    """Get current analysis progress for a paper."""
    # Check in-memory status first
    if paper_id in _running_analyses:
        return _running_analyses[paper_id]

    # Fall back to DB
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    results = await fetch_all(
        "SELECT * FROM analysis_results WHERE paper_id = ? AND phase != 'error' ORDER BY created_at",
        (paper_id,),
    )

    phases: list[PhaseStatus] = []
    total_cost = 0.0
    total_in = 0
    total_out = 0

    phase_order = ["screening", "visual", "recipe", "deep_dive"]
    completed_phases = {r["phase"] for r in results}

    for phase_name in phase_order:
        matching = [r for r in results if r["phase"] == phase_name]
        if matching:
            r = matching[-1]  # latest result for this phase
            cost = r.get("cost_usd") or 0.0
            tin = r.get("tokens_in") or 0
            tout = r.get("tokens_out") or 0
            phases.append(PhaseStatus(
                phase=AnalysisPhase(phase_name),
                status="completed",
                model_used=r.get("model_used"),
                tokens_in=tin,
                tokens_out=tout,
                cost_usd=cost,
                completed_at=r.get("created_at"),
            ))
            total_cost += cost
            total_in += tin
            total_out += tout
        else:
            phases.append(PhaseStatus(phase=AnalysisPhase(phase_name), status="pending"))

    # Check if visualization is also completed
    has_viz = "visualization" in completed_phases or "viz_plan" in completed_phases
    completed_main = len(completed_phases & set(phase_order))
    if has_viz:
        progress = (completed_main / 4) * 80 + 20  # 80% for phases + 20% for viz
    else:
        progress = (completed_main / 4) * 80  # Max 80% without viz
    progress = min(progress, 100.0)

    return AnalysisStatus(
        paper_id=paper_id,
        overall_status=paper["status"],
        phases=phases,
        progress_pct=progress,
        total_cost_usd=total_cost,
        total_tokens_in=total_in,
        total_tokens_out=total_out,
    )


@router.get("/{paper_id}/results", response_model=FullAnalysisResponse)
async def get_analysis_results(paper_id: int):
    """Get full analysis results across all phases."""
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    results = await fetch_all(
        "SELECT * FROM analysis_results WHERE paper_id = ? AND phase != 'error' ORDER BY created_at",
        (paper_id,),
    )

    # Build status
    status = await get_analysis_status(paper_id)

    # Parse results by phase
    phase_data: dict[str, Optional[dict]] = {
        "screening": None,
        "visual": None,
        "recipe": None,
        "deep_dive": None,
    }

    for r in results:
        phase = r["phase"]
        if phase in phase_data:
            try:
                phase_data[phase] = json.loads(r["result"])
            except (json.JSONDecodeError, TypeError):
                phase_data[phase] = {"raw_text": r["result"]}

    return FullAnalysisResponse(
        paper_id=paper_id,
        status=status,
        screening=phase_data["screening"],
        visual=phase_data["visual"],
        recipe=phase_data["recipe"],
        deep_dive=phase_data["deep_dive"],
    )


@router.get("/{paper_id}/figures", response_model=FigureListResponse)
async def get_figures(paper_id: int):
    """Get all extracted figures for a paper with AI analysis."""
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    rows = await fetch_all(
        "SELECT * FROM figures WHERE paper_id = ? ORDER BY figure_num",
        (paper_id,),
    )

    figures = [FigureInfo(**row) for row in rows]
    return FigureListResponse(figures=figures, total=len(figures))


@router.get("/{paper_id}/recipe")
async def get_recipe(paper_id: int):
    """Get the extracted recipe card for a paper."""
    result = await fetch_one(
        "SELECT * FROM analysis_results WHERE paper_id = ? AND phase = 'recipe' ORDER BY created_at DESC LIMIT 1",
        (paper_id,),
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No recipe found for paper {paper_id}. Run analysis first.",
        )

    try:
        recipe_data = json.loads(result["result"])
    except (json.JSONDecodeError, TypeError):
        recipe_data = {"raw_text": result["result"]}

    return {
        "paper_id": paper_id,
        "recipe": recipe_data,
        "model_used": result.get("model_used"),
        "created_at": result.get("created_at"),
    }


@router.get("/{paper_id}/mermaid", response_model=MermaidResult)
async def get_mermaid(paper_id: int):
    """
    Generate a Mermaid diagram for the paper's experimental process flow.
    Uses Gemini for fast diagram generation.
    """
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    # Check if recipe exists (we need it for the flow)
    recipe_result = await fetch_one(
        "SELECT result FROM analysis_results WHERE paper_id = ? AND phase = 'recipe' ORDER BY created_at DESC LIMIT 1",
        (paper_id,),
    )

    recipe_text = ""
    if recipe_result:
        recipe_text = f"\n\nRecipe data:\n{recipe_result['result'][:3000]}"

    # Get paper text for context (cached)
    folder_name = paper["folder_name"]
    paper_dir = get_paper_dir(folder_name)
    paper_text = ""
    try:
        paper_text = get_pdf_text(paper_dir)
    except FileNotFoundError:
        pass

    prompt = f"""Generate a Mermaid flowchart diagram that shows the experimental process/methodology flow of this research paper.

CRITICAL RULES (Mermaid v10.x compatibility):
1. Return ONLY the Mermaid code. No markdown fences, no explanation.
2. Start with "flowchart TD" or "flowchart LR". Do NOT use "graph TD".
3. NEVER use --- frontmatter blocks or accTitle/accDescr.
4. Use simple alphanumeric node IDs (A, B, step1, step2). NEVER use Korean in node IDs.
5. ALWAYS wrap labels containing special characters in double quotes: A["레이저 소스 (1064nm)"]
6. Special characters that MUST be quoted: parentheses (), colons :, semicolons ;, pipes |, angles <>.
7. For edge labels use: A -->|"label text"| B
8. Keep labels concise (under 30 chars).
9. Do NOT use HTML tags in labels except <br/> for line breaks.

Paper title: {paper['title']}
{recipe_text}

Paper text excerpt:
{paper_text[:5000]}

Return ONLY valid Mermaid syntax starting with "flowchart TD" or "flowchart LR".
"""

    result = await _call_gemini(prompt)

    # Clean up the mermaid code
    mermaid_code = result["text"].strip()
    # Remove markdown code fence if present
    if mermaid_code.startswith("```"):
        lines = mermaid_code.split("\n")
        # Remove first and last line (fences)
        lines = [l for l in lines if not l.strip().startswith("```")]
        mermaid_code = "\n".join(lines).strip()

    # Sanitize: remove frontmatter and accTitle if LLM included them anyway
    import re as _re
    # Strip --- frontmatter block
    fm_match = _re.match(r"^\s*---\s*\n.*?\n\s*---\s*\n?", mermaid_code, _re.DOTALL)
    if fm_match:
        mermaid_code = mermaid_code[fm_match.end():]
    # Strip accTitle/accDescr lines
    mermaid_code = _re.sub(r"^\s*accTitle\s*:.*$", "", mermaid_code, flags=_re.MULTILINE)
    mermaid_code = _re.sub(r"^\s*accDescr\s*:.*$", "", mermaid_code, flags=_re.MULTILINE)
    mermaid_code = mermaid_code.strip()

    return MermaidResult(
        paper_id=paper_id,
        mermaid_code=mermaid_code,
        diagram_type="flowchart",
        description=f"Process flow diagram for: {paper['title']}",
    )


@router.get("/{paper_id}/visualizations", response_model=VisualizationPlanResponse)
async def get_visualizations(paper_id: int):
    """
    Get the visualization plan and generated diagrams/figures for a paper.
    Gemini Pro 3 plans up to 5 visualizations (Mermaid + PaperBanana mix).
    """
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    # Look for stored visualization results
    viz_result = await fetch_one(
        "SELECT result FROM analysis_results WHERE paper_id = ? AND phase = 'visualization' ORDER BY created_at DESC LIMIT 1",
        (paper_id,),
    )

    if viz_result is None:
        # No visualizations generated yet
        return VisualizationPlanResponse(paper_id=paper_id)

    try:
        data = json.loads(viz_result["result"])
        items = [VisualizationItem(**item) for item in data.get("items", [])]
        return VisualizationPlanResponse(
            paper_id=paper_id,
            items=items,
            total_count=data.get("total_count", len(items)),
            model_used=data.get("model_used", ""),
            planned_at=data.get("planned_at"),
        )
    except (json.JSONDecodeError, TypeError):
        return VisualizationPlanResponse(paper_id=paper_id)


@router.get("/{paper_id}/report", response_model=ReportResponse)
async def get_report(paper_id: int):
    """
    Generate an integrated markdown report combining all analysis phases.
    """
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    results = await fetch_all(
        "SELECT * FROM analysis_results WHERE paper_id = ? AND phase != 'error' ORDER BY created_at",
        (paper_id,),
    )

    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"No analysis results found for paper {paper_id}. Run analysis first.",
        )

    # Build report sections
    sections: list[str] = []
    sections.append(f"# Analysis Report: {paper['title']}\n")
    sections.append(f"**Authors:** {paper.get('authors', 'N/A')}")
    sections.append(f"**Year:** {paper.get('year', 'N/A')}")
    sections.append(f"**Journal:** {paper.get('journal', 'N/A')}")
    sections.append(f"**DOI:** {paper.get('doi', 'N/A')}")
    sections.append(f"**Domain:** {paper.get('domain', 'N/A')}")
    sections.append(f"**Agent:** {paper.get('agent_used', 'N/A')}")
    sections.append(f"**Analyzed:** {paper.get('analyzed_at', 'N/A')}")
    sections.append("")

    phase_titles = {
        "screening": "Phase 1: Screening",
        "visual": "Phase 2: Visual Verification",
        "recipe": "Phase 3: Recipe Extraction",
        "deep_dive": "Phase 4: Deep Dive Analysis",
    }

    for r in results:
        phase = r["phase"]
        title = phase_titles.get(phase, phase.title())
        sections.append(f"## {title}\n")
        sections.append(f"*Model: {r.get('model_used', 'N/A')} | "
                        f"Tokens: {r.get('tokens_in', 0):,} in / {r.get('tokens_out', 0):,} out | "
                        f"Cost: ${r.get('cost_usd', 0):.4f}*\n")

        try:
            data = json.loads(r["result"])
            sections.append(_format_phase_data(phase, data))
        except (json.JSONDecodeError, TypeError):
            sections.append(r["result"])

        sections.append("")

    # Cost summary
    total_cost = sum(r.get("cost_usd", 0) or 0 for r in results)
    total_in = sum(r.get("tokens_in", 0) or 0 for r in results)
    total_out = sum(r.get("tokens_out", 0) or 0 for r in results)
    sections.append("## Cost Summary\n")
    sections.append(f"- **Total Cost:** ${total_cost:.4f}")
    sections.append(f"- **Total Tokens In:** {total_in:,}")
    sections.append(f"- **Total Tokens Out:** {total_out:,}")

    markdown = "\n".join(sections)

    return ReportResponse(
        paper_id=paper_id,
        title=paper["title"],
        markdown=markdown,
        generated_at=datetime.utcnow().isoformat(),
    )


@router.post("/{paper_id}/figures/{figure_id}/explain", response_model=FigureExplanationResponse)
async def explain_figure(paper_id: int, figure_id: int):
    """
    Generate a detailed expert-level explanation of a specific figure.
    Uses LLM to analyze the figure in context of the full paper text.
    Returns cached explanation if already generated.
    """
    return await explain_figure_handler(paper_id, figure_id)


@router.post("/{paper_id}/paperbanana", response_model=PaperBananaResponse)
async def generate_paperbanana(paper_id: int, request: PaperBananaRequest):
    """
    Generate a PaperBanana visual summary image for a paper.
    """
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    folder_name = paper["folder_name"]
    output_dir = get_paperbanana_dir(folder_name)

    # Get analysis results for the visual summary
    results = await fetch_all(
        "SELECT phase, result FROM analysis_results WHERE paper_id = ? AND phase != 'error'",
        (paper_id,),
    )

    analysis_data: dict = {}
    for r in results:
        try:
            analysis_data[r["phase"]] = json.loads(r["result"])
        except (json.JSONDecodeError, TypeError):
            analysis_data[r["phase"]] = {"raw": r["result"]}

    # Generate the PaperBanana image
    try:
        image_path = await _generate_paperbanana_image(
            paper=paper,
            analysis_data=analysis_data,
            output_dir=output_dir,
            style=request.style,
            language=request.language,
            include_recipe=request.include_recipe,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate PaperBanana image: {str(e)}",
        )

    # Build the URL path for the static file server
    filename = Path(image_path).name
    image_url = f"/static/library/{folder_name}/paperbanana/{filename}"

    # Get image dimensions
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            width, height = img.size
    except Exception:
        width, height = 0, 0

    return PaperBananaResponse(
        paper_id=paper_id,
        image_path=str(image_path),
        image_url=image_url,
        width=width,
        height=height,
    )
