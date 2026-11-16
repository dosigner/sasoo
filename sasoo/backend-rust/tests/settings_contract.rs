use sasoo_backend::http::settings::{
    SecretDisplay, SettingsPatch, effective_provider, mask_api_key, parse_research_areas,
    prepare_settings_patch, settings_from_rows,
};
use serde_json::json;
use std::collections::BTreeMap;

#[test]
fn null_mask_clear_and_provider_mirror_have_distinct_semantics() {
    let patch: SettingsPatch = serde_json::from_value(json!({
        "openai_api_key": null, "gemini_api_key": "abcdefgh...wxyz",
        "ai_provider": "gemini", "image_provider": "openai", "theme": null,
        "auto_analyze": false,
    }))
    .unwrap();
    let prepared =
        prepare_settings_patch(patch, "library_path_darwin", |_| unreachable!()).unwrap();
    assert!(prepared.secret_updates.is_empty());
    assert!(!prepared.stored_updates.contains_key("openai_api_key"));
    assert!(!prepared.stored_updates.contains_key("gemini_api_key"));
    assert!(!prepared.stored_updates.contains_key("theme"));
    assert_eq!(prepared.stored_updates["image_provider"], "gemini");
    assert_eq!(prepared.stored_updates["auto_analyze"], "false");
    let clear: SettingsPatch = serde_json::from_value(json!({"openai_api_key":""})).unwrap();
    let clear = prepare_settings_patch(clear, "library_path_darwin", |_| unreachable!()).unwrap();
    assert_eq!(clear.secret_updates["openai_api_key"], None);
    assert_eq!(clear.stored_updates["openai_api_key"], "");
}

#[test]
fn empty_and_all_null_are_rejected_but_mask_only_is_accepted() {
    for input in [json!({}), json!({"theme":null}), json!({"unknown":3})] {
        let patch = serde_json::from_value(input).unwrap();
        assert_eq!(
            prepare_settings_patch(patch, "library_path_darwin", |_| unreachable!())
                .unwrap_err()
                .to_string(),
            "No settings to update."
        );
    }
    let patch = serde_json::from_value(json!({"openai_api_key":"..."})).unwrap();
    assert!(
        prepare_settings_patch(patch, "library_path_darwin", |_| unreachable!())
            .unwrap()
            .stored_updates
            .is_empty()
    );
}

#[test]
fn unicode_mask_uses_python_codepoints_and_profile_order_is_preserved() {
    assert_eq!(mask_api_key(""), "");
    assert_eq!(mask_api_key("짧은키"), "***");
    assert_eq!(
        mask_api_key("가나다라마바사아자차카타파하거너"),
        "가나다라마바사아...파하거너"
    );
    let input = vec![
        "광학".to_owned(),
        "기계".to_owned(),
        "전자".to_owned(),
        "제외".to_owned(),
    ];
    let patch = SettingsPatch {
        research_areas: Some(input),
        research_context: Some("실험 맥락".into()),
        ..Default::default()
    };
    let prepared =
        prepare_settings_patch(patch, "library_path_darwin", |_| unreachable!()).unwrap();
    assert_eq!(
        prepared.stored_updates["research_areas"],
        r#"["\uad11\ud559", "\uae30\uacc4", "\uc804\uc790"]"#
    );
    assert_eq!(
        parse_research_areas(r#"[1,"광학",null,"기계","전자","제외"]"#),
        vec!["광학", "기계", "전자"]
    );
    assert!(parse_research_areas("{}").is_empty());
    assert!(parse_research_areas("bad JSON").is_empty());
}

#[test]
fn response_keeps_unknown_unreadable_and_selected_provider_separate() {
    let rows = BTreeMap::from([
        ("ai_provider".into(), "gemini".into()),
        ("pdf_parser_mode".into(), "legacy".into()),
        ("extraction_pipeline_version".into(), "legacy".into()),
        ("research_areas".into(), r#"["광학"]"#.into()),
    ]);
    let secrets = SecretDisplay {
        openai_masked: mask_api_key("sk-synthetic-long-key"),
        gemini_masked: String::new(),
        openai_unreadable: false,
        gemini_unreadable: true,
        openai_available: true,
        gemini_available: false,
    };
    let dto = settings_from_rows(&rows, "/synthetic/library", secrets).unwrap();
    let wire = serde_json::to_value(dto).unwrap();
    assert_eq!(wire["gemini_key_unreadable"], true);
    assert_eq!(wire["gemini_api_key"], "");
    assert_eq!(wire["active_provider"], "openai");
    assert_eq!(wire["ai_provider"], "gemini");
    assert_eq!(wire["switched_to"], "openai");
    assert_eq!(wire["pdf_parser_mode"], "java");
    assert_eq!(wire["extraction_pipeline_version"], "resolver_v1");
    assert_eq!(wire["library_path"], "/synthetic/library");
    assert_eq!(
        effective_provider(Some("wrong"), true, true),
        Some("openai")
    );
    assert_eq!(effective_provider(Some("gemini"), false, false), None);
}

#[test]
fn invalid_engine_or_library_cannot_prepare_any_write() {
    for input in [
        json!({"theme":"dark","pdf_parser_mode":"other"}),
        json!({"extraction_pipeline_version":"legacy"}),
        json!({"pdf_visual_engine":"openai"}),
    ] {
        let patch = serde_json::from_value(input).unwrap();
        assert!(prepare_settings_patch(patch, "library_path_darwin", |_| unreachable!()).is_err());
    }
    let patch = serde_json::from_value(json!({"library_path":"relative","theme":"dark"})).unwrap();
    assert!(
        prepare_settings_patch(patch, "library_path_darwin", |_| Err(
            sasoo_backend::error::SasooError::InvalidInput("absolute required".into())
        ))
        .is_err()
    );
    let patch = serde_json::from_value(json!({"library_path":"/safe/../library"})).unwrap();
    let prepared =
        prepare_settings_patch(patch, "library_path_darwin", |_| Ok("/library".into())).unwrap();
    assert_eq!(prepared.stored_updates["library_path_darwin"], "/library");
    assert!(!prepared.stored_updates.contains_key("library_path"));
}

#[test]
fn credential_display_does_not_imply_available_key() {
    let dto = settings_from_rows(
        &BTreeMap::new(),
        "/synthetic/library",
        SecretDisplay {
            openai_masked: mask_api_key("   "),
            openai_available: false,
            ..Default::default()
        },
    )
    .unwrap();
    let wire = serde_json::to_value(dto).unwrap();
    assert_eq!(wire["openai_api_key"], "***");
    assert!(wire["active_provider"].is_null());
    assert!(wire["switched_to"].is_null());
}

#[test]
fn research_area_storage_matches_python_ascii_and_surrogate_escaping() {
    let patch = SettingsPatch {
        research_areas: Some(vec!["\u{7f}😀e\u{301}\n".into()]),
        ..Default::default()
    };
    let prepared =
        prepare_settings_patch(patch, "library_path_darwin", |_| unreachable!()).unwrap();
    assert_eq!(
        prepared.stored_updates["research_areas"],
        r#"["\u007f\ud83d\ude00e\u0301\n"]"#
    );
}
