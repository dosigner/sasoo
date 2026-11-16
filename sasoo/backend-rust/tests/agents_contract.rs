//! F04/F05 and chain system instructions against Python (tests/agents_oracle.py).
use sasoo_backend::analysis::{
    agents::{parse_agent_md, persona_prompt},
    config::FrozenAgent,
    prompts::{chain_system_instruction, parse_research_areas, reader_profile_block},
    selection::{agent_for_domain, screening_domain},
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

fn fixture() -> Value {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/agents/agents-v1.json");
    serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
}

#[test]
fn parse_and_persona_match_python() {
    let doc = fixture();
    for (name, text) in doc["texts"].as_object().unwrap() {
        let p = parse_agent_md(text.as_str().unwrap()).unwrap();
        let want = &doc["parsed"][name];
        assert_eq!(p.agent_name, want["agent_name"].as_str().unwrap(), "{name}");
        assert_eq!(p.domain, want["domain"].as_str().unwrap(), "{name}");
        assert_eq!(p.personality, want["personality"].as_str().unwrap(), "{name}");
        assert_eq!(p.enabled, want["enabled"].as_bool().unwrap(), "{name}");
        assert_eq!(json!(p.prompts), want["prompts"], "{name}");
        for (stage, persona) in want["persona"].as_object().unwrap() {
            let stage = (stage != "None").then_some(stage.as_str());
            assert_eq!(persona_prompt(&p, stage), persona.as_str().unwrap(), "{name} {stage:?}");
        }
    }
}

#[test]
fn domain_selection_matches_python() {
    let doc = fixture();
    for case in doc["selection"].as_array().unwrap() {
        let catalog: Vec<FrozenAgent> = case["names"]
            .as_array()
            .unwrap()
            .iter()
            .map(|n| {
                let raw = doc["texts"][n.as_str().unwrap()].as_str().unwrap().to_owned();
                FrozenAgent { name: n.as_str().unwrap().into(), enabled: true, keywords: vec![], sha256: Sha256::digest(raw.as_bytes()).into(), raw_md: raw }
            })
            .collect();
        let agent = agent_for_domain(&catalog, case["domain"].as_str().unwrap());
        assert_eq!(agent.agent_name, case["agent_name"].as_str().unwrap(), "{case}");
        assert_eq!(persona_prompt(&agent, Some("visual")), case["persona_visual"].as_str().unwrap(), "{case}");
    }
    for case in doc["domains"].as_array().unwrap() {
        assert_eq!(screening_domain(case["screening"].as_str().unwrap(), case["paper_domain"].as_str()), case["output"].as_str().unwrap(), "{case}");
    }
}

#[test]
fn reader_profile_and_chain_instruction_match_python() {
    let doc = fixture();
    for case in doc["profiles"].as_array().unwrap() {
        let a = &case["args"];
        let areas: Vec<String> = a[0].as_array().unwrap().iter().map(|v| v.as_str().unwrap().to_owned()).collect();
        let got = reader_profile_block(&areas, a[1].as_str().unwrap(), a[2].as_str().unwrap(), a[3].as_str().unwrap(), a[4].as_str().unwrap());
        assert_eq!(got, case["output"].as_str().unwrap(), "{case}");
    }
    for case in doc["chains"].as_array().unwrap() {
        let a = &case["args"];
        let focus = (!a[2].is_null()).then_some(&a[2]);
        let got = chain_system_instruction(a[0].as_str().unwrap(), a[1].as_str().unwrap(), focus, a[3].as_str().unwrap(), a[4].as_str().unwrap());
        assert_eq!(got, case["output"].as_str().unwrap(), "{case}");
    }
    for case in doc["areas"].as_array().unwrap() {
        let raw = case["input"].as_str().unwrap_or("");
        assert_eq!(json!(parse_research_areas(raw)), case["output"], "{case}");
    }
}
