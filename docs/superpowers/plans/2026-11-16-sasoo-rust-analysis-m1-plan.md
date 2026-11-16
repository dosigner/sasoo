# Rust 분석 실행 첫 목표(M1): 논문 1편을 Rust로 끝까지 분석

작성 2026-11-16. 기준 계획은 [Rust 구현 계획](2026-11-14-sasoo-rust-backend-implementation-plan.md)의 52개 과제다. 이 문서는 그중 "Rust로 분석이 실제로 도는 상태"에 꼭 필요한 과제만 골라 순서와 분담을 정한다. 기준 계획의 과제 정의, 완료 기준, 복구 규칙은 그대로 따른다.

## 1. 왜 이 문서가 필요한가

2026-11-16 측정에서 Rust로 실제 동작하는 Python 함수는 731개 중 3개다(전환율 차트 (로컬 이력 자료: `../../validation/2026-11-16-sasoo-rust-conversion-waterfall.html`)). 업로드와 분석 API는 501이다. 개발자 실사용(G4, 2주 동안 10편)을 하려면 Rust가 분석을 실행해야 한다. 기준 계획의 52개를 순서대로 다 하면 분석이 도는 시점이 가장 마지막 묶음 근처가 된다. 그래서 분석이 처음 도는 가장 짧은 경로를 먼저 정한다.

## 2. M1 완료 기준

1. 격리 root의 라이브러리 사본에서 G4 논문 10편(5절)을 Rust `/run`으로 분석한다.
2. 각 편의 완료 판정(`completion_checks`)이 Python과 같은 단계 집합에서 completed 또는 skipped다. Review는 review_map, Article과 Letter는 deep_dive와 synthesis가 completed다.
3. 기록한 공급사 응답을 재생하는 모드에서, Rust가 저장한 단계 결과가 Python 기준 결과와 의미 계약(스키마, 필수 필드, skip 이유, 비용과 unknown)에서 같다. LLM 원문이 매번 달라지는 실제 호출 모드는 구조만 비교한다.
4. Electron 기본 백엔드는 바꾸지 않는다. 운영 DB와 사용자 라이브러리는 열지 않는다.

## 3. M1에 넣는 과제와 빼는 과제

| 구분 | 과제 | 이유 |
| --- | --- | --- |
| PDF | 이미 구현된 Rust 추출(`pdf-xberg-native`, profile `text-layer-v2` (`native_options()`))을 격리 모드에서 사용. 분석 입력이 이 추출로 부족하면 P06(기존 Python 추출을 별도 프로세스로 호출)을 대안으로 둔다 | 2026-11-16 15:40 Rust PDF 보고서 (로컬 이력 자료: `../../validation/rust-pdf-native-20261116-151611/REPORT.md`): 논문 3편 81쪽 실행, 운영 채택(P02/P03)은 미완료. 읽기 순서 수정은 현재 기준 소스에 포함돼 있고 native_options()의 v2 identity로 검증했다. 처음 이 문서는 Rust PDF 추출이 없다고 보고 P06을 기본으로 정했으나 사실과 달랐다 |
| 실행부 | W02 claim과 spawn, W03 요청과 사용량 원장, W05 staging과 공개, W06 완료 판정과 단계 graph, W10 `/run`, status, results | 분석 1회를 안전하게 저장하는 최소 집합 |
| 공급사 | F01 비용(일부 있음), F02 OpenAI, F03 Gemini | 사용자 결정(2026-11-16): 두 공급사를 모두 쓸 수 있어야 한다. Gemini 공식 SDK에 Rust는 없으므로(ai.google.dev/gemini-api/docs/libraries, 2026-11-16 확인) F02와 같이 HTTP를 직접 호출한다 |
| 분석 단계 | F04 agent와 profile, F05 screening, F16 citation, F17 visual, F06 recipe, F18 deep_dive, F19 synthesis, review_map | 화면의 요약, 인용, 그림과 표, 레시피, 심층 분석, 종합, 리뷰 지도 |
| 업로드 | P04 중 기존 논문 재분석에 필요한 부분만 | M1은 이미 라이브러리에 있는 논문으로 한다. 새 업로드는 M2 |

M2 이후로 미루는 과제: W04 예산과 동시 실행 제한, W07 취소와 삭제, W08 장애 복구, W09 종료 정리, F07과 F08 시각화와 이미지 생성(1편 비용의 81%, 2026-11-16 Letter 실측), F09-F12 채팅, 그림 설명, 실험 계획, 보고서, P02-P05 Rust PDF 엔진, D01-D05 설치본과 전환. W04, W07, W08은 사용자에게 내보내기 전에 반드시 필요하다. M1은 개발자 격리 환경 전용이므로 뒤로 미룬다.

