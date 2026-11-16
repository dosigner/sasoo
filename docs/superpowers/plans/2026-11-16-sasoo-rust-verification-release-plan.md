# Sasoo Rust 백엔드 검증과 배포 계획

작성일: 2026-11-16. 상위 문서: [Rust 백엔드 구현 계획](2026-11-14-sasoo-rust-backend-implementation-plan.md)(이하 "구현 계획").

구현 계획에는 이미 다음 내용이 있습니다.
- 검증 층 구분(§8)
- 설치본 acceptance(D01-D05)
- 전환과 rollback 절차(§9)

이 문서는 구현 계획에 없는 네 가지를 정합니다.
1. PR마다 도는 CI 관문
2. Python과 Rust를 같은 입력으로 비교하는 방법
3. 사용자에게 내보내는 릴리스 단계
4. Python 기능 개발과 Rust 이식의 속도 맞추기

## 1. 결론

검증은 네 관문(G1-G4)으로 나눕니다. 아래 관문을 통과해야 위 관문으로 갑니다.

| 관문 | 언제 | 무엇을 확인 | 증거의 범위 |
| --- | --- | --- | --- |
| G1. PR CI | 모든 PR | fmt, clippy, `cargo test`, 계약 fixture와 Python 원본의 일치 | 결정적 로직과 저장된 계약 |
| G2. 차등 비교 | 야간 또는 수동 | 같은 요청과 같은 저장 응답을 Python과 Rust에 주고 결과를 비교 | HTTP와 저장 결과의 동등성 |
| G3. 설치본 acceptance | 릴리스 후보마다 | 구현 계획 D04, D05 | 실제 target의 화면, 설치, upgrade |
| G4. 베타 실사용 | 베타 채널 한 주기 이상 | 실제 라이브러리에서 오류율, 완료율, 비용 미확인 건수 | 실제 사용 환경 |

배포는 설치 단위로 전환합니다. 라우트 단위로 조금씩 옮기는 방식(strangler)은 쓸 수 없습니다. 구현 계획 §1 제약에 따라 하나의 live DB에는 schema와 queue 소유자가 하나만 있어야 하기 때문입니다. 그래서 한 앱에 두 백엔드를 함께 넣고, 재시작할 때 명시적으로 고르게 합니다. 릴리스 단계는 내부 빌드, 베타 채널, 기본값 전환, Python 제거 순서입니다.

## 2. 현재 상태 (2026-11-16 확인)

| 항목 | 상태 | 근거 |
| --- | --- | --- |
| Rust 코드 | git 미추적. CI가 테스트할 수 없음 | `git status` |
| CI | Rust job 없음. `build-check.yml`은 windows-latest 한 job | `.github/workflows/build-check.yml` |
| 릴리스 | `release.yml`이 macos-15와 windows-latest에서 빌드 | 구현 계획 §9 |
| toolchain | `rust-toolchain.toml` 없음. `Cargo.toml`은 `rust-version = "1.92"`, edition 2024. 로컬 rustc 1.94.1 | 파일 확인 |
| 로컬 도구 | rustfmt, clippy 미설치. fmt와 clippy 상태는 미확인 | `rustup component list --installed` |
| 테스트 | `cargo test` 87건 통과(2026-11-14 실행) | 이전 세션 실행 결과 |
| 크기 | Rust debug 바이너리 5.8 MB(PDF 엔진 없음). Python 번들 `backend/dist` 404 MB | `du -sh` |
| 자동 업데이트 | electron-builder GitHub provider. channel, prerelease 설정 없음 | `package.json` `build.publish`, `electron/*.ts` |
| 저장소 | public | `gh repo view` |
| 미구현 | worker 실행, 분석 오케스트레이션, PDF 추출 | 구현 계획 §1 표 |

## 3. G1: PR CI

### 추가할 것

1. `sasoo/backend-rust/rust-toolchain.toml`을 만듭니다. 정확한 버전(예: `1.94.1`)과 `rustfmt`, `clippy` component를 고정합니다. `rust-version = "1.92"`는 최소 지원 버전으로 그대로 둡니다.
2. `build-check.yml`에 `rust` job을 추가합니다. matrix는 `macos-15`(aarch64-apple-darwin)와 `windows-latest`(x86_64-pc-windows-msvc)입니다. 구현 계획 D02의 두 target과 같습니다.
3. job의 단계는 다음과 같습니다.
   - `cargo fmt --check`
   - `cargo clippy --locked --all-targets -- -D warnings`
   - `cargo test --locked`
   - `cargo deny check advisories licenses`
4. 빌드 캐시 action은 commit SHA로 고정합니다(제3자 action).
5. 계약 drift 검사를 기존 Python job에 추가합니다: `python scripts/export-rust-contracts.py --verify --output-root contract-fixtures/rust-backend-v2`.

`cargo deny`의 license 검사는 PDF 엔진 후보(Xberg, ORT 모델)를 들일 때 필요합니다. 구현 계획 P05의 자원 고정과 같은 목적입니다.

