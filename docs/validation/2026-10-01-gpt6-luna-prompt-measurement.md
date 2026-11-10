# Sasoo GPT-6 Luna 프롬프트 비교 준비 보고서

작성일: 2026-10-01. 최종 상태: **`awaiting_paid_approval`**.

오프라인 준비 조건을 충족했다. 기존 프롬프트 A와 완료 조건을 강화한 후보 B 하나, 실제 제품 경로에서 포착한 12개 요청, 평가 기준과 비용 추정을 고정했다. **이번 생성 0회, token-count API 0회**다. 따라서 원문 정확성, 정보 충족, 출처 정확성, 생성 시간과 비용 개선의 실측 결론은 아직 없다. 과거 응답을 이번 A로 사용하지 않았다.

현재 세션에는 이 cohort의 유료 호출 범위와 지출 상한을 승인한 메시지가 없다. [실험 상세 명세](../../RESEARCH/2026-10-01-gpt6-luna-measurement-metaprompt.md)의 “새 예산 승인이 없는 경우 … `awaiting_paid_approval`로 인계한다”에 따라 준비 자료를 제출한다. 운영 적용은 별도 결정이다.

## 고정한 비교

질문은 “완료 조건을 강화한 프롬프트가 기존 프롬프트보다 원문에 충실하고 필요한 정보를 더 정확하게 포함하는가?”다.

| 항목 | 고정값 |
|---|---|
| 모델 / effort | `gpt-6-luna` / `high` |
| A | 시작 시점 `_DEEP_DIVE_INSTRUCTION`, 3,694자 |
| B | 조사 보고서 후보 블록을 기존 규칙, 필드, 분야별 계약 앞에 결합한 v1, 4,362자 |
| 입력 | 동일한 원본 PDF 전체, `detail=high`; PDF에 포함된 부록만 제공 |
| 범위 | 단독 `deep_dive`, 이전 응답 ID 없음, 앞 단계 결과/스크리닝/인용 digest 없음 |
| 독자 | `undergrad`, 공용 한국어 규칙과 neutral system, 개인화 없음 |
| schema / validator | 현재 strict wire schema와 제품 validator 공통 |
| 출력 / tier | 16,000 tokens / `default` |
| 검색 / 재시도 | 생성 도구 없음, SDK/adapter/형식 재생성 0회 |
| 캐시 | 앱 캐시 우회, provider 캐시 설정 유지 및 실제 사용량 기록 |
| 실행 | 한 프로세스에서 직렬, 논문당 A/B 각 1회 |
| 순서 | theory A→B, robotics2 B→A, review A→B, bio1 B→A, bio2 A→B, robotics1 B→A |

B는 역할/완료 기준을 명시하는 도입부로 교체하고, 기존 `규칙:`부터 분야별 관점까지 그대로 유지했다. 문장 수를 편집 목표로 낮추고 지표 정의, 조건, 중요한 미확인 사항을 우선한다. 논문별 정답, 실패 정답이나 원문 위치 힌트를 추가하지 않았다. 기존 문구에 이미 있던 일반적인 질량/마찰/출처 규칙은 보존했다. 여러 문구가 함께 변하므로 향후 관측된 차이를 특정 한 문장만의 효과로 분해하지 않는다.

- A SHA-256: `af94abf1b4181ca13879bad26bbf30b28f0f8700d8331be5eadecd89655d721e`
- B SHA-256: `d62965f16de40aea1bb9e8fe607c22a887012ad0a04eb614829ef56e4387e9d3`
- [A 원문](assets/gpt-6-luna/prompt-eval-20261001/prompts/baseline.txt), [B 원문](assets/gpt-6-luna/prompt-eval-20261001/prompts/v1.txt), [프롬프트 diff](assets/gpt-6-luna/prompt-eval-20261001/prompts/baseline-to-v1.diff)
- [실험 계획](assets/gpt-6-luna/prompt-eval-20261001/experiment-plan.json), [12개 실제 제품 요청과 조건 비교](assets/gpt-6-luna/prompt-eval-20261001/offline-plan.json), [평가 기준](assets/gpt-6-luna/prompt-eval-20261001/evaluation-rubric.json)

