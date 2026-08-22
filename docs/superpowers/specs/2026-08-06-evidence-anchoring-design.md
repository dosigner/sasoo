# Evidence Anchoring MVP 설계 (Phase 1)

2026-08-06. deep-reasoner(opus)와 Codex의 독립 병렬 설계를 종합한 확정 스펙.
원본 보고서: `.superpowers/sdd/2026-08-06-evidence-anchoring-mvp/phase1-design-{deepreasoner,codex}.md` (로컬).
근거 데이터: deep-reasoner의 실측 스파이크(라이브러리 13편·440문장 샘플).

## 목표

Recipe 파라미터마다 (evidence_quote, page, 검증 상태, bbox)를 붙이고, LLM이 아닌 결정론적
코드로 검증한 뒤, UI에서 상태를 정직하게 표시하고 클릭하면 PDF 해당 위치로 이동한다.
검증 실패는 UNVERIFIED 계열로 남긴다 — 조용한 승격 금지.

## 두 설계가 수렴한 결정 (그대로 채택)

1. **신규 `evidence_anchors` 테이블** — `analysis_results.id` FK. LLM 원본 JSON blob은 무수정
   보존, 검증 결과는 분리 저장. alembic 불필요(순수 추가 — 기존 init_db() ALTER 패턴).
2. **LLM 역할은 후보 생성까지** — `_RECIPE_SCHEMA.parameters.items`에 `evidence_quote`(가장 짧고
   연속된 축자 인용 1개)와 `evidence_page`(1-based)만 추가. `verification_status`/`bbox`류는 절대
   LLM 출력 필드로 두지 않는다. `source_tag`는 required로 승격.
3. **검증은 `_run_recipe` 내 동기 실행** — recipe row 저장(`lastrowid` 확보) 직후, phase
   completed 노출 전. 별도 큐·phase 신설 금지(로컬 문자열 연산, 41페이지 논문 실측 ~0.4초).
4. **캐시 히트 경로도 검증 실행** — 캐시 helper가 source `analysis_results.id`를 반환하게 확장
   (`CachedPhaseResult.result_id`), `ensure_evidence_anchors(result_id)`로 옛 결과 백필·검증기
   버전업을 LLM 재호출 없이 수행. 롤아웃 시 `_CHAIN_CACHE_VERSION` bump.
5. **파라미터 안정 ID 부재 대응** — 검증기가 사후 부여한 키(`analysis_result_id` + 파라미터
   index + name slug)로 연결하고, 프론트는 label 불일치 시 앵커를 숨긴다(fail closed).
6. **MVP 범위: Recipe 파라미터만** — claim 제외. 단 스키마는 `target_kind`/`target_key`를
   범용으로 두어 이후 claim·코퍼스 비교를 스키마 교체 없이 수용.
7. **사용자 확인/수정 UI 제외** — read-only 상태 표시만. 클릭으로 UNVERIFIED→VERIFIED를 바꾸는
   UI는 금지(후속 phase에서 자동 상태와 분리된 human_review_status로 설계).
8. **값 가드** — quote가 존재해도 explicit 파라미터의 값(숫자·단위)이 quote 안에 없으면 검증
   실패(`VALUE_MISMATCH`). inferred 파라미터는 구조적으로 VERIFIED 불가.

## 갈린 지점과 종합 판정

### A. 검증 대조 원본 → **PDF 텍스트층(PyMuPDF) 일원화** (deep-reasoner 안 채택)

실측: PDF 축자 인용을 매니페스트 full_text로 대조하면 70.7%만 확인(ODL 83.0%/Gemini 33.6%),
PDF 텍스트층으로 대조하면 91.4%. 레시피 체인은 PDF를 직접 입력받으므로 대조 대상도 PDF여야
하고, 이 결정으로 파서 엔진 비대칭이 사라지며 bbox(`page.search_for`)가 양 엔진 모두에서
얻어진다. Codex의 핵심 통찰은 흡수: **Gemini 전사본으로는 절대 검증하지 않는다**(LLM quote를
다른 LLM 전사본으로 확인하는 순환 검증 금지). 텍스트층이 없는 스캔 PDF는 `NO_TEXT_LAYER`로
정직하게 표시.

### B. 상태 어휘 → **직교 3필드 + 파생 표시 상태** (deep-reasoner 구조에 Codex 상태 통합)

단일 enum(Codex 13종)은 조합 폭발로 커진다. 저장은 직교 필드로:
- `quote_status`: verified_exact | verified_normalized | partial_match | not_found | no_quote | no_text_layer | ambiguous | stale_source | verifier_error
- `page_status`: match | mismatch(발견 페이지는 진단 필드로 보존) | invalid_page | no_page | derived(전문 검색으로 유일 발견)
- `value_status`: value_in_quote | value_missing | inferred | not_applicable
UI/export용 파생 상태 1개(`display_status`)를 결정론 규칙으로 계산: **VERIFIED는
quote_status∈{exact,normalized} ∧ page_status∈{match,derived} ∧ value_status=value_in_quote일
때만.** 나머지는 전부 미검증 계열 라벨.

