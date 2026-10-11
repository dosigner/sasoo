# Sasoo 1.2.0 visualization fixes: completion table

작성일: 2026-10-10. 기준: 공개 v1.2.0 `3076abfe56ff7cd06444c64eebd85e6b180491aa` (origin/main과 같음, tree `e12b7b14`). 브랜치 `fix/viz-top10`. 발견 번호는 `2026-10-10-visualization-top10-review.md`를 따른다. 유료 API, 사용자 DB, 자격 증명은 쓰지 않았다. 모든 검증은 합성 데이터, 격리 DB, 로컬 가로채기로 했다.

## 완료표

| # | 상태 | 커밋 | 수정 전 실패 근거 | 수정 후 근거 |
|---|---|---|---|---|
| 1 | 해결 | 9a5e6e6 | 실제 ZIP을 file URL로 열었을 때 외부 요청 3건(location.href, 링크 클릭, meta refresh. 뒤의 둘은 보고서에 없던 경로) | 같은 시험에서 0건. 바깥 문서에 안쪽과 같은 CSP(frame-src 'none'). 슬라이더 계산(7에서 14)과 Tab, ArrowRight 조작은 그대로 동작 |
| 2 | 해결 | 5f2fafa, 2795625 | updater가 최신 행을 다시 읽어 새 실행에 옛 결과를 저장. 같은 행 두 항목 동시 갱신에서 한쪽 유실 | run_id(행 id)와 run_token으로 실행을 식별. 바뀐 실행은 409. 행 쓰기는 CAS. 워커도 행 점유와 체크포인트를 CAS로 하고, 라우트 편집을 병합 |
| 3 | 해결 | bb27248 | 미완료와 오류 봉투가 빈 성공 계획 `[]`로 반환. 깨진 계획 캐시도 `[]` | 새 계획은 스키마 전체가 필수. 오류 봉투는 거부. 읽을 수 없는 캐시는 miss. 실패하면 생성 호출 0회, 완료 행 없음 |
| 4 | 해결 | 7e6ed01, 2795625 | 실패 항목이 있는 완료 캐시를 그대로 반환. 중단된 체크포인트에서 성공한 Mermaid를 재호출 | 모든 항목이 성공하고 이미지 파일이 논문 폴더에 있을 때만 캐시 hit. 그 외에는 실패, 누락, 미완료 항목만 생성. 재사용 예정 항목도 체크포인트에 기록 |
| 5 | 해결 | bb27248 | illustrations 누락 응답이 레거시 경로로 중요도 0인 Mermaid 3개를 수락. 과다 배정 캐시 계획에서 이미지 9개와 Sunburst 여러 장 생성 | 레거시 정규화 경로 삭제. 신선한 계획과 캐시 계획 모두 생성 직전 게이트(이미지 5, Mermaid 3, HTML 1, 추가 항목 60점, Sunburst 1)를 통과 |
| 6 | 해결 | 5f2fafa, 2795625 | 실제 hook(jsdom)에서 old plan, 재생성, new plan 순서로 진행하면 `regenerated old plan`이 표시 | override, 진행 표시, 오류를 `run_id:run_token`별로 보관. 늦게 끝난 옛 실행의 결과는 새 실행에 적용되지 않음 |
| 7 | 해결(범위 명시) | 41d078a, 2795625 | 문법 오류, assert 실패 HTML이 completed로 표시. 실행 신호 없음 | sandbox frame 안의 실행 점검(오류, 예외, console.assert, `<output>`의 NaN과 Infinity, 입력 무반응). nonce와 frame source를 검증하고, 10초 무응답이면 frame을 제거. 결과를 항목에 저장하며, failed는 캐시 재사용에서 제외. 화면에는 "원문 기준으로 검산하지 않았어요"를 항상 표시 |
| 8 | 해결 | d150eba | 이미지 설명 비용이 빠져 $0.1225로 기록(기대값 $0.1229). Mermaid와 실패한 시도의 비용 없음 | 요청마다 `{id, kind, model, cost_usd}`를 기록. Mermaid, 설명, 렌더, HTML, repair가 한 번씩 합산되고, 체크포인트와 캐시 hit에서 중복 없음 |
| 9 | 해결 | d150eba | 미확인 재생성 비용이 옛 값 0.1225를 유지. 행의 cost_incomplete 미갱신 | 재생성 비용이 None이면 None으로 교체. 이전 요청은 prior_requests에 보존. 실패하거나 실행이 바뀐 재생성의 비용도 원래 실행에 기록 |
| 10 | 해결 | d150eba | 미확인 비용만 있는 상태에서 대시보드가 "아직 분석 데이터가 없어요" 표시 | 비용 API가 기간, 논문, 모델별 unknown_cost_count를 반환. 대시보드와 Home 타일이 미확인 건수를 표시 |

