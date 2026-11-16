# Sasoo Rust backend implementation milestone

현재 이 crate는 Rust 이식을 위한 격리 구현 단계다. 기존 Electron/Python backend의 운영 선택은 유지하며, 분석과 사용자 자료 전환은 연결하지 않는다. 전체 실행 상태와 남은 과제는 [현재 기준점 기록](../../docs/validation/rust-backend/m1-baseline-20261116.md)에 기록한다.

## 확인된 경계

- CLI, health/asset HMAC, 인증/CORS, shutdown, docs/OpenAPI wire shell.
- 전용 thread와 bounded queue를 쓰는 SQLite handle, 단일 Rust owner, 합성 DB Online Backup/additive migration, 기존 Python reader/writer 호환 확인.
- 합성 credential store와 Python/Rust Fernet 상호 복호화, key epoch/CAS와 settings transaction.
- 유휴 paper/file service, 관측된 Range/HEAD/Unicode 파일 응답. 명시적인 synthetic root의 기본 HTTP 연결은 GET /api/papers만 제공한다. settings handler와 refresh adapter는 미연결.
- PDF 문서/좌표 모델, helper 응답의 source/engine/options 검증. 선택 기능 `pdf-xberg-native`를 켜면 명시적인 텍스트 추출 probe를 실행할 수 있음. 운영 채택은 미완료임.
- 불변 설정 snapshot과 원자 접수. FigureExplain은 identity/request/usage/spool/publication fence의 합성 코어 gate를 통과했다. 실제 FigureExplain HTTP/SDK와 분석 /run, claim/spawn은 미연결.
- 일부 Python JSON/cache/schema bytes와 Decimal 비용 순수 함수. 전체 phase input과 비용 원장은 미연결.

## 검증

저장소 루트에서 실행한다. Cargo.lock의 고정 crate를 준비한 뒤 전체 테스트는 offline으로 수행한다.

```bash
cargo test --locked --offline --manifest-path sasoo/backend-rust/Cargo.toml
```

루트 rust-toolchain.toml은 Rust 1.94.1을 고정한다. PDF probe 검증 target은 aarch64-apple-darwin이며 Windows 실행 검증은 남아 있다.

## 명시적인 PDF 텍스트 추출 probe

`xberg-native-pdf = 1.3.10`의 Rust 파서를 직접 호출한다. 외부 OCR/model/native runtime은 사용하지 않는다. 기존 Xberg 전체 profile과 배포 엔진 선택은 변경하지 않는다. 의존성 준비 후 실행은 offline으로 수행한다.

```bash
cargo test --locked --offline --manifest-path sasoo/backend-rust/Cargo.toml --features pdf-xberg-native
cargo run --locked --offline --manifest-path sasoo/backend-rust/Cargo.toml \
  --features pdf-xberg-native --example pdf_probe -- /absolute/input.pdf /absolute/new-output-version
```

새 출력 폴더에 document.json, page-text.json, full-text.txt, options.json, receipt.json을 저장한다. 기존 출력 폴더가 있으면 거절하며 라이브러리, DB, legacy sidecar를 갱신하지 않는다. options.json의 settings_bytes는 옵션 SHA-256을 재현하는 원본 바이트다. 라이브러리 호출자는 pdf::native::native_options()의 고정 엔진, revision, profile과 옵션 해시를 사용한다.

입력은 100 MiB, 페이지 수는 10000, 반환 텍스트는 64 MiB로 제한한다. 이 값은 probe의 방어 한계이며 측정한 운영 예산이 아니다. 단일 동기 실행 슬롯은 파서 반환까지 유지한다. 취소는 페이지 경계에서 확인하므로 진행 중인 파서 호출을 즉시 중단하거나 강제 종료하지 않는다. XBERG_NATIVE_PDF_MAX_DECOMPRESS_MB 환경 설정은 고정 profile과 충돌하므로 거절한다.

text-layer-v2는 같은 크기와 겹치는 X 범위의 인접 baseline을 한 줄로 X 정렬하던 결함을 수정한다. vendor/xberg-native-pdf의 MIT 원본, upstream revision, 파일별 SHA-256과 최소 patch를 보존하며 registry cache는 수정하지 않는다. engine.revision은 upstream 기반 revision이고 local patch의 SHA-256은 NATIVE_SETTINGS/options identity에 별도로 포함한다. ColumnAware라는 옵션명은 이 glyph-walk API의 내부 줄 정렬이 적용됐다는 증거가 아니므로 실제 assembly 경로를 identity에 기록한다. 전체 읽기 순서 품질, OCR, 검증된 bbox, 구조화된 표와 수식, figure asset과 bbox overlay는 미검증이다. 이전 v1 출력과 legacy sidecar는 유지한다.

## 격리된 PDF 업로드/검색 후보

P03 운영 채택과 P04 정식 공개를 완료한 상태가 아니다. 사용자가 명시적으로 선택한 새 synthetic root에서만 다음 경로를 실행한다. 기존 읽기 전용 경로와 Electron 기본 backend는 유지한다. 실제 사용자 library를 이 root로 지정하지 않는다.

