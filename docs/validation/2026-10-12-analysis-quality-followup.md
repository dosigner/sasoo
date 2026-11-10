# Sasoo 분석 품질 후속 구현과 오프라인 검증

2026-10-12. 표시, HTML 입력 점검, 그림/HTML 원문 근거 전달, recipe의 재현 조건 검색을 구현했다. 비용 없는 회귀 검사와 실제 Chromium GUI 확인을 완료했다. 새 공급자 API 호출은 0건이며 추가 공급자 비용은 $0이다. 새 결과의 공급자 생성 품질과 설치 앱은 이번 검증 범위에서 미검증이다.

## 완료 기준별 판정

| 완료 기준 | 판정과 관측 | 재현 근거 |
|---|---|---|
| 중복 단위와 단위 경계 | 통과. 같은 원본 `60%`/`%`가 수정 전 `60%%`, 수정 후 `60%`. `ms`/`s`, `kg`/`g`는 다른 단위로 취급하며 자동 단위 변환을 하지 않는다. 원본 저장값은 유지했다. recipe 화면과 CSV도 같은 formatter를 사용한다. | `unit-regression.json`, `synthesisBlocks.test.ts`, `recipeCsv.test.ts` |
| 빈 t와 검사 범위 | 통과. 기존 실응답 HTML은 예전 검사기에서 passed, 새 검사기에서 failed다. 수정한 별도 fixture는 passed다. 입력을 개별 점검해 한 입력만 반응하는 사례에서 반응하지 않는 입력을 드러냈다. 정상 상수 출력과 유효한 선택 기본값은 명시된 정책 아래 통과했다. | `html-regression.json`, `verify_html.py` |
| 무효 입력과 이전 출력 | 통과. 빈 문자열/공백, 범위 밖 t, σ=0, vector 차원 불일치 및 빈 성분에서 계산값을 `—`로 바꾼다. 기존 HTML도 로컬 wrapper가 숫자 입력의 빈 값과 범위 오류를 차단한다. sandbox, CSP, nonce, 메시지 출처 검사와 timeout은 유지했다. | 동일 HTML 회귀, `HtmlVisualization.dom.test.tsx` |
| 그림/표 개수 의미 | 통과. 표시와 report는 추출 개수라고 명시한다. 새 visual 결과는 추출 개수와 모델이 보고한 수를 별도 필드에 보존한다. 모델의 보고 수는 원문 전체 개수의 검증값이 아니다. 원문 전체 개수는 미확인이다. screening의 false와 DB 행은 수정하지 않았다. | `workbenchSummaries.ts`, `report_service.py`, 백엔드/프런트엔드 회귀 |
| Table 1 요청 근거 | 통과, mock 요청 전달 범위. 저장된 실제 요청에는 2.99/6.35/142가 없었다. 수정 경로에서 캡처한 설명 요청에는 값과 PDF p.8 위치가 들어간다. 본문의 앞부분만 자르는 방법 대신 계획이 참조한 페이지를 선정한다. 표 근거를 확보하지 못하면 유료 생성 전에 오류와 이유를 남긴다. | `captured-offline-requests.json`, `source-regression.json`, `test_analysis_quality_followup.py` |
| flow map/density 구별 | 통과, 명시된 역할 혼동 탐지 범위. 저장된 설명 응답의 `ψ=Gaussian density` 오기를 탐지한다. 설명 검사 실패 시 렌더 요청을 하지 않고 설명 요청 사용량을 보존한다. 모든 수식의 대수적 동등성을 증명하는 검사기는 아니다. | 동일 백엔드 회귀, `figure_gen.equation_role_conflicts` |
| HTML 원문 식과 계산 | 통과, 요청 전달 및 fixture 실행 범위. 독립 요청에 원문 식 (10), (21), (22), (23), 변수 정의와 PDF 위치가 들어간다. 경계값과 대표 vector 입력의 화면값은 독립 계산과 상대 오차 5e-7 이내다. `x=x0`에서 field를 평가한 값과 이동 위치에서의 field를 따로 비교했다. 새 공급자 HTML 생성은 미실행이다. | `html-regression.json`, 캡처 요청 |
| recipe 조건 누락/미보고 충돌 | 통과, 로컬 검색 후보를 드러내는 범위. 원본 PDF 텍스트에서 시간 분포, 전처리, target/loss, 평가 보정, solver 근거를 찾아 별도 `reproduction_check`로 반환한다. A의 시간 sampling 부재 주장과 p.17의 정규화/BPD 누락을 대조 대상으로 드러낸다. U-Net normalization과 pixel 정규화를 혼동한 충돌은 회귀에서 제외했다. 검색 실패는 저자의 미보고 증명이 아니다. | A/B reproduction JSON, 원문 p.4/6/17 렌더, 새 API 배선 회귀 |
| 미확인 값과 상세함 | 통과. 기존 recipe, σ_min 및 학습 seed를 자동 보충하지 않는다. 저장된 A/B의 17개 deep_dive 필드, 절별 답변 12개, 적용 조건 검사 8개가 그대로이며 이 개수를 제품 고정 규칙으로 쓰지 않았다. | 새 품질 회귀의 원본 불변 검사 |
| 실제 GUI 및 export | 통과. 현재 React 앱을 Chromium에서 1400×900, 1024×900으로 실행했다. 60% 표시와 recipe 원문 대조 UI를 확인했다. 390px HTML도 실행했다. 앱/HTML의 가로 넘침, 런타임 오류와 콘솔 오류는 0이다. HTML 외부 요청과 fixture 앱의 데이터 쓰기는 0이다. export도 같은 HTML wrapper의 입력 오류 처리를 확인했다. | `gui-evidence.json`, 앱/HTML PNG, `html-regression.json` |
| 새 유료 평가 | 준비 완료, 승인 대기. 과거 원장이나 요청을 재발행하지 않았다. 계획과 소스/원문 해시, 모델/effort, 호출 수, 예약 예산, 중단 기준을 별도 manifest로 보존했다. | `paid-evaluation-proposal.json` |

