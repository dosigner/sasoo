# Rust M1 Claude 담당분 진행 기록 (2026-11-16)

승인된 계획: `/Users/dongj/.claude/plans/eager-dancing-cupcake.md`. 기준 커밋 `7813af5`(Codex 계약), 브랜치 `claude/rust-m1-20261116-v2`(origin에 push됨).

## 끝난 것

1. W03 원장 `runtime/ledger.rs`, 테스트 `tests/ledger.rs` 9건. 커밋 `b8d517f`.
2. F02/F03 `providers/openai.rs`, `gemini.rs`, `transport.rs`(reqwest), `types.rs` 도우미. 오라클 `tests/provider_wire_oracle.py`가 Python 어댑터를 가로챈 httpx/httpx2로 실행해 `tests/fixtures/provider/wire-v1.json`(21케이스 + 업로드)을 만든다. 테스트 `tests/provider_wire.rs` 6건. 커밋 `ccb23d9`.
3. 문서 문맥 `analysis/document_context.rs`(합성 19건, 코퍼스 17편 일치), 단계 공통 도우미 `analysis/stage.rs`, screening, visual, recipe, deep_dive, review_map 실행기. 커밋 `146977c`.
4. F04/F05 `agents.rs`, `selection.rs`, 지시문 조립 `prompts.rs`. 커밋 `9dabe88`.
5. citation 실행기와 `citation_analyzer.rs`(32 단계 케이스). 커밋 `29b5b13`.
6. 재시도 후 무효 JSON의 `_parse_error`를 CPython 문구로 맞춤(`stage::json_error_message`).

## 진행 중 (백그라운드 에이전트)

- `analysis/synthesis.rs`: `_run_synthesis` + evidence_verifier 수치 비교 이식, 테스트 `tests/stage_synthesis.rs`.

## 남은 것

1. synthesis(에이전트 진행 중).
2. recipe evidence 앵커(`_ensure_recipe_evidence`)는 이식하지 않았다.
3. 응답 기록(유료, 사용자 승인 필요).

## Codex 요청 목록 (PR 설명에 넣는다)

1. `analysis/mod.rs`에 `document_context`, `stage` 등록. 지금은 `screening.rs`의 `#[path]` 두 줄로 붙어 있다. 등록 후 그 두 줄을 지운다.
2. `flate2`를 직접 의존성으로 추가(이미 Cargo.lock에 1.1.11). 반복 출력 zlib 검사(`stage::zlib_says_degenerate`)가 지금은 false 고정이다.
3. 실행기 입력 경로: 실행기는 단계별 입력(phase_inputs 등)을 구조체 필드로 받는다. 실행마다 `PipelineDeps`를 조립하는 쪽이 document context에서 채운다. `RunContext.document`(DocumentArtifact)에서 Python과 같은 `full_text`를 얻는 방법은 PDF 흐름과 정해야 한다.
4. gateway 재시도: Python 실효 시도 횟수는 OpenAI 9회(어댑터 3 x SDK 3), Gemini 12회(3 x 4). Rust `generate`는 1회 시도이고 `is_retryable`, `RETRY_DELAYS_SECS`를 제공한다.

## 알려진 차이

- `json.loads`가 받는 NaN/Infinity와 짝 없는 surrogate는 serde가 거부한다.
- 공급사 호출 자체가 실패할 때(HTTP 오류) Python은 SDK 예외 문구를 저장하고 Rust는 SasooError 문구를 저장한다(citation 실패 행).
- 문서 문맥 에이전트가 찾은 Python 쪽 이상 동작 3건(캡션 정규식 `{2}` 치환, `%` 뒤 `\b`, Materials and Methods 이중 매치)은 그대로 재현했다. Python 수정 후보다.
- 스트리밍(`stream`)은 M1 분석 단계가 쓰지 않아 구현하지 않았다.
- OpenAI 이미지 입력(PDF 없을 때 visual 그림 8장)은 `InputPart`에 없다.

## 실행 메모

- 테스트: `cd sasoo/backend-rust && CARGO_TARGET_DIR=$TMPDIR/sasoo-m1-target cargo test --locked --offline`. `papers_http`는 로컬 포트 바인딩이 필요해 샌드박스 밖에서 돈다. Python 호환 테스트는 미추적 링크 `sasoo/backend/.venv` -> 공유 작업공간 venv를 쓴다.
- 코퍼스 사본: `/Users/dongj/dev/sasoo-m1-corpus/review-run/library`(원본 `/tmp/claude-501/review-run`). 논문 본문은 저장소에 넣지 않는다.