## 기준 상태와 문서 차이

소스 HEAD는 `eb7db2c4c0220094bd27eb9c5c075a8f3ae38f82`, branch는 `main`이다. 작업 시작 시 tracked 변경 9개와 기존 untracked 자료를 보존했다. 이번 구현은 새 [prompt_compare.py](../../sasoo/backend/tools/prompt_compare.py)와 [통합 검사](../../sasoo/backend/tools/test_prompt_compare.py)이며 운영 프롬프트/모델/DB를 수정하지 않았다. 기존 변경 diff는 종료 시점에도 바이트 단위로 같고, 과거 조사/평가 자료 1,853개 해시도 모두 유지됐다. [보존 검사](assets/gpt-6-luna/prompt-eval-20261001/checks/preservation.json), [시작 diff](assets/gpt-6-luna/prompt-eval-20261001/baseline/working-tree.diff), [이번 구현 diff](assets/gpt-6-luna/prompt-eval-20261001/implementation.diff).

실행 환경은 macOS 27 arm64, Python 3.14.6, OpenAI SDK 3.6.0, Pydantic 2.13.5, AnyIO 4.12.1이다. 문서의 release CI Python 3.12 환경과 다르며 패키지 검증을 주장하지 않는다. [환경/예산 스냅샷](assets/gpt-6-luna/prompt-eval-20261001/baseline/environment-budget.json)과 baseline/source에 실제 읽은 제품 코드를 보존했다.

확인한 차이는 다음과 같다.

1. 조사 보고서의 baseline hash와 현재 프롬프트가 정확히 일치한다. 운영 `MODEL_LUNA`는 여전히 `gpt-5.6-luna`다. 기존 dirty 변경은 이미지 생성/가격 및 설정 UI 관련이며, deep_dive의 변경은 아니다.
2. 과거 비교 보고서의 누적 생성비 US$0.58928133 이후 5.6 Luna source-audit pilot US$0.02955125가 추가됐다. 현재 누적은 **US$0.61883258**, 미정산 생성 요청은 0건이다. pilot을 6 Luna 품질 증거로 사용하지 않는다.
3. manifest의 `/tmp/sasoo-v101-papers/` PDF 6개가 모두 사라져 있었다. 같은 버전을 다시 받아 6/6의 SHA-256과 페이지 수를 확인했다. bio1 기본 URL과 PMC 경로는 HTML을 반환했으며 이를 PDF로 사용하지 않았다. 공식 CDN에서 기존 해시와 일치하는 파일을 확보했다. [복구 기록](assets/gpt-6-luna/prompt-eval-20261001/source-retrieval.json), [bio1 복구](assets/gpt-6-luna/prompt-eval-20261001/source-retrieval-bio1-recovery.json), [확인된 원본](assets/gpt-6-luna/prompt-eval-20261001/sources-verified.json).
4. 기존 `dry-run`은 count API를 호출한다. 새 오프라인 경로는 `RequestGate`에서 정지하며 네트워크 접근도 차단한다. 기존 SDK count 함수의 기본 재시도도 실제 실행 시에는 0으로 제한한다.
5. 제품 요청의 끝 문장은 앞선 체인/digest를 언급하지만 이번 입력에는 그런 자료가 없다. A/B 모두 같은 문장을 유지했다. 새로운 간소화 입력으로 제품 경로를 대체하지 않았다.
6. 기존 raw 기록은 정규화된 응답이다. 새 연결은 실제 실행 시 전체 SDK 응답과 SDK 호출 시간을 추가 보존한다. 기존 검토 pack의 무작위 순서는 seed를 고정할 수 없어, 이 실험은 `20261001`을 사용한다.
7. 현재 로컬 validator는 확장 필드, 중복 키와 제어문자를 검사하지만 최상위 모든 필드나 원문 진실성을 독립 검증하지 않는다. A/B에 같은 validator를 쓰되 별도 형식/원문 판정에서 이 한계를 유지한다.

## 오프라인 검증 결과