## 실제 검사

- 백엔드 `./.venv/bin/python -m pytest services api models -q`: 1,162개 통과, 268개 하위 검사 통과. 기존 의존성의 deprecation warning 44개가 있었다.
- 이후 추가한 새 품질 회귀 8개 통과. 실제 recipe API 배선, Table 1 payload, HTML 식, 원본 불변성, 리뷰에 조건을 강제하지 않는 경계를 포함한다. 최종 관련 기존 묶음도 232개와 하위 검사 16개가 통과했다.
- `python -m py_compile main.py` 통과.
- 프런트엔드 전체 Vitest 44개 파일, 363개 테스트 통과. 마지막 UI/guard 변경 뒤 관련 묶음을 다시 통과했다.
- 최종 `pnpm exec tsc --noEmit`, `pnpm lint`, `pnpm build` 통과.
- `git diff --check` 통과.

GUI 재현은 저장소 루트에서 `pnpm --dir sasoo/frontend dev --host 127.0.0.1 --port 5178 --strictPort`를 실행한 뒤 `python3 docs/validation/assets/analysis-followup-20261012/verify_html.py`와 `verify_gui.py`를 실행한다. 시스템 Python의 기존 Playwright/Chromium 설치를 사용했다. 이 작업에서 시작한 Vite 프로세스는 검증 후 종료했다.

현재 backend/.venv는 Python 3.14다. 이번에는 release packaging을 하지 않았으므로 release용 Python 3.12 검증으로 표현하지 않는다.

GUI는 실제 React 앱과 브라우저를 사용했지만 API 응답은 격리한 GET fixture다. 원문 PDF와 생성 이미지 파일은 기존 검증 복사본/저장된 실응답에서 읽었다. 원문 그림의 정적 리소스 일부는 fixture 대응 이미지를 사용하므로 원문 그림 추출 품질 검증으로 해석하지 않는다. 비어 있는 실험 계획 GET fixture를 함께 제공했고 생성 POST는 차단했다. 실제 공급자, 번들 backend, 설치 앱, 자동 업데이트를 이번 GUI 검증이 입증하지는 않는다.

