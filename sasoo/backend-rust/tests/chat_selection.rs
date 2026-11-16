use sasoo_backend::analysis::selection_context::{Selection, match_selection};

fn selection(text: &str, page: usize, end_page: usize) -> Selection {
    Selection {
        text: text.into(),
        page,
        end_page,
    }
}
#[test]
fn confirms_unique_selection_and_includes_neighboring_text() {
    let result = match_selection(
        &[
            "Before paragraph.\n\nA selected sentence with enough words.\n\nAfter paragraph."
                .into(),
        ],
        selection("A selected sentence with enough words.", 1, 1),
    )
    .unwrap();
    assert_eq!(result.status, "matched");
    assert!(result.excerpt.unwrap().contains("selected sentence"));
}
#[test]
fn duplicate_and_wrong_page_are_never_confirmed() {
    let result = match_selection(
        &["duplicate sentence. duplicate sentence.".into()],
        selection("duplicate sentence.", 1, 1),
    )
    .unwrap();
    assert_eq!(result.status, "unverified");
    let result =
        match_selection(&["other text".into()], selection("unique sentence", 2, 2)).unwrap();
    assert_eq!(result.status, "unverified");
}
#[test]
fn unicode_cross_page_and_invalid_inputs() {
    let pages = vec!["첫쪽 선택된".into(), "문장 끝".into()];
    let result = match_selection(&pages, selection("선택된 문장", 1, 2)).unwrap();
    assert_eq!(result.status, "matched");
    assert!(match_selection(&pages, selection("x", 0, 1)).is_err());
    let not_crossing = match_selection(&pages, selection("첫쪽 선택된", 1, 2)).unwrap();
    assert_eq!(not_crossing.status, "unverified");
}
#[test]
fn line_break_hyphen_is_matched_without_changing_source_text() {
    let result = match_selection(
        &["before atmos-\npheric turbulence after".into()],
        selection("atmospheric turbulence", 1, 1),
    )
    .unwrap();
    assert_eq!(result.status, "matched");
    assert!(result.excerpt.unwrap().contains("atmos-\npheric"));
}

#[test]
fn line_hyphen_must_be_present_in_pdf_and_not_a_formula() {
    assert_eq!(
        match_selection(&["xy- zw = a".into()], selection("xyzw = a", 1, 1))
            .unwrap()
            .status,
        "unverified"
    );
    assert_eq!(
        match_selection(&["xyzw = a".into()], selection("xy- zw = a", 1, 1))
            .unwrap()
            .status,
        "unverified"
    );
    assert_eq!(
        match_selection(
            &["The proba-\nbility is high.".into()],
            selection("The proba- bility is high.", 1, 1)
        )
        .unwrap()
        .status,
        "matched"
    );
}

#[test]
#[ignore = "Requires local PDF blocks independently extracted from the frozen validation corpus"]
fn frozen_pdf_selections_match_python() {
    use std::path::PathBuf;
    let root =
        PathBuf::from(std::env::var("SASOO_CHAT_PARITY_DIR").expect("set SASOO_CHAT_PARITY_DIR"));
    let page_blocks: serde_json::Value = serde_json::from_slice(
        &std::fs::read(
            std::env::var("SASOO_CHAT_PAGE_BLOCKS").expect("set SASOO_CHAT_PAGE_BLOCKS"),
        )
        .unwrap(),
    )
    .unwrap();
    let rows: Vec<serde_json::Value> =
        serde_json::from_slice(&std::fs::read(root.join("selection-results.json")).unwrap())
            .unwrap();
    for row in rows {
        let id = row["id"].as_str().unwrap();
        let paper = id.split('-').next().unwrap();
        let raw = &row["result"]["selection"];
        let selection = Selection {
            text: raw["text"].as_str().unwrap().into(),
            page: raw["page"].as_u64().unwrap() as usize,
            end_page: raw["end_page"].as_u64().unwrap() as usize,
        };
        let source: Vec<String> = serde_json::from_value(page_blocks[paper].clone()).unwrap();
        let result =
            match_selection(&source[selection.page - 1..selection.end_page], selection).unwrap();
        assert_eq!(
            result.status,
            row["result"]["status"].as_str().unwrap(),
            "{id}"
        );
        assert_eq!(
            result.excerpt.as_deref(),
            row["result"]["excerpt"].as_str(),
            "{id}"
        );
    }
}

#[test]
fn whitespace_before_wrapped_hyphenation_is_preserved() {
    let result=match_selection(&["The proba-  \nbility is high.".into()],selection("The proba- bility is high.",1,1)).unwrap();
    assert_eq!(result.status,"matched");
}
