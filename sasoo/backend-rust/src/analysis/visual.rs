//! Phase 2 visual verification (port of `_run_visual`, analysis_execution.py).
use crate::{
    analysis::{
        cache::{CacheInput, phase_cache_key},
        graph::{PhaseExecutor, ProviderGateway, RunContext, StageInput, StageOutput},
        screening::stage::{
            ChainCall, ChainSource, OPENAI_DOC_TEXT_CHAR_LIMIT, chain_previous_id, choice, clean_llm_json,
            input_coverage, is_error_result, parse_error_text, python_dumps, python_loads, python_str,
            result_cost_or_mark, result_row, run_chain_stage, source_signature, stage_max_output_tokens,
            stage_output,
        },
    },
    error::Result,
    providers::transport::BoxFuture,
    types::Json,
};
use serde_json::json;

pub const VISUAL_INSTRUCTION: &str = "이 논문의 그림·표·수식을 검증해줘.

figure_count(그림 수), tables_found(표 수), equations_found(수식 수),
diagram_types(다이어그램 종류: SEM/TEM/spectrum/graph/photograph/schematic 등),
quality_summary(그림 품질 전체 평가, 한국어), key_findings_from_visuals(시각자료에서
읽어낸 핵심 사항 리스트, 한국어)를 채워줘.

규칙:
- key_findings_from_visuals의 각 항목은 근거가 된 그림/표 번호로 시작해(예: \"Fig. 3: ...\", \"Table 2: ...\").
- 그림에서 실제로 읽을 수 있는 내용만 관찰로 적어. 수치·글자가 안 읽히면 추측하지 말고 \"판독 불가\"라고 표시해.
- 본문 주장과 그림 내용이 어긋나는 지점이 보이면 짚어줘.
- 함께 제공되는 figure/table 메타데이터(quality/confidence 등)는 추출 파이프라인 상태 정보일 뿐, 그림 내용의 과학적 타당성 근거가 아니야.";

/// `_load_visual_snapshot` result: artifact contract plus resolved figure and table rows.
#[derive(Clone, Debug)]
pub struct VisualSnapshot {
    pub contract: Json,
    pub figures: Vec<Json>,
    pub tables: Vec<Json>,
}

pub struct VisualExecutor {
    pub visual_input: String,
    pub snapshot: VisualSnapshot,
    pub source: ChainSource,
    /// Hex SHA-256 of the attached PDF (Gemini URI or OpenAI inline).
    pub pdf_sha256: Option<String>,
    pub system_instruction: String,
    pub single_attempt: bool,
    pub max_output_tokens: Option<u32>,
}

/// `document_context.build_visual_partial_cache_input` (sort_keys=True).
pub fn visual_partial_cache_input(figure_count: usize, table_count: usize, state: &str, error: &Json) -> String {
    String::from_utf8(
        crate::analysis::prompts::python_json_bytes(
            &json!({"figure_count": figure_count, "table_count": table_count, "visual_state": state, "visual_error": error}),
            false,
        )
        .unwrap_or_default(),
    )
    .unwrap_or_default()
}

/// `_doc_reference_phrase`.
pub fn doc_reference_phrase(openai: bool, pdf_provided: bool) -> &'static str {
    if openai && !pdf_provided { "위 논문 본문 텍스트(첫 단계에 첨부된 그림 이미지 포함)" } else { "위 논문 PDF" }
}