### C. partial_match는 검증이 아니다 (실측 근거로 확정)

숫자 한 자리를 바꾼 위조 인용이 유사도 임계 0.6에서 81.1%, 0.8에서도 52.0% 통과(정규화 완전
일치는 0.0%). 따라서 partial_match는 "부분 일치 — 미검증"으로만 표시하고, **위조 인용
false-verify = 0**을 pytest 회귀 게이트로 고정한다.

### D. bbox 하이라이트 컷라인 → 사용자 결정 (DEC-009)

양안 공통: bbox는 백엔드에서 처음부터 저장(PyMuPDF search_for). 차이는 acceptance 범위 —
Codex: 페이지 점프+quote 표시까지만 acceptance, 하이라이트는 다음 increment.
deep-reasoner: 하이라이트 포함 권고(일정 압박 시 프론트만 컷).
→ 사용자 결정으로 확정한다.

### E. near-miss quote 노출 범위 (DEC-012, 2026-08-08 추가)

페이지만 어긋난 매치(`UNVERIFIED_PAGE_MISMATCH`)는 "인용이 원문에 축자로 존재한다"와 "값이
인용 안에 있다"가 이미 보장된 유일한 미검증 버킷이다(C절의 partial과 다르다). 이 버킷에
한해 matched_quote를 툴팁과 CSV에 노출하되 검증 도장은 붙이지 않는다 — 배지는 "다른
페이지에서 발견", 툴팁은 "발견된 원문 (p.발견)"에 주장 페이지를 병기한다. 요약 배지 분자에는
넣지 않는다(분자는 VERIFIED만).

노출 허용 상태는 `frontend/src/lib/evidence.ts`의 `FOUND_QUOTE_STATUSES` 한 곳에서 정의하고
툴팁과 CSV가 같이 참조한다. 이 집합을 넓히는 것은 표시 정책 변경이 아니라 검증 계약 변경이다.
제외 사유는 상태마다 다르다 — partial은 C절 실측(위조 인용 81% 통과)이 막는 영구 제외이고,
ambiguous는 매치 위치가 하나로 좁혀지지 않아 "발견 페이지"를 한 값으로 쓸 수 없어서 제외한다.
후자는 다중 위치 UI가 생기면 재검토 대상이다(DEC-012 Revisit condition).

CSV 열 이름은 9열을 유지한 채 상태 중립 + 한국어로 고정한다(구분, 항목, 값, 검증 상태,
검증 방법, 발견 인용, 발견 페이지, 주장 인용, 주장 페이지). 이름에 "(verified)" 같은 도장이
남아 있으면 미검증 행을 채우는 순간 조용한 승격이 되므로, 이름 정리가 노출의 선행 조건이다.
발견 인용과 발견 페이지는 한 덩어리로 게이팅한다 — 인용을 막은 행에 페이지만 남기면 같은
과대표현이 된다. 검증 요약 메타 행은 백엔드 summary가 아니라 화면과 같은 anchored 분모로 센다.

이 결정이 바꾸지 않는 것: 요약 배지 분자(VERIFIED만), bbox 하이라이트 스타일(위치 표시일 뿐),
백엔드 검증기와 저장 스키마. 표시 정책만의 변경이다.

## normalized match 규칙 (normalizer-v2)

(0단계: zero-width 문자·soft hyphen 제거 — 줄바꿈 하이픈 결합의 전제 조건, 구현 중 추가 확정)
→ NFKC → 소문자 → 유니코드 대시·하이픈 계열 통일 → 리거처 해제 → 줄바꿈 하이픈 결합
(`-\n` 제거) → 공백 연속 1개로 축약 → 스마트 따옴표 통일. 버전 태그를 앵커 행에 저장
(`normalizer_version`), 규칙 변경 시 재검증 트리거(`ensure_anchors`가 태그 불일치를 보고
다음 조회 때 자동 재검증한다. 로컬 PDF 대조라 LLM 재과금 없음).

**v2 개정 (2026-08-09)**: 대시 통일을 NFKC **결과에도** 적용한다. 위/아래첨자 마이너스
(U+207B, U+208B)는 NFKC를 거치면 U+2212가 되는데 v1의 대시 폴딩은 원문 글자만 봐서 그때
놓쳤고, 그 결과 "10⁻³"는 U+2212로 "10−3"은 "-"로 남아 같은 뜻이 두 문자열로 갈렸다.
1:1 치환이라 오프셋 맵 정합은 유지된다(맵 단조성·범위·raw span 재정규화 일치를 검증).

부작용을 하나 안다: NFKC는 위첨자를 납작하게 만들므로 `10⁻³`와 하이픈 범위 `10-3`이 같은
문자열이 된다. 인용 매칭 층에서는 이 둘이 서로 매치될 수 있다. 그 대가는 값 가드가 아래
규칙으로 받는다.