### drift 검사의 효과와 비용

drift 검사가 있으면, 고정된 계약을 바꾸는 Python PR은 fixture를 다시 만들기 전까지 실패합니다. 그래서 Python 변경이 Rust 이식 목록에서 빠지지 않습니다.

비용도 있습니다. 지금 fixture는 `api.ts`, `analysis_routes.py` 같은 원본 파일 전체의 sha256을 담습니다. 그래서 계약과 관계없는 수정에도 검사가 실패합니다. 2026-11-14 작업에서도 테스트 파일 경로 한 줄을 바꾸자 SSE fixture가 맞지 않게 되었습니다.

선택지는 두 가지입니다.

1. 스키마, OpenAPI, 완료 판정처럼 의미가 바뀌는 계약은 실패로, 원본 파일 해시 차이는 경고로 둡니다(추천). exporter가 두 종류를 나눠 보고할 수 있는지는 아직 확인하지 않았습니다. 나눌 수 없으면 exporter를 고쳐야 합니다.
2. 모든 차이를 실패로 둡니다. 가장 엄격하지만 Python PR마다 fixture를 다시 캡처해야 합니다.

### 완료 조건

두 runner에서 `rust` job이 통과하고, 첫 실행 시간을 기록합니다. 저장소가 public이므로 GitHub 호스트 runner 시간에 따른 비용은 생기지 않는다고 판단합니다. 요금 정책은 실행 전에 다시 확인해야 합니다.

## 4. G2: 차등 비교

### 방법

1. 입력: 라이브러리 복사본의 논문 묶음입니다. Review 51번, Article 45번과 48번을 포함하고, Letter가 생기면 추가합니다.
2. 공급사 응답: Python 실행에서 저장한 응답(cassette)을 씁니다. 같은 응답을 Rust 공급사 adapter에 넣습니다(구현 계획 F 묶음의 "저장 응답"). 비교 과정에서 유료 호출은 0건입니다.
3. 실행: `scripts/rust-contract-harness.py`에는 Python 동작을 기록하는 capture 모드가 이미 있습니다(`--app-data-root`, `--deny-network`). 여기에 compare 모드를 추가합니다. 같은 요청을 Rust 서버에 보내고 응답을 정규화해 비교합니다. 정규화 대상은 시각, 무작위 ID, 문서에 순서 무관으로 정한 배열입니다.
4. 비교 대상: HTTP 응답, `analysis_results` 행, `completion_checks`, 비용 원장, 생성 파일의 해시입니다.
5. 의도한 개선은 허용 목록에 이유와 함께 적습니다. 예를 들어 Gemini 사용량 미확인을 0 대신 `None`으로 두는 것은 PR #138에서 Python도 바뀌었으므로 차이가 아닙니다.

### 실행 시점

PR마다 돌리지 않고 야간 또는 수동으로 돌립니다. 논문 여러 편의 전체 분석을 다시 재생하므로 시간이 깁니다. 시간은 첫 실행에서 측정합니다.

### 시작 조건

Rust에 HTTP handler가 연결되어야 합니다(구현 계획 A04-A06). 분석 결과 비교는 worker와 F 묶음이 연결된 뒤에 할 수 있습니다(W10, F01 이후).

### 완료 조건

허용 목록에 없는 차이가 0건입니다.

## 5. 릴리스 단계

| 단계 | 사용자에게 보이는 것 | 백엔드 선택 | 들어갈 조건 | 되돌리기 |
| --- | --- | --- | --- | --- |
| 0. 저장소만 | 없음 | Python | Rust 코드 커밋, G1 통과 | 해당 없음 |
| 1. 내부 빌드 | 없음 | 환경 변수(예: `SASOO_BACKEND=rust`)로만 Rust. 설정 화면 없음 | D01 launcher 선택, G2에서 읽기와 설정 경로 통과 | 환경 변수 제거 |
| 2. 베타 채널 | prerelease 버전(예: `1.5.0-beta.1`)과 설정의 "Rust 백엔드 사용(재시작 필요)" | 사용자가 opt-in | G2 전체 통과, G3 통과 | 구현 계획 D03 rollback |
| 3. 기본값 전환 | 정식 릴리스. 설정에 "Python 백엔드로 실행" 유지 | 기본 Rust, Python 선택 가능 | G4에서 오류율과 완료율이 Python 기준 이하 | 설정에서 Python 선택 + D03 |
| 4. Python 제거 | 번들이 작아짐 | Rust만 | Python 실행 의존성 0(PDF helper 포함, 구현 계획 P03, D02) | 이전 버전 설치 + D03 |

각 단계는 릴리스 하나 이상을 유지합니다.

### 단계 공통 규칙