```bash
cargo run --locked --offline --manifest-path sasoo/backend-rust/Cargo.toml --example pdf_candidate_fixture
# Use the newly printed root, and supply an ephemeral API token through the environment.
export SASOO_RUST_ISOLATED_ROOT=/absolute/new/synthetic/root
export SASOO_RUST_PDF_CANDIDATE=1
export SASOO_RUST_PDF_TIMEOUT_MS=30000 # Synthetic probe timeout, not an operating budget.
cargo run --locked --offline --manifest-path sasoo/backend-rust/Cargo.toml --features pdf-xberg-native -- --port 18773
```

SASOO_API_TOKEN이 필요하다. root에는 synthetic-only marker와 별도의 .sasoo-rust-pdf-candidate marker가 필요하며 example이 둘 다 생성한다. owner lock, 유휴 상태, 경로 containment를 확인한 뒤 기존 일관 백업 절차로 candidate catalog만 추가한다. token, marker, feature 또는 명시 선택이 없으면 쓰기 후보가 활성화되지 않는다.

- POST /api/papers/upload: 기존 file multipart. basename/확장자와 80자 stem 정리, 첫 1024 bytes의 PDF magic, 100 MiB 상한을 확인한다. 숨김 파일 stem은 후보에서 거절한다. 같은 이름/원본도 기존 Python처럼 별도 논문으로 저장한다. metadata/domain/agent는 filename stub과 general로 표시하며 provider를 호출하지 않는다. React의 기존 선택 파일 상한은 50 MiB로 유지한다.
- GET /api/papers/{id}/extraction: current의 source/options/document 해시를 검증한다. version query는 명시적 historical 조회이며 current로 표시하지 않는다.
- POST /api/papers/{id}/extraction: 원본을 다시 추출해 새 immutable version을 공개한다. 기존 버전과 성공 파일은 유지하고 source/current CAS가 다르면 공개를 거절한다.
- GET /api/papers/{id}/search?q=...: 저장한 페이지별 본문을 chat_retrieval에 공급한다. page_unverified를 유지하며 같은 추출물을 독립 파서로 다시 사용하지 않는다.
- POST /api/papers/{id}/selection-context: text/page/end_page를 받아 해당 물리 1-based 페이지 범위만 match_selection에 전달한다. matched는 저장 본문의 일치이며 원본의 독립 검증을 뜻하지 않는다.
- POST /api/papers/upload/{operation_id}/cancel: 업로드/refresh의 X-Sasoo-Pdf-Operation-ID와 일치할 때만 취소를 요청한다. 슬롯은 실제 producer 반환까지 유지한다. 이미 공개된 결과는 취소 요청으로 되돌리지 않으며 native 중단은 경계 취소다.

원본은 staging에서 해시 확인 후 이동하며 추출물은 paper/.sasoo-runtime/pdf/{uuid}/에 create_new로 저장한다. receipt와 document를 재검증한 뒤 DB transaction이 버전/current 참조를 공개한다. 파일 준비 뒤 DB 실패, 취소 또는 crash가 생기면 새 미공개 파일이 남을 수 있고 HTTP가 제공하지 않는다. 자동 삭제/복구는 구현하지 않는다. GET은 추출/refresh를 예약하지 않는다. source 교체, 오래된 옵션, 손상 또는 없는 출력은 text_ready=false와 stale/invalid/missing으로 표시한다.

기존 React Workbench는 pdf_candidate인 논문에 저장 본문 검색/선택 문맥을 표시한다. upload 완료, text readiness, visual readiness, analysis 미실행을 구분하고 자동 분석을 차단한다. candidate의 agent catalog는 빈 stub이다. 비용/provider/전체 분석 경로는 이번 범위에 없으며 Home의 GET /api/settings/cost는 501이다. 이 API 확장은 후보 전용이며 기존 OpenAPI snapshot 전체 이식 완료를 뜻하지 않는다.

실행 파일의 server mode는 기존 절대 디렉터리를 가리키는 SASOO_RUST_ISOLATED_ROOT가 필요하다. 실제 app-data나 library를 지정하지 않는다. worker mode는 수명 관리 연결 전이므로 Unsupported로 종료하며, 미연결 API는 501을 반환한다. 새 crate를 기존 launcher의 backend로 선택하면 기능이 빠진 상태가 되므로 설치본 전환 gate를 먼저 충족해야 한다.

## 자료 보존

현재 backup/migration은 정확한 synthetic fixture marker가 있는 격리 DB만 허용한다. worker가 migration을 수행하지 않으며, 새 API가 사용자의 실제 DB/키/라이브러리에 연결되는 factory는 제공하지 않는다. PDF 모델/native runtime과 유료 provider 호출도 자동 실행하지 않는다. unknown usage나 과거 NULL을 0 또는 새 provenance로 바꾸지 않는다.