HTML fixture 수리는 새 폴더의 복사본에만 적용했다. 저장된 기존 유료 HTML의 script 자체는 바꾸지 않았다. 따라서 기존 생성 코드의 결함은 회귀 대상으로 남아 있으며, 앱 wrapper의 방어와 새로운 생성 프롬프트의 요구사항을 구분해야 한다.

## 변경 파일과 설계

- `frontend/src/lib/synthesisBlocks.ts`, `recipeCsv.ts`, `components/RecipeCard.tsx`: 공통 단위 표시, CSV 의미 일치, 재현 조건과 미보고 미확정 표시.
- `components/HtmlVisualization.tsx`, `HtmlVisualization.dom.test.tsx`, `lib/strings.ts`, `lib/vizExport.ts`: 개별 입력/빈 값/경계 검사, 상수와 선택 기본값 계약, 무효 결과 차단, export의 동일 wrapper 재사용.
- `components/AnalysisPanel.tsx`, `lib/workbenchSummaries.ts`, `backend/api/report_service.py`: 추출 개수의 의미와 검증 범위 표시.
- `backend/services/document_context.py`, `analysis_execution.py`, `viz/figure_gen.py`, `api/analysis_routes.py`: 계획 관련 원문 페이지 선정, 직접 생성과 재생성 경로의 동일 근거 전달, 원문 표 부재의 생성 보류, 역할 혼동 탐지와 결과 provenance.
- `backend/services/evidence_verifier.py`, `evidence_repo.py`, `frontend/src/lib/api.ts`, `components/synthesis/DiagramCard.tsx`: 기존 인용 검사와 별개인 PDF 조건 검색, 독립 검증 상태와 생성/정확성 범위 표시.
- `backend/services/test_analysis_quality_followup.py`, `frontend/src/lib/synthesisBlocks.test.ts`: 저장된 실패 사례를 사용한 회귀.

정확한 식은 기존 EquationChain/KaTeX 경로를 유지했다. 표 역시 기존 표 탭의 데이터 렌더 경로가 확인용 기준이다. 이미지의 모든 글자와 숫자를 자동 검증하는 새 OCR/검토 모델은 추가하지 않았다. 원문 수치/식은 제품 로직에 하드코딩하지 않았다.

## 보존과 캐시

기존 병렬 실행의 `_run_parallel`, 단계 중첩, 생성 항목 수집/체크포인트 구조는 유지했다. 모델 레지스트리, effort, concurrency와 가격표는 변경하지 않았다. 사용량/unknown cost, 취소와 늦은 저장 거부, 부분 실패 재사용 검사도 기존 테스트에서 통과했다.

`_CHAIN_CACHE_VERSION`은 유지했다. recipe 프롬프트의 변경은 해당 phase의 기존 prompt hash에만 반영되며, visualization은 원문 근거 버전과 입력 signature를 캐시 키에 포함한다. 기존 성공 데이터와 비용을 삭제하지 않으며 새 생성은 사용자의 명시적 재분석/재생성 경로에서 발생한다. 기존 결과 조회에 붙는 recipe 조건 검색은 로컬 PDF 작업이며 원본 result blob과 인용 앵커를 바꾸지 않는다.

시작 시 17개 기존 dirty 파일을 복사하고 초기 patch/status를 보존했다. 이번 변경과 겹치지 않는 12개 dirty 파일은 초기 복사본과 바이트 일치다. `parallel-live-20261011/`의 증거 파일 125개도 초기 SHA-256과 전부 일치한다. 초기 코드와 수정 코드의 별도 소스 아카이브 및 해시를 남겼다. 커밋, push, 공개 배포, 사용자 라이브러리 쓰기는 하지 않았다.

## 새 유료 검증 제안