추가 수정: 라이트박스 focus trap에 iframe이 없어 키보드로 HTML 설명에 들어갈 수 없던 문제(41d078a).

## 계약 요약

- 비용: 행의 `cost_usd` 열은 알려진 USD 합계(반올림 없음), payload의 `cost_unknown_count`는 미확인 요청 수다. 합계는 매번 기록에서 다시 계산한다. API 응답에서만 소수 4자리로 반올림한다. 미확인 비용은 0으로 치지 않는다.
- 실행 정체성: `(run_id, run_token)`. 같은 입력으로 재분석하면 행 id는 그대로 두고 run_token을 새로 받는다.
- 실행 점검: 생성 성공, 실행 점검 통과, 원문 수치 검산은 서로 다른 상태다. 앱에는 독립 수치 기준이 없으므로 검산 상태는 항상 미확인이다.

## 검증

- backend `services api models`: 1134 passed, 1 failed, 7 skipped. 실패 1건은 sandbox 안의 Java ODL 테스트로, sandbox 밖에서는 통과한다.
- frontend vitest: 350 passed. `tsc --noEmit`, eslint, `vite build` 통과.
- root vitest(Electron 포함): 277 passed.
- 독립 리뷰(deep-reasoner)에서 P1 1건, P2 2건, P3 6건이 나왔다. P1, P2 두 건, P3의 repair 비용과 503 구분은 2795625에서 수정하고 회귀 테스트로 고정했다. 이 테스트들이 수정 전 커밋에서 실패하는 것도 확인했다.
- Chromium 147, 실제 내보내기 ZIP, 합성 fixture 11종:
  - 문법 오류, 예외, assert 실패, NaN, 범위 밖 숫자 입력, 입력 무반응은 실패로 판정.
  - 무한 루프는 시간 초과 처리 후 frame 제거.
  - debounce 갱신과 설명 문장의 "Infinity"는 오판 없이 통과.
  - 출력값 대조: y(7)=14, RC 방전 τ=100 ms, V=4.4146 V가 독립 Python 계산과 일치. 외부 요청 0건.
- 브라우저 GUI(worktree frontend, 합성 공급사 백엔드, 격리 DB, 1440x900과 1024x700, light와 dark):
  - 실패 이미지 복구: 같은 실행 행에 저장. 비용 증가 $0.1285가 단가표 계산(설명 $0.006 + 렌더 $0.1225)과 일치.
  - 재생성 중 재분석: 409와 안내 문구 표시. 새 실행 행은 그대로이고, 비용은 원래 실행에 기록. 새로고침 후 새 실행 표시.
  - ZIP 내보내기: 부모 CSP와 sandbox 확인.
  - 비용 미확인: 대시보드와 Home에 4건으로 표시.
  - 실패 HTML: 화면과 저장값 모두 failed.
  - 무한 루프 HTML: 루프 중에도 탭 전환이 즉시 반응. 약 10초 뒤 timeout 표시와 다시 실행 버튼.
  - 키보드: 라이트박스에서 Tab 2회로 iframe에 진입하고 슬라이더 조작.
  - 콘솔 오류는 의도한 409와, `node_modules` 심볼릭 링크 때문에 생긴 vite 개발 서버의 pdfjs 아이콘 403뿐.
- Electron 43.4.0(Chromium 150), 앱과 같은 webPreferences: sandbox srcdoc iframe이 별도 프로세스에서 실행되고, 무한 루프 중에도 부모 타이머가 동작(2초에 20회).
- 원본 작업 폴더: 기존 소스 20개의 해시와 `git status` 해시가 시작 시점과 같다.

## 확인하지 않은 범위

