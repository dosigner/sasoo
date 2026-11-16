# Rust M1 Claude 담당분 진행 기록 (2026-11-16)

승인된 계획: `/Users/dongj/.claude/plans/eager-dancing-cupcake.md`. 기준 커밋 `7813af5`(Codex 계약), 브랜치 `claude/rust-m1-20261116-v2`(origin에 push됨).

## 끝난 것

1. W03 원장 `runtime/ledger.rs`, 테스트 `tests/ledger.rs` 9건. 커밋 `b8d517f`.
2. F02/F03 `providers/openai.rs`, `gemini.rs`, `transport.rs`(reqwest), `types.rs` 도우미. 오라클 `tests/provider_wire_oracle.py`가 Python 어댑터를 가로챈 httpx/httpx2로 실행해 `tests/fixtures/provider/wire-v1.json`(21케이스 + 업로드)을 만든다. 테스트 `tests/provider_wire.rs` 6건. 커밋 `ccb23d9`.
3. 단계 공통 도우미 `analysis/stage.rs`(오라클 `tests/stage_helpers_oracle.py`, fixture `tests/fixtures/stage/helpers-v1.json`, 테스트 `tests/stage_helpers.rs`). 미커밋.
4. screening 실행기 `analysis/screening.rs`(오라클 `tests/stage_oracle.py`, fixture `stages-v1.json`, 테스트 `tests/stage_screening.rs` 16케이스 일치). 미커밋.

## 진행 중 (백그라운드 에이전트)

- `analysis/document_context.rs`: document_context.py + section_splitter.py 이식, 테스트 `tests/document_context.rs`, 코퍼스 대조는 `SASOO_M1_CORPUS_ORACLE`.
- `analysis/citation.rs`: citation_analyzer.py + `_run_citation` 이식, 테스트 `tests/stage_citation.rs`.

## 남은 것

1. `_run_chain_stage` 이식 후 visual, recipe(+evidence), deep_dive(+summary_contract), review_map, synthesis(+evidence_verifier 수치).
2. F04 agent .md 파서와 F05 domain 선택, persona, reader profile, chain system instruction.
3. 응답 기록(유료, 사용자 승인 필요).

## Codex 요청 목록 (PR 설명에 넣는다)

1. `analysis/mod.rs`에 `document_context`, `stage` 등록. 지금은 `screening.rs`의 `#[path]` 두 줄로 붙어 있다. 등록 후 그 두 줄을 지운다.
2. `flate2`를 직접 의존성으로 추가(이미 Cargo.lock에 1.1.11). 반복 출력 zlib 검사(`stage::zlib_says_degenerate`)가 지금은 false 고정이다.
3. 실행기 입력 경로: 실행기는 단계별 입력(phase_inputs 등)을 구조체 필드로 받는다. 실행마다 `PipelineDeps`를 조립하는 쪽이 document context에서 채운다. `RunContext.document`(DocumentArtifact)에서 Python과 같은 `full_text`를 얻는 방법은 PDF 흐름과 정해야 한다.
4. gateway 재시도: Python 실효 시도 횟수는 OpenAI 9회(어댑터 3 x SDK 3), Gemini 12회(3 x 4). Rust `generate`는 1회 시도이고 `is_retryable`, `RETRY_DELAYS_SECS`를 제공한다.

## 알려진 차이

- `json.loads` NaN/Infinity, `json.JSONDecodeError` 메시지 문자열(screening의 재시도 후 무효 JSON 경로)은 Rust가 다르게 적는다.
- 스트리밍(`stream`)은 M1 분석 단계가 쓰지 않아 구현하지 않았다.
- OpenAI 이미지 입력(PDF 없을 때 visual 그림 8장)은 `InputPart`에 없다.

## 실행 메모

- 테스트: `cd sasoo/backend-rust && CARGO_TARGET_DIR=$TMPDIR/sasoo-m1-target cargo test --locked --offline`. `papers_http`는 로컬 포트 바인딩이 필요해 샌드박스 밖에서 돈다. Python 호환 테스트는 미추적 링크 `sasoo/backend/.venv` -> 공유 작업공간 venv를 쓴다.
- 코퍼스 사본: `/Users/dongj/dev/sasoo-m1-corpus/review-run/library`(원본 `/tmp/claude-501/review-run`). 논문 본문은 저장소에 넣지 않는다.