대상은 원문 해시를 확인한 다음 3편이다.

1. 계산 중심: Flow Matching for Generative Modeling, 28쪽.
2. 정량 중심: Uplink pre-compensation for ground-to-space optical communications using downlink tomographic reconstruction, 12쪽. 광학 수치/시뮬레이션 조건 전달을 확인한다.
3. 리뷰: Optical Communication in Space: Challenges and Mitigation Techniques, 41쪽. 적용되지 않는 실험 조건을 강제하지 않는지 확인한다.

논문마다 초기 버전/수정 버전을 새로 1회씩 실행하므로 총 6회다. 두 버전 모두 현재 병렬 실행을 유지하며, 후속 수정의 품질과 지연을 비교한다. 병렬화의 인과 효과를 추정하는 실험은 아니다. 같은 논문 pair에서는 같은 계획과 항목 수를 사용하고 초기→수정, 수정→초기 순서를 교차한다. 캐시 적중/작업량 차이는 별도 기록한다. source PDF, source archive, 설정과 plan의 해시를 발행 전에 잠근다.

보수적 상한은 실행당 기본 텍스트 7개, 이미지 설명 5개, 이미지 렌더 5개, Mermaid 3개, HTML 1개로 21개 요청, 전체 126개다. 리뷰의 recipe/HTML 부적용이나 작은 계획이면 실제 호출은 더 적다. 텍스트 요청 $0.30, 이미지 요청 $0.60의 예약 한도를 쓰면 최대 예약은 $46.80이고 제안 전체 상한은 $54다. 이는 현재 공급자 확정 견적이나 기존 잔액이 아니다. 승인/발행 전에 단가와 출력 상한을 재확인한다.

새 run ID와 요청별 ledger를 사용하며 재시도를 끈다. 발행 전에 예약하고 응답 사용량으로 정산한다. 미확인 사용량/청구 상태, timeout, 승인 소스/모델/계획 불일치, 호출 수 또는 예산 초과가 발생하면 추가 발행을 멈춘다. 기존 요청 상태/응답부터 복구하며 성공 요청을 재발행하지 않는다. 실제 사용량 계산과 청구서 확인은 별도로 기록한다. 원문과 익명 결과만 받는 독립 검토는 생성 성공, 실행 성공, 원문 정확성을 각각 판정한다.

## 학습 메모와 남은 한계

숫자 계산에 앞서 입력의 의미를 검증해야 한다. `Number('')=0`은 JavaScript 변환 결과이지 사용자가 0을 입력했다는 뜻이 아니다. 저장된 실패 fixture가 새 검사에서 실패하는지부터 확인하면 검사기의 맹점을 재현할 수 있다.

원문을 앞 단계에서 읽었다는 사실은 독립 후속 요청이 그 식과 값을 받았다는 증거가 아니다. 캡처한 실제 요청과 원문 위치를 대조해야 한다. 특히 Flow Matching에서 `u_t(x0)`와 `u_t(ψ_t(x0))`의 차이는 평가 위치이며, 끝점 예시의 10과 1은 서로 다른 정의에 따른 값이다. p.17의 변환과 Jacobian/BPD 보정도 재현 과정의 일부다.

로컬 recipe 검색은 원문에 있는 조건과 부재 주장의 충돌 후보를 드러낸다. 자연어 설명의 동등성, 모든 조건의 누락 여부, 저자 미보고의 확정은 아직 독립 검토가 필요하다. 명시된 상수 출력 사유도 수학적으로 검증한 것으로 자동 승격하지 않는다. 기존 그림의 density 오기와 숫자가 없는 비교 그림은 보존돼 있으며 새 공급자 결과가 해결됐는지는 미검증이다.

생략/미검증: 새 유료 생성, 청구서 대조, 설치 앱/패키징, 실제 학습과 논문 성능 재현은 수행하지 않았다.
남은 위험: 요청에 근거를 전달하고 테스트가 통과해도 모든 논문의 과학적 정확성이 보장되지는 않는다.