impl PhaseExecutor for VisualExecutor {
    fn run<'a>(
        &'a self,
        ctx: &'a RunContext,
        gateway: &'a dyn ProviderGateway,
        input: &'a StageInput,
    ) -> BoxFuture<'a, Result<StageOutput>> {
        Box::pin(async move {
            let choice = choice(ctx, "visual")?;
            let openai_pdf = matches!(self.source, ChainSource::OpenAiPdf { .. });
            let source_hash = match self.source {
                ChainSource::OpenAiPdf { .. } | ChainSource::GeminiFile(_) => self.pdf_sha256.as_deref(),
                _ => None,
            };
            let doc_text = match &self.source {
                ChainSource::DocText(t) => t.as_str(),
                _ => "",
            };
            let source_text = if doc_text.is_empty() { self.visual_input.as_str() } else { doc_text };
            let (figures, tables) = (&self.snapshot.figures, &self.snapshot.tables);
            let contract = &self.snapshot.contract;
            let state = contract.get("visual_state").and_then(Json::as_str).unwrap_or("");
            if !openai_pdf && (state != "ready" || (figures.is_empty() && tables.is_empty())) {
                return self.partial(&choice, source_text);
            }
            let mut figure_desc = String::new();
            if !figures.is_empty() || !tables.is_empty() {
                figure_desc = format!(
                    "\n\nExtracted {} resolved figures and {} resolved tables from the paper.",
                    figures.len(),
                    tables.len()
                );
                let get = |row: &Json, key: &str| python_str(row.get(key).unwrap_or(&Json::Null));
                for fig in figures {
                    figure_desc.push_str(&format!(
                        "\n- {}: quality={}, confidence={}, resolver={}",
                        get(fig, "figure_num"), get(fig, "quality"), get(fig, "confidence"), get(fig, "resolver_version")
                    ));
                }
                for table in tables.iter().take(10) {
                    figure_desc.push_str(&format!(
                        "\n- {}: confidence={}, method={}, resolver={}",
                        get(table, "table_num"), get(table, "confidence"), get(table, "parse_method"), get(table, "resolver_version")
                    ));
                }
            }
            let prompt_chain = format!(
                "{VISUAL_INSTRUCTION}\n\n{}를 직접 보고 시각 요소를 분석해줘.{figure_desc}",
                doc_reference_phrase(choice.provider == crate::types::ProviderId::OpenAi, openai_pdf)
            );
            let prompt_fallback = format!("논문 관련 텍스트:\n{}\n{figure_desc}\n\n{VISUAL_INSTRUCTION}", self.visual_input);
            let cache_key = String::from_utf8(phase_cache_key(&CacheInput {
                model: choice.model.clone(),
                thinking: choice.effort.clone().unwrap_or_default(),
                system_instruction: self.system_instruction.clone(),
                prompt: prompt_fallback.clone(),
                source_signature: source_signature(source_text, source_hash, "high"),
                max_output_tokens: self.max_output_tokens.or_else(|| stage_max_output_tokens("visual")).map(u64::from),
            })?)
            .unwrap_or_default();
            let mut ids = Vec::new();
            let call = ChainCall {
                phase: "visual",
                prompt_chain,
                prompt_fallback,
                system_instruction: self.system_instruction.clone(),
                previous_id: chain_previous_id(input),
                source: self.source.clone(),
                restart_context: String::new(),
                choice: choice.clone(),
                schema: crate::analysis::screening::stage::stage_schema("visual")?,
                single_attempt: self.single_attempt,
                max_output_tokens: self.max_output_tokens,
            };
            let (mut result, at) = run_chain_stage(gateway, &mut ids, &call).await?;
            let cleaned = clean_llm_json(result["text"].as_str().unwrap_or(""));
            result["text"] = match python_loads(&cleaned) {
                Some(mut parsed) if parsed.is_object() => {
                    if !is_error_result(&cleaned) {
                        parsed["_input_coverage"] = input_coverage(source_text, source_hash, Some(OPENAI_DOC_TEXT_CHAR_LIMIT));
                    }
                    parsed["reported_figure_count"] = parsed.get("figure_count").cloned().unwrap_or(Json::Null);
                    parsed["reported_table_count"] = parsed.get("tables_found").cloned().unwrap_or(Json::Null);
                    parsed["figure_count"] = json!(figures.len());
                    parsed["tables_found"] = json!(tables.len());
                    parsed["extracted_figure_count"] = json!(figures.len());
                    parsed["extracted_table_count"] = json!(tables.len());
                    parsed["source_total_counts_status"] = json!("unverified");
                    json!(python_dumps(&parsed, false))
                }
                // shortcut: Python stores str(json.JSONDecodeError) here.
                _ => json!(parse_error_text(&cleaned, "JSON parse failed")),
            };
            let cost = result_cost_or_mark(&mut result, at);
            Ok(stage_output(result_row("visual", &result, cost, &cache_key, &choice), ids, None))
        })
    }
}

impl VisualExecutor {
    /// Partial result stored without a provider call when visual artifacts are not ready.
    fn partial(&self, choice: &crate::analysis::screening::stage::ModelChoice, source_text: &str) -> Result<StageOutput> {
        let (figure_count, table_count) = (self.snapshot.figures.len(), self.snapshot.tables.len());
        let c = &self.snapshot.contract;
        let field = |k: &str| c.get(k).cloned().unwrap_or(Json::Null);
        let (quality_summary, mut key_findings) = if figure_count == 0 && table_count == 0 {
            (
                "이 논문에서는 그림과 표를 추출하지 못해 텍스트 분석만으로 진행했어요.".to_owned(),
                vec!["시각 asset이 준비되지 않아 텍스트 분석만으로 후속 단계를 진행했습니다.".to_owned()],
            )
        } else {
            (
                "시각 artifact가 아직 준비되지 않아 현재 확보된 DB 메타데이터만으로 partial visual result를 저장했습니다.".to_owned(),
                vec![format!("현재 DB 기준 resolved figure {figure_count}개, resolved table {table_count}개가 있습니다.")],
            )
        };
        let error = field("visual_error");
        if crate::analysis::screening::stage::truthy(&error) {
            key_findings.push(python_str(&error));
        }
        let partial = json!({
            "figure_count": figure_count,
            "tables_found": table_count,
            "extracted_figure_count": figure_count,
            "extracted_table_count": table_count,
            "source_total_counts_status": "unverified",
            "equations_found": 0,
            "diagram_types": [],
            "quality_summary": quality_summary,
            "key_findings_from_visuals": key_findings,
            "visual_ready": field("visual_ready"),
            "visual_state": field("visual_state"),
            "visual_error": error,
            "artifacts_ready": field("artifacts_ready"),
            "artifacts_error": field("artifacts_error"),
            "artifacts_partial": true,
            "_input_coverage": input_coverage(source_text, None, Some(OPENAI_DOC_TEXT_CHAR_LIMIT)),
        });
        let hash_source = format!(
            "{}\n{}",
            visual_partial_cache_input(figure_count, table_count, &python_str(&field("visual_state")), &error),
            source_signature(source_text, None, "high")
        );
        let result = json!({"text": python_dumps(&partial, false), "model": "system", "tokens_in": 0, "tokens_out": 0});
        let mut row = result_row("visual", &result, Some(0.0), &hash_source, choice);
        row["interaction_id"] = Json::Null;
        Ok(stage_output(row, Vec::new(), None))
    }
}