원본 PDF 6편을 사용해 제품 `invoke_product → _run_deep_dive → _run_chain_stage`의 생성 직전 요청 12개를 포착했다. 프롬프트 변수 하나를 실험 프로세스 안에서만 바꾸고 매번 복원한다. 의도한 지시문을 같은 자리에서 제거한 후 모든 app 인자와 wire 요청을 비교했으며 **6쌍 모두 동일**했다. 키에는 A/B 조건을 넣어 충돌을 막았다. PDF 본문/base64를 요청 로그에 중복 저장하지 않고 원본 파일 참조와 해시를 기록했다.

공통 app schema hash는 `be3010c070a8ca472155761f4f588fbddc7bd8e773e60aaa6d0b436441fe0e39`, wire schema hash는 `33e7d3cdefd40e28bddb0e210f3cf1822975a85b75407b4c0edc13a7dfb73661`다. [schema 파일](assets/gpt-6-luna/prompt-eval-20261001/schemas/wire.json)도 별도로 확인할 수 있다. 이 두 값은 `luna_compare.digest`의 정렬된 JSON 객체 해시이며, pretty JSON 파일 자체의 바이트 해시와는 다르다.

검사 결과는 **101 tests 및 7 subtests 통과**, `py_compile` 통과, 최종 12개 요청의 offline 재포착 비교 통과다. SWIG/PyMuPDF deprecation 경고 5개가 있었고 실패는 없다. 새 통합 검사는 모의 provider로 12회 생성/24회 count 경로, 승인 없는 실행 차단, malformed 응답 보존, 원장 정산, timeout의 불명 비용 보존/후속 중단, 재발행 금지, 블라인드 pack의 metadata 제거를 검사했다. 이 횟수는 외부 API 호출이나 실제 품질 측정이 아니다. [명령/종료 코드](assets/gpt-6-luna/prompt-eval-20261001/checks/sealed-results.json), [검사 출력](assets/gpt-6-luna/prompt-eval-20261001/checks/sealed-1.txt).

최초 검사에서 PDF 경로가 없어 중단된 사실과 복구 이력도 보존했다. [준비 중 실패](assets/gpt-6-luna/prompt-eval-20261001/checks/preparation-failures.json).

## 사전 품질 판정 규칙

[기존 원문 기준](2026-09-22-v1.0.1-paper-evidence.md)의 Q1~Q6를 논문별 6개 복합 항목으로 고정했다. 각 항목에 나열된 필수 구성요소가 모두 정확해야 1점이며 부분 점수는 없다. **논문별 분모 6, 조건별 전체 분모 36**이다. 원문 위치와 허용 범위는 [필수 기준 CSV](assets/gpt-6-luna/prompt-eval-20261001/required-criteria.csv)에 있으며, 6편 밖의 일반화 기준으로 해석하지 않는다.

Q2의 실제 clone/Sanger 확인, UR5의 return 정의, 리뷰 308편의 정확한 근거 위치 등 기존 판정의 해석도 명시했다. 특정 오답 문자열만 찾는 검사로 대체하지 않는다. 정답과 위치는 평가자 자료이고 생성 입력에는 들어가지 않는다.

| 지표 | 고정한 판정 |
|---|---|
| 엄격 PASS | 응답 완료/형식 통과, Q1~Q6 모두 충족, 모든 서술 필드에 새 사실/출처 결함 없음 |
| 사실 지지율 | 원문으로 지지되는 주장 등장 수 / 평가 가능한 주장 등장 수. 복합 문장을 독립 판정 가능한 사실로 나누되 수치의 단위/조건/대상은 떼어내지 않음 |
| 필수 충족률 | 정확하게 충족한 복합 Q 항목 수 / 6. 문구 위치는 어느 기존 필드여도 됨 |
| 출처 정확성 | 실제로 주장을 지지하는 claim-ref 연결 수 / 출력된 연결 수. 위치 존재와 의미 지지를 별도 기록 |
| 중요 미확인 정보 | 지정된 Q6와 제공 범위를 정확히 설명. 다른 unknown으로 대체하거나 원문에 있는 정보를 없다고 하면 실패 |
| 중대 오류 | 수치, 단위, 부호, 방향, 지표 정의, 비교 대상, 방법 변형, 실물/시뮬레이션 범위 오류. 누락과 작은 위치 결함은 따로 기록 |
| 형식/완료 | JSON, required 필드, 중복 키, 제어문자, 배열/enum 계약, provider 상태, cap 도달 여부 |