## 4. 순서

1. 선행: 다른 세션의 Phase 16(Rust 그림 설명), Phase 17(Rust `GET /api/papers`) 완료. 그 뒤 `backend-rust`와 fixture를 git에 기준 커밋으로 넣고 SHA를 양쪽이 확인한다. 각 세션은 그 커밋에서 별도 브랜치와 worktree로 시작한다. 지금은 미추적 파일이라 두 세션이 나눠 작업하면 합칠 방법이 없다. Phase 16 합성 코어 gate와 Phase 17 실제 listener/readonly oracle gate는 완료했다. 새 기준 커밋의 현재 소스 검증과 보존 범위는 [M1 기준점 기록](../../validation/rust-backend/m1-baseline-20261116.md)을 따른다. 이 완료는 실제 SDK/전체 F10/기본 backend 전환을 뜻하지 않는다.
2. 공급사 응답 기록: 5절의 10편을 Python으로 OpenAI와 Gemini에서 각각 한 번씩 분석하면서 공급사 요청과 응답을 비밀 없이 HTTP 바이트로 기록한다. 이후 Rust 테스트는 이 기록을 재생하므로 비용이 들지 않는다. 이 단계만 유료 API를 쓴다. OpenAI 10편은 전 단계 약 $2-4, 시각화 이미지를 빼면 약 $0.4-0.6이다(2026-11-16 Letter 실측 $0.1882 중 이미지 $0.1525). Gemini 비용은 아직 재지 않았다.
3. 병렬 1차: 실행부 W02, W03, W05, W06과 PDF P06, 공급사 F02를 나눠서 진행한다(6절).
4. 단계 실행기: F04, F05, F16, F17, F06, F18, F19, review_map을 W06의 `run_phase`에 하나씩 연결한다. 단계마다 재생 모드로 Python 기준 결과와 비교한다.
5. W10으로 HTTP에 연결하고, 앱 화면을 Rust 서버에 붙여 10편을 분석한다. 실제 호출 모드는 마지막에 1-2편만 돌린다.

## 5. G4 논문 10편 (라이브러리 사본 `/tmp/claude-501/review-run/library` 기준)

| 번호 | 폴더 | 유형 | 쪽 |
| --- | --- | --- | --- |
| 1 | 2017_COMST_OpticalComm_optical_communications | Review | 41 |
| 2 | 2019_FourierSpaceDNN_optics (PRL) | Letter | 6 |
| 3 | 2022_SciRep_CoherentFsoLeo_optics | Article | 12 |
| 4 | OptFor_RefractiveMCAO_optics | Article | 19 |
| 5 | 2022_ApplOpt_PredictionNet_optics | Article | 8 |
| 6 | 2022_New_Generation_Free_Space_Optical_Commun_ca76571d (JLT) | Article | 10 |
| 7 | 2025_LSA_MetaSeeker_optics | Article | 13 |
| 8 | 2025_OptExpress_UplinkPrecomp_optics | Article | 12 |
| 9 | 2025_GR00TN1_ai_ml | Article(기술 보고서) | 36 |
| 10 | 2023_FlowMatching_ai_ml | Article | 28 |

유형은 screening 결과가 있는 1-4는 실측이고, 5-10은 PDF 메타데이터와 쪽수로 추정했다. 2단계에서 Python screening이 정한 값으로 고친다. 사본은 임시 폴더라 2단계 전에 고정 위치로 옮긴다.

## 6. 분담 (2026-11-16 합의)

이 표의 "Codex 세션"은 Phase 13-17을 맡은 Codex 세션이고, "Claude 세션"은 이 문서를 쓴 세션이다. Codex 세션은 Phase 16에서 실행 설정, 공개 경계(publication fence), 늦은 사용량 처리를 만들었고, 이 부분이 W02, W05, W06과 같은 계열이다. 분담은 Claude 세션이 제안했고 Codex 세션이 아래 예외 두 가지를 붙여 받아들였다.

| 담당 | 과제 | 주로 고치는 곳 |
| --- | --- | --- |
| Codex 세션 | W02, W05, W06, W10 | `src/runtime/`(`ledger.rs` 제외), `src/http/`, `src/analysis/{graph,completion}.rs` |
| Claude 세션 | 2단계 기록, W03, F02, F03, 단계 실행기(F04, F05, F06, F16-F19, review_map), 필요하면 P06 | `src/runtime/ledger.rs`, `src/providers/`, `src/analysis/`(`graph.rs`, `completion.rs` 제외), `src/pdf/legacy_helper.rs` |
| Codex 세션만 고치는 공용 파일 | `Cargo.toml`, `src/lib.rs`, 각 `mod.rs`, `src/storage/migrations.rs` | Claude 세션이 모듈 등록과 의존성 추가를 요청하면 Codex 세션이 반영한다 |

