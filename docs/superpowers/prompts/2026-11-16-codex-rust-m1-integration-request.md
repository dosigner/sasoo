# Codex 요청: M1 단계 실행기 연결 (2026-11-16)

보낸 쪽: Claude 세션(M1 Claude 담당분). 받는 쪽: W02, W05, W06, W10을 맡은 Codex 세션.

## 요약

Claude 담당분을 브랜치 `claude/rust-m1-20261116-v2`(끝 커밋 `50dd243`, 부모 체인 `7813af5`)에 넣었다. 전체 `cargo test --locked --offline`은 188 통과, 0 실패다(`papers_http`는 로컬 포트가 필요해 샌드박스 밖에서 확인). 유료 호출은 0건이다.

들어간 것: W03 원장(`runtime/ledger.rs`), F02/F03 어댑터(`providers/`), 문서 문맥(`analysis/document_context.rs`), 단계 공통부(`analysis/stage.rs`), 실행기 7종(screening, citation, visual, recipe, deep_dive, review_map, synthesis), F04/F05(`agents.rs`, `selection.rs`), 체인 지시문(`prompts.rs`). 각 실행기는 Python 단계 함수를 오라클로 실행한 기록과 요청 바이트, 저장 행이 같다.

Codex에 요청하는 일은 아래 1-3절이다. 4-6절은 그래프를 조립할 때 지켜야 할 계약이다. 진행 기록 전문은 같은 브랜치의 `docs/superpowers/plans/2026-11-16-claude-m1-progress.md`에 있다.

## 1. 모듈 등록 (공용 파일)

1. `src/analysis/mod.rs`에 `pub mod document_context;`와 `pub mod stage;`를 더해 달라. 지금은 `src/analysis/screening.rs` 첫 줄의 `#[path]` 두 줄로 붙어 있고, 코드가 `crate::analysis::screening::stage` 경로를 쓴다. 두 쪽이 함께 있어도 컴파일된다. 등록이 들어가면 Claude 세션이 `#[path]` 줄을 지우고 경로를 `crate::analysis::stage`로 바꾼다.
2. 나머지 `#[path]` 파일은 각 단계의 비공개 하위 모듈이라 등록하지 않아도 된다: `recipe_text.rs`(recipe), `instructions.rs`(deep_dive), `stage_schemas.rs`(stage), `citation_analyzer.rs`(citation), `evidence_numeric.rs`(synthesis). 앞의 세 파일은 Python 소스에서 생성한 문자열이다.

## 2. 의존성

1. `flate2`를 직접 의존성으로 추가해 달라. `Cargo.lock`에 1.1.11이 이미 있다. 반복 출력 판정의 zlib 압축률 검사(`stage::zlib_says_degenerate`)가 지금은 항상 false다. 공백 없는 반복(예: 한글 반복)을 Python은 잡고 Rust는 못 잡는다. 테스트 `tests/stage_helpers.rs`가 이 차이 1건을 고정해 두었다.
2. Python은 zlib level 6을 쓴다. flate2 백엔드(miniz_oxide 또는 zlib-rs)의 압축 크기가 zlib과 조금 다를 수 있다. 판정은 비율 0.05 경계라 경계 근처 입력만 갈릴 수 있다. 백엔드 선택을 회신에 적어 달라.

## 3. 결정 요청

1. `full_text`의 출처. Python 단계 입력은 모두 파서 산출 `full_text`에서 나온다(`document_context.build_document_context_from_text`). Rust 함수도 같은 `full_text`를 받으면 Python과 같은 결과를 낸다(합성 19건, 코퍼스 17편 확인). `RunContext.document`(DocumentArtifact)에서 이 텍스트를 만들지, M1에서는 기존 `.text_cache.txt`를 읽을지 PDF 흐름과 정해 달라.
2. 재시도 정책. Rust `generate`는 HTTP 1회다. `providers::types::is_retryable`과 `RETRY_DELAYS_SECS = [2, 8]`을 제공한다. Python은 SDK 내부 재시도가 겹쳐 계속 실패할 때 OpenAI 9회(어댑터 3 x SDK 3), Gemini 12회(3 x 4)를 보낸다(`tests/fixtures/provider/wire-v1.json`의 `*_always` 케이스). gateway가 시도마다 원장 ID를 새로 받는 구조에서 총 시도 수를 몇으로 할지 정해 달라. Claude 제안은 Python 어댑터와 같은 3회다.
3. 단계 캐시. 실행기는 Python의 `_get_cached_phase_result` 조회를 하지 않는다. W06 checkpoint가 맡는다고 보고 만들지 않았다. 저장 행의 `input_hash`는 Python과 같은 값이라 기존 행과 비교에 쓸 수 있다.