- 실제 공급사 응답과 청구서. 비용은 합성 사용량과 단가표로만 계산했다.
- 패키징된 Electron 앱에서의 전체 흐름. 개발 모드 Electron은 사용자의 기존 개발 세션이 포트 5173을 쓰고 있어 띄우지 않았다. 같은 Electron 바이너리로 프로세스 격리만 확인했다. 패키징된 백엔드에는 합성 공급사를 주입할 수 없다.
- 실제 재분석 파이프라인 전체와 재생성의 동시 실행. 함수 수준(격리 DB, 실제 워커 저장 경로)과 jsdom hook, DB 삽입으로 흉내 낸 GUI로 확인했다.
- 남은 P3:
  - 재생성의 일반 예외(VizGenerationError 외) 경로는 비용을 기록하지 않는다.
  - 레거시 단일 Mermaid의 repair 비용은 기록할 실행이 없다.
  - 월별 by_model에 미확인 건수가 없다.
  - 앱 index.html CSP는 frame-src를 default-src 'self'에 맡긴다(외부 출처 탐색은 차단됨).
- 늦게 실행한 재생성 비용은 해당 실행 행이 처음 기록된 달로 집계된다.
- 실행 점검은 우발적 결함을 찾는다. 의도적으로 결과를 위조하는 HTML은 sandbox와 CSP로 격리할 뿐, 점검 결과를 신뢰할 수 없다.

## 후속 수정 (2026-10-11, v1.2.1 이후)

위 "남은 P3" 중 비용 기록 3건과 월 귀속 1건을 고쳤다. index.html CSP 항목은 그대로 남아 있다.

| 항목 | 원인 | 수정 | 회귀 테스트 |
|---|---|---|---|
| 재생성의 일반 예외 | 생성기가 유료 호출 뒤에 예외를 내면 기록을 버렸다. Mermaid는 응답에 `text`가 없으면 `KeyError`, 이미지는 렌더 뒤 파일 저장이 실패하면 `OSError`. 재생성과 분석 파이프라인이 같은 생성기를 쓰므로 양쪽에 있던 결함이다 | 응답 텍스트는 `get`으로 읽는다. 렌더 기록을 파일 저장 전에 남기고, 저장 실패는 다른 공급사로 재시도하지 않는 실패 결과로 돌려준다 | `test_reply_without_text_still_records_its_spend`, `test_image_that_cannot_be_saved_still_records_the_paid_render` |
| 레거시 단일 Mermaid | `GET /mermaid` 생성과 `viz_id` 없는 repair에는 기록할 실행이 없었다. 생성 쪽도 비용을 남기지 않았다(보고서에 없던 경로). 앱 화면은 이 경로를 쓰지 않는다(`useAnalysis`의 `mermaid`는 항상 null) | 두 경로의 요청을 `phase='mermaid'` 원장 행으로 남긴다. 호출 실패는 비용 미확인 행이다. repair 대상 항목이 사라진 경우도 원래 실행에 기록한다 | `LegacyMermaidCostTests` 2건 |
| 월별 by_model 미확인 | 월별 항목에 모델별 미확인 건수가 없었다 | `by_model_unknown` 추가(화면에는 표시하지 않는 API 필드) | `test_summary_keeps_known_totals_and_counts_unknown_requests` |
| 늦은 재생성의 월 귀속 | 월 집계가 행의 `created_at`만 봤다. 같은 원인으로 월 예산 한도(`read_budget_state`)도 늦은 재생성 비용을 이번 달에 넣지 않았다(보고서에 없던 경로) | 새 요청 기록에 `at`(UTC)을 넣고, 공용 `pricing.ledger_entries`가 요청마다 월을 정한다. 대시보드와 예산이 같은 함수를 쓴다. `at`이 없는 기존 기록과 일반 행은 행의 월을 따른다 | `test_late_regeneration_is_counted_in_the_month_it_ran`(대시보드와 예산) |

새 회귀 테스트 6건은 수정 전 main(5d09040)에서 모두 실패하고 수정 후 통과한다. backend `services api models`는 1140 passed, 7 skipped, frontend vitest는 350 passed, root vitest는 277 passed, `tsc --noEmit`과 eslint는 통과했다. 예산 테스트 3건과 기존 mock 테스트 2건은 `fetch_one` 대신 `fetch_all`, 원장 INSERT에 맞춰 fixture만 고쳤고 단언의 의도는 같다.

남은 한계: 이미 저장된 v1.2.x 기록에는 `at`이 없어 행의 월로 집계된다. 토큰 수와 논문 수는 계속 행의 월을 따른다.