예외: `ledger.rs`는 runtime 폴더 안이지만 W03이라 Claude 세션이 맡는다. `graph.rs`와 `completion.rs`는 analysis 폴더 안이지만 W06이라 Codex 세션이 맡는다. `runtime/accept.rs`와 `analysis/config.rs`의 기존 W01 계약은 Codex가 통합하며 단계 실행기는 이를 재정의하지 않는다.

두 쪽의 경계는 기준 계획 4절의 `StageInput`, `StageOutput`, `ProviderOutcome`, `run_phase`다. Codex 세션이 이 계약과 모듈 등록 순서를 먼저 맞춘다. Claude 세션의 단계 실행기는 W06이 오기 전에는 이 인터페이스의 순수 함수로 만들고 재생 fixture로 시험한다. 작업은 각자 git 브랜치와 PR로 하고 main에 합친다.

Rust PDF 추출과 격리 업로드, 저장, 검색 연결은 세 번째 Codex 작업 흐름(2026-11-16 16:14 시작, PDF 인계 문서 기준)이 진행 중이다. 기준 커밋 이후에는 이 흐름도 별도 branch/worktree에서 변경하고, 공용 파일 수정은 Codex 담당 PR로 요청한다. 공유 checkout의 계속되는 수정은 이미 고정된 기준 소스에 자동 합치지 않는다.

## 7. 결정이 필요한 것

1. 6절 분담을 받아들였다. 공통 기준 커밋 SHA는 기준 PR의 head commit으로 고정하고 양쪽 branch는 같은 SHA에서 만든다.
2. 2단계의 유료 기록(약 $2-4)을 언제 할지.
3. (결정됨 2026-11-16) M1에 OpenAI와 Gemini를 모두 넣는다.

## 8. 확인하지 않은 것

- 각 과제의 작업 기간은 추정하지 않았다.
- P06이 Windows에서 Python helper를 찾는 방법은 확인하지 않았다(D02 범위).
- 5절 5-10번의 유형은 추정이다.

## 9. 병합 경계와 모듈 등록 순서

- Codex는 기존 `CommitScope`, `PublicationScope`, `StageVerdict`, `ConfigSnapshot`을 재사용한다. 별도 동명 타입이나 가변 config 복제본을 만들지 않는다.
- W03 소유자는 `providers/types.rs`의 `NewRequestSpec`, `RequestSpec`, `ProviderOutcome`, `UsageState`와 `runtime/ledger.rs`를 제공한다. `RequestScope`는 기존 `PublicationScope`의 alias이며 request ID 발급은 prepare_request 한곳이다.
- W06 소유자는 `RunContext`, `PipelineDeps`, `StageInput`, `StageOutput`, `Phase`, `CheckpointKey`를 먼저 작은 인터페이스 PR로 고정한다. 기존 계획 §4의 run_phase 계약을 유지하고 구체 필드/async 경계는 이 PR에서 컴파일 검증한다. 아직 없는 타입을 구현 완료로 간주하지 않는다.
- 등록 순서는 공통 타입과 graph 경계, W03/provider 타입과 ledger, 개별 단계, graph 실행, 마지막 W10 HTTP다. 각 소유자는 자기 파일만 변경하고 mod.rs/lib.rs/Cargo/migration 요청은 Codex PR에서 반영한다. 별도 worktree에서는 다른 세션의 미완성 파일에 의존해 main을 깨지 않는다.
- W10의 M1 범위는 격리 개발 모드의 run/status/results다. W04/W07/W08/W09가 미완료인 상태를 전체 W10 완료로 표시하지 않고 cancel/active DELETE/production guard를 임의로 연동하지 않는다.
- 공급사 기록의 예상 비용은 실행 승인이 아니다. 유료 기록과 실제 호출은 별도 명시 승인 전에는 수행하지 않는다. 새 runtime/model 설치와 사용자 원본 library 접근도 하지 않는다.

기준 커밋 주석: 위 로컬 이력 자료 경로는 원래 checkout에 보존된 과거 근거다. 이 최소 Rust/fixture 기준 커밋의 실행 의존성이 아니며 원문/논문 PDF/과거 runtime 산출물을 복사하지 않았다.