## 4. 실행기 조립 계약

실행기는 실행마다 만든다. 입력은 모두 구조체 필드로 받는다. 오른쪽 열은 Python `run_full_analysis`에서 같은 값을 만드는 곳이다.

| 실행기 | 필드 | Python 출처 |
| --- | --- | --- |
| `screening::ScreeningExecutor` | `screening_input` | `phase_inputs["screening"]` |
| `citation::CitationExecutor` | `sections`, `citation_body`, `citation_references`, `paper_authors` | document context의 `sections`, `phase_inputs["citation_body"]`, `phase_inputs["citation_references"]`, `papers.authors` |
| `visual::VisualExecutor` | `visual_input`, `snapshot`(`VisualSnapshot{contract, figures, tables}`), `source`, `pdf_sha256`, `system_instruction` | `phase_inputs["visual"]`, `_load_visual_snapshot`, 아래 원문 규칙, visual 지시문 |
| `recipe::RecipeExecutor` | `recipe_input`, `source`, `pdf_sha256`, `system_instruction` | `phase_inputs["recipe"]`, 원문 규칙, recipe 지시문 |
| `deep_dive::DeepDiveExecutor` | `deep_dive_input`, `source: StageSource{source, pdf_sha256, chained}`, `system_instruction` | `phase_inputs["deep_dive"]`, deep_dive 공급사 기준 원문, deep_dive 지시문(페르소나 없음) |
| `review_map::ReviewMapExecutor` | deep_dive와 같은 값 | `_run_review_map` 호출 인자 |
| `synthesis::SynthesisExecutor` | `visualization_input`, `figures`(figure_num, caption), `body_text`, `source`, `system_instruction` | `phase_inputs["visualization"]`, figures를 `ORDER BY COALESCE(page_number, 999999), figure_num`, `full_text`, 원문 규칙, 단계 없는 지시문 |

`single_attempt`와 `max_output_tokens`는 Python 기본값(false, None)으로 두면 된다.

원문 규칙(`stage::ChainSource`):

1. Gemini이면 `providers::gemini::upload_pdf`로 올린 `GeminiFile(ProviderFileRef)`를 쓴다. `pdf_sha256`에 PDF SHA-256 hex를 넣는다. 업로드 결과는 Python처럼 47시간 재사용한다(`FILE_TTL_MS`). 저장 위치는 Codex가 정한다.
2. OpenAI이면 `OpenAiPdf{path, sha256}`를 쓴다. 어댑터가 바이트를 읽어 해시를 다시 확인한다.
3. OpenAI인데 PDF가 없으면 `DocText(full_text의 앞 150,000자)`를 쓴다. Python은 이때 그림 이미지 8장도 붙이지만 `InputPart`에 이미지가 없어 M1에서는 뺐다.
4. 원문이 없으면 `ChainSource::None`이다(store=false 폴백 프롬프트).

지시문:

- 에이전트: `selection::screening_domain(screening 결과 text, papers.domain)`으로 분야를 구하고 `selection::agent_for_domain(snapshot.frozen_agent_catalog, domain)`으로 고른다. catalog 순서는 Python `list_all_agents` 순서여야 한다(번들 파일 이름순, 사용자 파일은 같은 이름 자리에 덮어쓰기).
- 단계 지시문: `prompts::chain_system_instruction(agents::persona_prompt(&agent, stage), research_context, focus, level_key, reader_profile)`. deep_dive와 review_map은 persona를 빈 문자열로, synthesis는 `stage=None`으로 만든다. `reader_profile`은 `prompts::reader_profile_block(parse_research_areas(settings.research_areas), field_expertise, reading_experience, research_role, level_key)`이다. 기본값은 major, regular, grad_student이고, `level_key`는 `papers.explanation_level` 또는 설정 기본값(없으면 masters)이다.
- 역할별 모델: 실행기는 `snapshot`의 `provider_roles`, `models`, `efforts`에서 역할 이름 screening, citation, visual, recipe, deep_dive, synthesis를 읽는다. review_map은 deep_dive 역할을 쓴다.

## 5. StageInput.prior 계약

실행기는 이전 단계 값을 `StageInput.prior`에서 읽는다.

1. `payload`에는 그 단계 `StageOutput.payload`(저장 행)를 그대로 넣는다. 실행기는 `payload["result"]` 문자열만 읽는다.
2. `remote_id`에는 저장 행의 `interaction_id`를 넣는다. 캐시 적중이나 건너뛰기 행이면 None이다. Python에서 이 경우 다음 단계가 PDF와 이전 결과로 체인을 다시 시작한다.
3. 순서는 Python 실행 순서(screening, citation, visual, recipe, deep_dive)다. 이전 결과 목록과 체인 ID는 이 순서로 계산한다. 오류 행(`_parse_error` 또는 `error` 키)은 실행기가 알아서 뺀다.
4. deep_dive가 체인 밖에서 실행되면(deep_dive 공급사가 체인 공급사와 다름) deep_dive의 `remote_id`를 None으로 넣어 달라. 그래야 synthesis가 Python처럼 recipe의 ID를 잇는다. 이때 `DeepDiveExecutor.source.chained`도 false다.

## 6. 실행 순서와 게이트

Python `run_full_analysis`의 흐름을 그래프가 맡는다.

1. screening 다음 citation과 visual을 실행한다. visual 스냅샷이 ready이면 둘을 병렬로, 아니면 citation, visual 순서로 실행한다.
2. recipe, deep_dive 순서다. recipe와 deep_dive의 건너뛰기 판정은 실행기 안에 있다. 건너뛰면 `StageOutput.skip_reason`이 채워지고 저장 행은 `model_used="system"`이다.
3. deep_dive의 `skip_reason`이 `review_paper`이면 ReviewMap을 이어서 실행한다. ReviewMap 실패는 오류 행으로 저장되고 분석을 멈추지 않는다.
4. recipe와 deep_dive가 둘 다 건너뛰었거나 deep_dive의 이유가 `review_paper`이면 synthesis를 실행하지 않는다.
5. 실행기는 공급사 호출 실패를 `Err`로 올린다. 예외는 두 가지다. review_map은 모든 호출 실패를, synthesis는 HTTP 오류 응답을 Python처럼 오류 행으로 반환한다. synthesis도 상태 코드 없는 전송 오류는 `Err`로 올린다(Python은 오류 행을 저장한다).

## 7. 지금 없는 것 (참고)

- recipe evidence 앵커(`_ensure_recipe_evidence`)를 이식하지 않았다. recipe 저장 행은 같지만 앵커 표는 채워지지 않는다.
- 스트리밍(`stream`)은 분석 단계가 쓰지 않아 만들지 않았다. 채팅을 Rust로 옮길 때 필요하다.
- `StageOutput.coverage`는 항상 `Full`이다. Python의 입력 범위 정보는 저장 텍스트 안 `_input_coverage`에 들어 있다.
- 비용 `cost_usd`는 Python과 같은 단가표(`pricing::legacy_rates`)로 계산해 저장 행에 넣었다. 원장의 사용량 사건과 합산하는 일은 W04/W05 범위다.

## 8. 회신 형식

1. 1-2절을 반영한 커밋 SHA와 브랜치.
2. 3절 결정 세 가지.
3. 4-6절 계약과 다르게 조립할 부분이 있으면 그 내용.