단순 제안/질문 자체는 사실 주장 분모에서 제외하지만 그 안의 사실 전제는 평가한다. 명시한 추론도 근거와 도출이 타당해야 한다. strengths/weaknesses, 비교, 절별 설명, 적용 제안까지 모두 검사한다. 출처를 여러 주장에 붙였으면 각 주장을 실제로 지지하는지 확인한다. 출처가 없는 주장 비율도 별도 기록한다.

평가 대상이 0개인 비율은 `N/A`다. 미실행은 `not_run`이며 0%나 관측된 N/A로 바꾸지 않는다. 발행됐으나 빈 답변이면 필수 충족은 0/6, 사실/출처 비율은 N/A, 형식/엄격 판정은 FAIL이다. 이론의 실험 시행 수 등은 비적용으로 설명해야 하며 임의 결측 실험값을 강요하지 않는다. theory Q6 자체는 정확한 비적용 설명을 평가하므로 분모에서 빼지 않는다.

응답 12개를 고정 seed로 섞고 A/B, 모델, 가격과 시간을 숨긴 pack을 평가자에게 제공한다. 각 판정은 생성 문구, 출력 위치, 원문 위치, 짧은 근거와 심각도를 연결한다. 판정 파일과 해시를 고정한 뒤 조건을 공개한다. 현재 판정과 독립 검증은 **미시작**이며 자기 검토만 이루어지면 독립 검증 미완료로 표시한다. JSON 통과나 reviewer 동의로 원문 정확성을 인정하지 않는다.

## 호출 수와 비용 자료

