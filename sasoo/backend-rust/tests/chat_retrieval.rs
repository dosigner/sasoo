use sasoo_backend::analysis::chat_retrieval::{Document, chunks, search, verify_pages};

#[test]
fn ranks_explicit_table_and_includes_adjacent_table() {
    let document = Document { parser_version: "fixture-v1".into(), full_text: "--- Page 1 ---\n\nSee Table 3 for results.\n\n--- Page 4 ---\n\n4.1 Experimental Setup\n\n| Model | Score |\n|---|---|\n| A | 5 |\n\nTable 3. Model comparison with baseline methods.".into() };
    let result = search(&document, "표 3을 설명해줘", 4);
    assert_eq!(result[0].page, Some(4));
    assert!(result[0].text.starts_with("Table 3"));
    assert!(result[1].text.starts_with("| Model"));
    assert_eq!(result[0].section.as_deref(), Some("4.1 Experimental Setup"));
    assert_eq!(result[0].extraction_version, "fixture-v1");
}

#[test]
fn page_confirmation_uses_independent_physical_text() {
    let document = Document {
        parser_version: "v1".into(),
        full_text: "--- Page 2 ---\n\nTable 3 Hyper parameters used for training each model".into(),
    };
    let result = search(&document, "Table 3", 4);
    let pages = vec![
        "A different page with different text here.".into(),
        "Table 3 Hyper parameters used for training each model".into(),
    ];
    let verified = verify_pages(result.clone(), Some(&pages));
    assert_eq!(verified[0].page, Some(2));
    assert_eq!(verified[0].extraction_status, "page_confirmed");
    let mut wrong = result.clone();
    wrong[0].page = Some(1);
    assert_eq!(verify_pages(wrong, Some(&pages))[0].page, None);
    assert_eq!(
        verify_pages(result, None)[0].extraction_status,
        "page_unknown"
    );
}

#[test]
fn rejects_unrelated_terms_and_handles_unicode_chunk_boundaries() {
    let text = format!("--- Page 1 ---\n\n{}", "한".repeat(1801));
    let document = Document {
        parser_version: "v1".into(),
        full_text: text,
    };
    let parts = chunks(&document);
    assert_eq!(parts.len(), 2);
    assert_eq!(parts[0].text.chars().count(), 1800);
    assert_eq!(parts[1].text, "한");
    assert!(search(&document, "Table 9 model", 4).is_empty());
    assert!(search(&document, "학습 데이터는 뭐야?", 4).is_empty());
}

#[test]
fn bare_subsection_and_explicit_missing_target_are_consistent() {
    let document = Document { parser_version: "v1".into(), full_text: "--- Page 5 ---\n\n4.1 Experimental Setup\n\nTraining data.\n\nModel performance is high.".into() };
    let result = search(&document, "4.1절을 설명해줘", 4);
    assert!(!result.is_empty());
    assert!(result.iter().all(|c| c.page == Some(5)));
    assert!(search(&document, "Table 3 model", 4).is_empty());
}

#[test]
#[ignore = "Requires the local, previously frozen three-paper validation corpus"]
fn frozen_real_paper_search_ranking_matches_python() {
    use std::path::PathBuf;
    let root =
        PathBuf::from(std::env::var("SASOO_CHAT_PARITY_DIR").expect("set SASOO_CHAT_PARITY_DIR"));
    let rows: Vec<serde_json::Value> =
        serde_json::from_slice(&std::fs::read(root.join("retrieval-results.json")).unwrap())
            .unwrap();
    let mut mismatches = vec![];
    for row in &rows {
        let paper = row["paper"].as_str().unwrap();
        let doc: Document = serde_json::from_slice(
            &std::fs::read(
                root.join("papers")
                    .join(paper)
                    .join(".document_context.json"),
            )
            .unwrap(),
        )
        .unwrap();
        let result = search(&doc, row["question"].as_str().unwrap(), 4);
        let actual: Vec<&str> = result.iter().map(|c| c.chunk_sha256.as_str()).collect();
        let expected: Vec<&str> = row["results"]
            .as_array()
            .unwrap()
            .iter()
            .map(|r| r["metadata"]["chunk_sha256"].as_str().unwrap())
            .collect();
        if actual != expected {
            mismatches.push(row["id"].as_str().unwrap().to_owned());
        }
    }
    assert!(
        mismatches.is_empty(),
        "Ranking differs from captured Python: {mismatches:?}"
    );
}

#[test]
#[ignore = "Requires local PDF text independently extracted from the frozen validation corpus"]
fn frozen_real_paper_page_confirmation_matches_python() {
    use std::path::PathBuf;
    let root =
        PathBuf::from(std::env::var("SASOO_CHAT_PARITY_DIR").expect("set SASOO_CHAT_PARITY_DIR"));
    let pages: serde_json::Value = serde_json::from_slice(
        &std::fs::read(std::env::var("SASOO_CHAT_PAGE_TEXT").expect("set SASOO_CHAT_PAGE_TEXT"))
            .unwrap(),
    )
    .unwrap();
    let rows: Vec<serde_json::Value> =
        serde_json::from_slice(&std::fs::read(root.join("retrieval-results.json")).unwrap())
            .unwrap();
    let mut mismatches = vec![];
    for row in &rows {
        let paper = row["paper"].as_str().unwrap();
        let doc: Document = serde_json::from_slice(
            &std::fs::read(
                root.join("papers")
                    .join(paper)
                    .join(".document_context.json"),
            )
            .unwrap(),
        )
        .unwrap();
        let physical: Vec<String> = serde_json::from_value(pages[paper].clone()).unwrap();
        let result = verify_pages(
            search(&doc, row["question"].as_str().unwrap(), 4),
            Some(&physical),
        );
        let actual: Vec<Option<usize>> = result.iter().map(|c| c.page).collect();
        let expected: Vec<Option<usize>> = row["results"]
            .as_array()
            .unwrap()
            .iter()
            .map(|r| r["displayed_physical_page"].as_u64().map(|x| x as usize))
            .collect();
        if actual != expected {
            mismatches.push(row["id"].as_str().unwrap().to_owned());
        }
    }
    assert!(
        mismatches.is_empty(),
        "Page confirmation differs from captured Python: {mismatches:?}"
    );
}

#[test]
fn target_does_not_confuse_subnumber_and_finds_later_occurrence() {
    let document = Document {
        parser_version: "v1".into(),
        full_text:
            "--- Page 1 ---\n\nTable 3.1 is not the target but Table 3 has the requested results."
                .into(),
    };
    let result = search(&document, "Table 3", 4);
    assert_eq!(result.len(), 1);
    let document = Document {
        parser_version: "v1".into(),
        full_text: "--- Page 1 ---\n\nTable 30 is a different table.".into(),
    };
    assert!(search(&document, "Table 3", 4).is_empty());
}