## 값 가드 규칙 (verifier ev2)

값 가드는 문자열이 아니라 **수**를 본다. 양쪽(값, 인용)에서 수 토큰을 뽑아 값으로 비교하며,
허용하는 것은 표기 차이뿐이고 **오차 허용은 없다**(0.0045와 0.0046은 끝까지 다른 수).

- 동치로 인정: 소수 ↔ 과학표기(`0.0045` ≡ `4.5 × 10⁻³` ≡ `4.5e-3` ≡ `4.5·10⁻³` ≡ `4.5 x 10^-3`),
  후행 0(`500` ≡ `500.0`), 자릿수 구분 쉼표(`1000` ≡ `1,000`).
- 토큰을 통째로 소비하는 것이 **경계 인식 매칭**을 겸한다: "50"은 "1550"과 같아질 수 없고,
  부호가 토큰에 포함돼 "-40"과 "40"이 갈리며, 지수부(`10`, `-3`)가 독립 숫자로 새지 않는다.
  값 "1"이 "1,000"에 걸리지도 않는다. v1의 경계 정규식이 뚫려 있던 자리들이다.
- **앞자리 없는 소수는 수가 아니다**: `.5`를 소수로 받으면 논문에 흔한 `fig.5`, `p.45`,
  `sec.3`이 전부 수가 되어 원문이 말하지 않은 값이 올라간다.
- **뒤로도 경계를 둔다**: `10.5`는 `version 10.5.3`에 걸리지 않는다. 다만 문장 끝 마침표는
  숫자가 아니므로 `4.5. 다음 문장`은 정상 매치다.
- **지수 마커는 공백을 건너뛰지 않는다**: `10 x 10 5`는 배열 치수지 1e6이 아니고, `1 e 2`도
  100이 아니다.
- **읽을 수 없는 조각은 버린다(fail closed)**: 가수 없는 `10-3` 꼴(`10` + 부호 + 숫자)은
  지수인지 범위인지 정할 수 없으므로 **수 토큰을 아예 내지 않는다**. 10과 3을 독립 수로
  흘리면 원문이 말하지 않은 값이 검증으로 올라간다. 대가로 `10-20` 같은 범위 값은 수로
  대조되지 않지만, 인용이 같은 표기를 담고 있으면 리터럴 대조가 받아준다.
- **하지 않는 것**: 단위 환산(500 °C ↔ 773 K)과 백분율 환산. 표기가 아니라 의미의 문제다.

위조 false-verify=0 게이트가 위 경계 케이스들을 포함한다. 규칙을 완화하려면 먼저
`services/test_evidence_verifier.py`의 경계 테스트를 읽어라 — 각 줄이 실제로 뚫렸던 자리다.

## 회귀 지표 (tools/extraction_audit 패턴 재사용)

- quote candidate rate(LLM이 후보를 낸 비율), quote verification pass rate(exact+normalized),
  page match rate, value guard pass rate, **forged-quote false verify rate(=0 게이트)**
- 분모를 parser engine·match method·source_tag별로 분리 보고
- 12편 gold 한계 명시: 그림 gold가 자기참조 기반인 것과 동일하게, quote gold도 초기에는
  수작업 스팟체크 표본으로 시작 — 확대 계획은 Phase 2에서

## 알려진 위험 (상위)

1. LLM의 실제 축자 인용률 미실측 — 후보 자체가 paraphrase면 pass rate가 낮게 시작. 하네스
   1차 측정 항목으로 지정, 프롬프트에 "원문 그대로, 가장 짧은 연속 스팬" 강제.
2. pdf.js 좌표 변환(`convertToViewportRectangle`) 실환경 정합 미검증 — 하이라이트를 포함할
   경우 스파이크 태스크를 선행.
3. 다단 조판에서 union bbox 과대 가능 — 첫 매치 rect만 사용, 과대 시 페이지 점프로 폴백.
4. 검증기 예외가 recipe phase를 죽이면 안 됨 — 파라미터별 `verifier_error`로 격리, recipe
   데이터는 보존(Codex 실행 순서 5·6 채택).

## Definition of Done (Phase 1)

- 새 분석에서 explicit 파라미터의 상태·페이지·quote가 RecipeCard에 표시되고 클릭 시 해당
  페이지로 이동(D 결정에 따라 하이라이트 포함 여부 확정)
- 미검증 상태가 색상만이 아니라 텍스트+아이콘/툴팁으로 구분됨
- CSV export에 quote/page/display_status/검증 방법 열 보존(verified·unverified 모두)
- 위조 인용 false-verify=0 게이트 포함 pytest 통과, 캐시 히트 백필 경로 테스트 존재
- 실행하지 못한 검증(실PDF 대규모 pass rate 측정 등)은 보고서에 미검증으로 명시