공식 GPT-6 Luna 단가는 2026-10-01 확인 기준 100만 tokens당 일반 입력 US$0.10, cached read US$0.01, cache write US$0.125, 출력 US$0.50이다. 272k 초과 입력은 전체 요청의 입력/cache 2배, 출력 1.5배이며 지역 endpoint는 10% 가산이다. 이 계획은 standard endpoint와 `default` tier를 고정한다. [공식 모델 가격](https://developers.openai.com/api/docs/models/gpt-6-luna), [공식 가격표](https://developers.openai.com/api/docs/pricing).

아래 예약 추정은 입력 전체를 cache write 요율로, 출력을 16,000 상한으로 계산했다. 입력은 과거 동일 PDF/schema/system의 실제 입력량을 참고하고 B에 늘어난 UTF-8 바이트 1,548을 토큰 여유분으로 더한 뒤 20% 여유를 적용했다. **현재 정확한 token count나 보장된 비용 상한이 아니다.** PDF 인코딩/토큰화가 바뀌면 추정이 달라질 수 있으며 승인 후 정확히 count한다.

| 논문 | 과거 입력 tokens | A 입력 여유 추정 | B 입력 여유 추정 | A 예약 추정 USD | B 예약 추정 USD |
|---|---:|---:|---:|---:|---:|
| theory | 21,176 | 25,412 | 27,269 | 0.0111765 | 0.01140863 |
| robotics2 | 63,485 | 76,182 | 78,040 | 0.01752275 | 0.017755 |
| review | 68,260 | 81,912 | 83,770 | 0.018239 | 0.01847125 |
| bio1 | 22,977 | 27,573 | 29,430 | 0.01144663 | 0.01167875 |
| bio2 | 50,012 | 60,015 | 61,872 | 0.01550188 | 0.015734 |
| robotics1 | 23,763 | 28,516 | 30,374 | 0.0115645 | 0.01179675 |

총 생성비 예약 추정은 **US$0.17229564**다. 지역 가산을 가정하면 US$0.189525204이지만 이 실행기의 선택된 조건은 아니다. 과거 비용 US$0.61883258과 합치면 US$0.79112822이며, 기존 US$1 생성 원장 한도 아래 추정 잔액은 US$0.20887178이다. 현재 기록상 잔액 US$0.38116742가 새 호출 승인으로 전환되는 것은 아니다.

승인 요청 범위는 **생성 12회, token-count 요청 24회(전체 사전 계산 12회 + 생성 직전 재확인 12회), 이번 생성비 추가 상한 US$0.25**다. 기존 누적 US$1 제한도 그대로 유지한다. 재시도, 추가 reviewer, 반복 실험은 이 범위에 포함하지 않는다.

Token-count 문서는 같은 Responses 입력을 지원한다고 설명하지만, 확인한 count 안내/가격표에서 별도 요금을 찾지 못했다. **무료로 확정하지 않았고, US$0.25는 생성비 상한이며 count까지 포함한 청구서 총액 보장이 아니다.** 요청마다 count 비용을 `null / unknown_tariff`로 보존한다. count 호출 자체도 명시적인 승인 범위에 들어가야 한다. 최종 청구서 총비용과 비용 감소율은 이 요금/과거 count 비용이 정산되기 전까지 확정하지 않는다. [공식 token-count 안내](https://developers.openai.com/api/docs/guides/token-counting), [전체 추정 자료](assets/gpt-6-luna/prompt-eval-20261001/cost-estimate.json).

## 측정 경계와 실패 처리

`provider-timing.json`의 `generation_seconds`는 SDK `Responses.create` 진입부터 응답/usage 수신 또는 예외까지다. count, 실행 큐 대기, 원응답 파일 쓰기와 제품 파싱은 제외한다. 기존 `LiveGate.result.seconds`는 큐 대기/adapter/일부 기록 작업을 포함하므로 별도 `gate_seconds`로 해석한다.

`total_processing_seconds`는 해당 생성 시도의 PDF 로딩 직전부터 직전 count, 예약, 생성, 파싱/검증까지다. 전체 cohort 사전 count 12회는 별도로 측정한다. 전체 wall time은 `paid-start.at`부터 마지막 validation 종료 또는 중단 시점까지이며 준비 작업과 사람의 검토 시간은 별도다.

생성 전에 기존 `BudgetJournal`에 예약하고, 실제 사용량/반환 모델/tier로 정산한다. 실패, timeout, incomplete, malformed를 보존한다. 사용량이 불명하거나 예약을 넘으면 미정산으로 남기고 후속 유료 호출을 멈춘다. 출력에 포함된 reasoning을 다시 합산하지 않는다. SDK 원응답, 정규화 응답, 제품 파싱 결과, count 기록과 시간은 조건이 포함된 동일 key로 연결한다.

입력과 조건을 정확히 count한 뒤 **전체 12회 예약 합계**가 새 생성 상한과 누적 원장 한도 안에 있는지 검사한다. 한도를 넘으면 생성 전에 중단한다. 실행 중 파일을 덮어쓰거나 같은 cohort를 자동 재발행하지 않는다. 중단 후 잔여 실행을 재개하려면 기존 발행/원장 상태를 확인해야 하며 현재 CLI는 재발행 방지를 위해 `paid-start.json`이 있는 실행의 재시작을 거부한다.

## 현재 논문별 결과와 산출물

| 논문 | 순서 | A | B | 원문 판정 / 비용 / 시간 |
|---|---|---|---|---|
| theory | A→B | 미실행 | 미실행 | 미측정 |
| robotics2 | B→A | 미실행 | 미실행 | 미측정 |
| review | A→B | 미실행 | 미실행 | 미측정 |
| bio1 | B→A | 미실행 | 미실행 | 미측정 |
| bio2 | A→B | 미실행 | 미실행 | 미측정 |
| robotics1 | B→A | 미실행 | 미실행 | 미측정 |

[논문별 비교 CSV](assets/gpt-6-luna/prompt-eval-20261001/paper-comparison.csv)는 6행, [요청 상태](assets/gpt-6-luna/prompt-eval-20261001/request-status.jsonl)는 12행, [판정 대기표](assets/gpt-6-luna/prompt-eval-20261001/judgements-pending.csv)는 원문 위치가 연결된 72행이다. 모든 미실행 행에 사유를 채웠으며 생성 문구/점수/비용/시간을 만들어 넣지 않았다. 원응답, 실제 usage, 블라인드 판정 pack은 생성 전이므로 존재하지 않는다. 새 [원장](assets/gpt-6-luna/prompt-eval-20261001/ledger.jsonl)은 발행 0건으로 비어 있고 [원장 상태](assets/gpt-6-luna/prompt-eval-20261001/ledger-state.json)가 과거 누적과 연결한다.

향후 비용은 실패 요청까지 모두 더하고, 성공한 대응 쌍의 시간은 따로 계산한다. 비용 감소율은 `1 - sum(cost_B)/sum(cost_A)`이며 불명 비용이 있으면 확정하지 않는다. 시간은 B/A 비율의 중앙값/최솟값/최댓값과 사용된 쌍 수를 보고한다. 필수 정보가 줄어든 답변을 높은 사실 지지율만으로 개선이라고 판정하지 않는다.

현재 개선/퇴보 사례는 **없음이 아니라 미관측**이다. 기존 6편의 통과 여부, 미사용 논문의 일반화, 실제 분석 체인, GUI 검증 모두 이번 실험에서 미측정이다. 유료 비교가 완료되면 고정된 우선순위에 따라 `comparison_incomplete`, `candidate_failed`, `regression_gate_passed` 중 판정하며, B의 부분 개선이 있어도 품질 게이트 실패를 통과로 바꾸지 않는다.

## 재현

[고정 파일 해시](assets/gpt-6-luna/prompt-eval-20261001/frozen-files.json)는 계획, 프롬프트, 평가 기준과 관련 소스의 변경을 검사한다. 저장된 준비를 재검사하는 명령은 네트워크/API를 사용하지 않는다. 저장된 PDF가 먼저 존재해야 한다.

```bash
cd sasoo/backend
./.venv/bin/python tools/prompt_compare.py --mode check \
  --campaign ../../docs/validation/assets/gpt-6-luna/prompt-eval-20261001
./.venv/bin/python -m pytest tools/test_luna_compare.py tools/test_prompt_compare.py \
  services/test_summary_contract.py services/llm/test_openai_client.py -q
```

PDF의 임시 경로가 정리됐다면 `sources-verified.json`의 고정 URL/버전으로 복구하고 원래 해시와 먼저 대조한다. bio1은 `source-retrieval-bio1-recovery.json`에서 `verified=true`인 CDN URL을 사용한다. 새 버전이나 HTML을 대신 입력하지 않는다. 프롬프트, rubric, 제품 코드와 SDK가 바뀌면 고정 검사에서 중단하며 새로운 실험으로 기록해야 한다. 모델 alias는 날짜 snapshot을 보장하지 않으므로 실제 반환 ID를 기록한다.

유료 실행은 **현재 승인되지 않았다**. 위 호출 범위가 명시적으로 승인된 뒤에만 다음 명령의 승인 인자를 사용할 수 있다. 인자 자체가 사용자 승인을 만들어내지는 않는다.

```bash
./.venv/bin/python tools/prompt_compare.py --mode run \
  --campaign ../../docs/validation/assets/gpt-6-luna/prompt-eval-20261001 \
  --approve-new-generation-usd 0.25 --approve-count-requests 24
```

이 실행은 로컬 제품이 사용하는 `OPENAI_API_KEY`와 기본 endpoint를 필요로 한다. 키나 인증 헤더는 산출물에 저장하지 않는다. 생성 후 `--mode review-pack`으로 평가자용 응답만 만든다. 평가자에게 `review-key.private.json`, offline-plan, 프롬프트, 비용/시간 자료를 제공하지 않는다. 판정 봉인 전에 조건을 공개하지 않는다.

준비 상태 자체의 재현성은 파일 해시, 동일 입력의 요청 비교, 모의 실패/원장 검사로 확인했다. 이는 모델이 원문을 정확히 읽었다는 증거와 다르다. 재사용할 원칙은 **입력의 동일성, 형식의 유효성, 원문 정확성, 필수 정보 충족을 각각 검증하는 것**이다. 이 실험에서 가장 큰 오판 위험은 단회 6쌍이나 JSON 통과를 안정성/일반화의 근거로 확대하는 것이다.
