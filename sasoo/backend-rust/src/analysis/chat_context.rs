//! Assemble model evidence and its metadata without storing source excerpts.
use super::{
    chat_retrieval::{Document, is_stop, search, verify_pages, words},
    selection_context::{Selection, match_selection},
};
use crate::error::{Result, SasooError};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PhaseState {
    Completed,
    Partial,
    Error,
    Missing,
}
#[derive(Debug, Clone)]
pub struct Phase {
    pub name: String,
    pub result_id: Option<i64>,
    pub state: PhaseState,
    pub text: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContextEvidence {
    pub model_material: String,
    pub sources: Vec<Value>,
    pub phase_states: BTreeMap<String, String>,
}

/// `physical_pages` is PDF-derived text, independent from the document sidecar.
pub fn assemble_context(
    document: &Document,
    question: &str,
    physical_pages: Option<&[String]>,
    selection: Option<Selection>,
    phases: &[Phase],
) -> Result<ContextEvidence> {
    let mut materials = vec![];
    let mut sources = vec![];
    let mut phase_states = BTreeMap::new();
    let question_lower = question.to_lowercase();
    let terms: Vec<_> = words(&question_lower)
        .into_iter()
        .filter(|word| !is_stop(word))
        .collect();
    if let Some(selection) = selection {
        let selected_pages = physical_pages
            .and_then(|p| {
                let start = selection.page.checked_sub(1)?;
                if selection.end_page < selection.page {
                    return None;
                }
                p.get(start..selection.end_page)
            })
            .unwrap_or(&[]);
        let matched = match_selection(selected_pages, selection)?;
        let body =
            serde_json::to_value(&matched).map_err(|e| SasooError::Internal(e.to_string()))?;
        let page = if matched.status == "matched" {
            Some(matched.selection.page)
        } else {
            None
        };
        let end_page = if page.is_some() {
            Some(matched.selection.end_page)
        } else {
            None
        };
        let truncated =
            matched.partial_before.unwrap_or(false) || matched.partial_after.unwrap_or(false);
        materials.push(json!({"key":"selection","value":body}));
        sources.push(json!({"key":"selection","label":if page.is_some(){"선택 구절과 확인된 주변 문맥"}else{"선택 구절 (주변 문맥 미확인)"},"page":page,"end_page":end_page,"truncated":truncated,"chars":serde_json::to_string(&matched).map_err(|e|SasooError::Internal(e.to_string()))?.chars().count()}));
    }
    let retrieved = verify_pages(search(document, question, 4), physical_pages);
    if retrieved.is_empty() {
        sources.push(json!({"key":"retrieval_status","label":"질문과 관련된 원문 검색 결과 없음","chars":0,"truncated":false}));
    }
    for chunk in retrieved {
        let excerpt: String = chunk.text.chars().take(1200).collect();
        let truncated = chunk.truncated || excerpt.chars().count() < chunk.text.chars().count();
        let source = json!({"key":"retrieved","label":"검색된 원문","page":chunk.page,"section":chunk.section,"extraction_version":chunk.extraction_version,"text_sha256":chunk.text_sha256,"chunk_sha256":chunk.chunk_sha256,"extraction_status":chunk.extraction_status,"chars":excerpt.chars().count(),"truncated":truncated,"excerpt":excerpt});
        materials.push(source.clone());
        let mut metadata = source;
        metadata
            .as_object_mut()
            .expect("source object")
            .remove("excerpt");
        sources.push(metadata);
    }
    for phase in phases {
        if phase.name.trim().is_empty() || phase_states.contains_key(&phase.name) {
            return Err(SasooError::InvalidInput(
                "Phase names must be unique and nonempty".into(),
            ));
        }
        let (label, triggers): (&str, &[&str]) = match phase.name.as_str() {
            "screening" => (
                "스크리닝 결과",
                &["기여", "핵심", "목적", "요약", "contribution", "summary"],
            ),
            "citation" => ("인용 분석 결과", &["인용", "citation", "참고문헌"]),
            "visual" => ("시각 분석 결과", &["그림", "표", "figure", "fig", "table"]),
            "recipe" => (
                "레시피 추출 결과",
                &[
                    "실험",
                    "데이터",
                    "학습",
                    "방법",
                    "training",
                    "dataset",
                    "method",
                ],
            ),
            "deep_dive" => (
                "심층 분석 결과",
                &["약점", "한계", "weakness", "limitation"],
            ),
            _ => return Err(SasooError::InvalidInput("Unknown analysis phase".into())),
        };
        let status = match phase.state {
            PhaseState::Completed => "completed",
            PhaseState::Partial => "partial",
            PhaseState::Error => "error",
            PhaseState::Missing => "missing",
        };
        phase_states.insert(phase.name.clone(), status.to_owned());
        if matches!(phase.state, PhaseState::Completed) {
            let id = phase.result_id.filter(|id| *id > 0).ok_or_else(|| {
                SasooError::InvalidInput("Completed phase requires a result ID".into())
            })?;
            let excerpt: String = phase.text.chars().take(3000).collect();
            let snippet_lower = excerpt.to_lowercase();
            if !triggers.iter().any(|term| question_lower.contains(term))
                && !terms
                    .iter()
                    .any(|term| term.chars().count() >= 3 && snippet_lower.contains(term))
            {
                continue;
            }
            let source = json!({"key":phase.name,"label":label,"result_id":id,"chars":excerpt.chars().count(),"truncated":phase.text.chars().count()>3000,"excerpt":excerpt});
            materials.push(source.clone());
            let mut metadata = source;
            metadata
                .as_object_mut()
                .expect("source object")
                .remove("excerpt");
            sources.push(metadata);
        }
    }
    materials.push(json!({"key":"analysis_status","value":phase_states}));
    let model_material =
        serde_json::to_string(&materials).map_err(|e| SasooError::Internal(e.to_string()))?;
    Ok(ContextEvidence {
        model_material,
        sources,
        phase_states,
    })
}

/// Format completed server history with its original analysis result IDs.
pub fn transcript(
    history: &[crate::storage::discussion::Message],
    question: &str,
) -> Result<String> {
    let mut parts = Vec::new();
    for message in history {
        if message.kind != "user" && !(message.kind == "sasoo" && message.status == "complete") {
            continue;
        }
        let mut content = message.content.clone();
        if message.kind == "sasoo" {
            let phases: Vec<Value> = message
                .context
                .as_ref()
                .and_then(|c| c.get("sources"))
                .and_then(Value::as_array)
                .map(|sources| {
                    sources
                        .iter()
                        .filter_map(|source| {
                            let id = source.get("result_id").filter(|id| !id.is_null())?;
                            Some(json!([source.get("key")?, id]))
                        })
                        .collect()
                })
                .unwrap_or_default();
            if !phases.is_empty() {
                let bytes = super::prompts::python_json_bytes(&Value::Array(phases), false)?;
                let encoded =
                    String::from_utf8(bytes).map_err(|e| SasooError::Internal(e.to_string()))?;
                content.push_str(&format!("\n[이 답변 당시 분석 결과 ID: {encoded}]"));
            }
        }
        parts.push(format!(
            "{}: {}",
            if message.kind == "user" {
                "사용자"
            } else {
                "사수"
            },
            content
        ));
    }
    parts.push(format!("사용자: {question}"));
    Ok(parts.join("\n"))
}