1. 조용한 자동 fallback은 없습니다(구현 계획 D01). Rust가 시작하지 못하면 오류를 보여 주고, 사용자가 고릅니다.
2. 백엔드는 앱을 재시작할 때만 바꿉니다. 바꾸기 전에 구현 계획 §9의 3번(SQLite Online Backup으로 snapshot)을 자동으로 실행합니다.
3. Rust가 schema migration을 하면, 구버전이 그 DB를 읽을 수 있는지 A02, D03에서 확인합니다. 읽을 수 없으면 되돌리기는 snapshot 복원뿐입니다. 이 경우 베타 안내에 그 사실을 적습니다.
4. 단계 1-3에서는 번들에 두 백엔드가 함께 들어갑니다. 크기는 Python 404 MB에 Rust 바이너리와 PDF 자원이 더해집니다. Rust 쪽 크기는 PDF 엔진이 정해진 뒤 측정합니다.

### 베타 채널 구현 전 확인

electron-updater의 prerelease와 channel 동작(`allowPrerelease`, 채널별 `*.yml`)은 버전마다 다를 수 있습니다. 구현 전에 설치된 electron-builder와 electron-updater 버전의 공식 문서를 다시 읽어야 합니다. 지금 앱에는 이 설정이 없습니다. 그래서 베타 사용자를 다시 정식 채널로 돌리는 경로도 같이 확인해야 합니다.

## 6. Python 기능 개발과 이식 속도

문제는 Python 쪽에 기능이 계속 들어오면서 Rust 이식 목록이 늘어난다는 점입니다. 2026-11-14 Review 논문 모드(PR #137)와 2026-11-16 사용량 미확인 처리(PR #138)가 이미 구현 계획 작성 뒤에 들어왔습니다.

선택지는 세 가지입니다.

1. Python 기능을 계속 개발하고, drift 검사와 이식 대기 목록으로 추적합니다(추천). 제품 개발은 멈추지 않습니다. 대신 Rust가 따라잡아야 할 목록이 계속 생깁니다.
2. 이식 기간에 Python은 버그 수정만 받습니다. 이식은 빠르지만 그동안 기능 개발이 멈춥니다.
3. Python 기능을 먼저 안정시킨 뒤 이식을 시작합니다. 이식 시작이 늦어집니다.

1번을 고르면 구현 계획 F 묶음에 "이식 대기 목록"을 두고 다음을 넣습니다.

| 항목 | Python 위치 | 지켜야 할 계약 |
| --- | --- | --- |
| Review 논문 모드 | `analysis_execution.py`, `analysis_completion.py` | `paper_type` 비필수, deep_dive skip 이유 `review_paper`, `STAGE_OUTPUTS` 인덱스 7, Review면 synthesis와 시각화 생략 |
| 사용량 미확인 | `gemini_client.py`, `openai_client.py`, `api.ts` | 사용량 부재는 `None`, `usage_complete`, `incomplete_reason`. 0으로 채우지 않음 |
| 빈 그림 설명 | `figure_service.py` | JSON 추출 뒤 빈 설명은 502와 `_usage` |
| pipeline 세마포어 | `gemini_client.py` | 실제 작업이 끝날 때 반납 |

## 7. 착수 순서

1. Rust 코드와 fixture v2를 커밋합니다([후속 계획](2026-11-16-sasoo-review-followup-and-rust-prep-plan.md) 3단계). 코드가 저장소에 없으면 CI가 테스트할 수 없습니다.
2. `rust-toolchain.toml`과 CI `rust` job(fmt, clippy, test)을 추가합니다. 첫 실행에서 fmt와 clippy 오류가 나오면 같은 PR에서 고칩니다.
3. drift 검사를 Python job에 추가합니다. 3절의 선택지를 먼저 정합니다.
4. `cargo deny`를 추가합니다.
5. Rust HTTP handler가 연결되면(A04-A06) harness에 compare 모드를 추가합니다(G2).
6. 환경 변수로만 Rust를 고르는 launcher를 만듭니다(D01, 릴리스 단계 1).
7. W10, F 묶음, D04가 끝나면 베타 채널을 준비합니다(릴리스 단계 2).

## 8. 정해야 할 것

1. drift 검사의 강도: 의미 계약만 실패(추천)와 모든 차이 실패 중 하나
2. Python 기능 개발 정책: 6절의 1, 2, 3 중 하나
3. toolchain 고정 버전: 로컬과 같은 1.94.1(추천) 또는 다른 버전
4. 베타 채널 운영 여부와 G4 통과 기준(사용자 수, 분석한 논문 수, 기간)

## 9. 미검증 항목

- 현재 Rust 코드의 fmt, clippy 상태(로컬에 component 없음)
- `cargo test`의 Windows 통과 여부(macOS에서만 실행)
- CI `rust` job의 실행 시간
- exporter가 의미 계약과 원본 해시 차이를 나눠 보고할 수 있는지
- electron-updater의 prerelease, channel 동작(현재 버전 문서 미확인)
- PDF 엔진을 넣은 뒤의 Rust 번들 크기
