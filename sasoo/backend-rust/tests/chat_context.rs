use sasoo_backend::analysis::{
    chat_context::{Phase, PhaseState, assemble_context},
    chat_retrieval::Document,
    selection_context::Selection,
};

#[test]
fn sends_excerpts_and_snapshots_metadata_and_analysis_version() {
    let document = Document {
        parser_version: "v1".into(),
        full_text: "--- Page 1 ---\n\nTable 1 Shows clear results from three benchmark models."
            .into(),
    };
    let pages = vec!["Table 1 Shows clear results from three benchmark models.".into()];
    let phases = vec![
        Phase {
            name: "citation".into(),
            result_id: Some(17),
            state: PhaseState::Completed,
            text: "Analysis was completed.".into(),
        },
        Phase {
            name: "recipe".into(),
            result_id: Some(18),
            state: PhaseState::Partial,
            text: "DO NOT USE".into(),
        },
    ];
    let selection = Some(Selection {
        text: "clear results from three benchmark models".into(),
        page: 1,
        end_page: 1,
    });
    let context = assemble_context(
        &document,
        "Table 1 citation",
        Some(&pages),
        selection,
        &phases,
    )
    .unwrap();
    assert!(context.model_material.contains("clear results"));
    assert!(!context.model_material.contains("DO NOT USE"));
    let snapshot = serde_json::to_string(&context.sources).unwrap();
    assert!(!snapshot.contains("clear results"));
    assert!(!snapshot.contains("Analysis was completed."));
    assert!(snapshot.contains("17"));
    assert!(!snapshot.contains("DO NOT USE"));
    assert_eq!(context.phase_states["recipe"], "partial");
}
#[test]
fn unavailable_pdf_and_failed_phase_are_explicit() {
    let document = Document {
        parser_version: "v1".into(),
        full_text: "--- Page 2 ---\n\nTable 2 Valid sample with sufficient words here.".into(),
    };
    let phase = Phase {
        name: "citation".into(),
        result_id: Some(8),
        state: PhaseState::Error,
        text: "wrong".into(),
    };
    let ctx = assemble_context(&document, "Table 2", None, None, &[phase]).unwrap();
    assert!(
        ctx.sources
            .iter()
            .any(|s| s["key"] == "retrieved" && s["page"].is_null())
    );
    assert_eq!(ctx.phase_states["citation"], "error");
    assert!(!ctx.model_material.contains("wrong"));
}

#[test]
fn unrelated_completed_phase_is_not_sent_but_remains_completed() {
    let document = Document {
        parser_version: "v1".into(),
        full_text: "--- Page 1 ---\n\nTable 1 Clear results on several sample models.".into(),
    };
    let phase = Phase {
        name: "citation".into(),
        result_id: Some(11),
        state: PhaseState::Completed,
        text: "bibliography data".into(),
    };
    let result = assemble_context(&document, "Explain Table 1", None, None, &[phase]).unwrap();
    assert_eq!(result.phase_states["citation"], "completed");
    assert!(!result.model_material.contains("bibliography data"));
    assert!(!result.sources.iter().any(|s| s["result_id"] == 11));
}
