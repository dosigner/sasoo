# Sasoo GPT-6 Luna 프롬프트 A/B 실측 보고서

생성 실행: 2026-10-03 KST. 원문 검토/보고 완료: 2026-10-04 KST. cohort: `prompt-eval-20261001`.

이 문서는 [승인 전 준비 보고서](2026-10-01-gpt6-luna-prompt-measurement.md)의 후속 실측본이다. 고정한 준비 파일의 상태는 작성 당시 값으로 보존했다.

**최종 판정: `candidate_failed`.** 후보 B는 필수 질문 충족과 전체 사실 지지율에서 작은 관측 개선이 있었지만, 중대 오류가 늘고 엄격 논문 통과는 개선되지 않았다. 기존 6편 모두의 고정 품질 게이트를 통과하지 못했다. 이번 결과는 완료 조건 강화만으로 원문 충실성과 필요한 정보가 일관되게 개선된다는 결론을 지지하지 않는다.

계획한 **생성 12회와 count 요청 24회**를 모두 실행했고, 실패/timeout/불완전 응답은 0건이다. 12개 모두 strict JSON schema와 완료 상태를 통과했다. 독립 문맥의 AI 검토자 3명이 원문 PDF를 대조해 **2,322개 사실 출현, 3,461개 claim-ref 연결, 1,589개 문자열 필드, 72개 필수 질문 그룹**을 판정했다. 사람 전문가의 확인은 받지 않았다.

## 비교 결과

| 지표 | A: 기존 프롬프트 | B: 완료 조건 v1 |
|---|---:|---:|
| 엄격 논문 PASS | 0/6 | 0/6 |
| 필수 질문 충족 | 25/36 (69.44%) | 27/36 (75.00%) |
| 사실 지지율, 주장 출현 수 합산 | 1155/1167 (98.97%) | 1146/1155 (99.22%) |
| 사실 지지율, 논문별 비율 평균 | 98.79% | 99.13% |
| 출처 정확성, 연결 수 합산 | 938/1743 (53.82%) | 923/1718 (53.73%) |
| 출처 정확성, 논문별 비율 평균 | 61.30% | 60.30% |
| 중대 오류, 같은 근본 오류 중복 제외 | 3 | 4 |
| 지정된 미확인/비적용 Q6 충족 | 1/6 | 1/6 |
| full schema 및 응답 완료 | 6/6 | 6/6 |
| 생성비, 보고 usage × 단가 | US$0.05862716 | US$0.05789343 |

B의 필수 질문 충족은 **2개 그룹 증가(+5.56 percentage points)**, 사실 지지율은 **약 +0.25 percentage points**였다. 중대 오류는 **3개에서 4개**가 됐다. 사실을 덜 쓰는 답변을 높은 지지율만으로 개선이라고 판단하지 않았으며, 충족률/중대 오류/출처를 함께 판정했다. `no_clear_gain`은 상세 명세상 추가 조건 비교용 상태이므로, 이번 1차 품질 게이트 미달에는 `candidate_failed`를 적용했다.

논문별 결과는 다음과 같다. 사실/출처 셀은 각각 지지 수/분모이며, 화살표는 A→B다.

| 논문 | 필수 질문 충족 | 사실 지지 | 출처 지지 | 중대 오류 | 엄격 A / B |
|---|---|---|---|---|---|
| Bell | 4/6 → 5/6 | 131/137 → 138/141 | 75/84 → 79/92 | 1 → 2 | FAIL / FAIL |
| Diffusion Policy | 3/6 → 3/6 | 219/221 → 218/218 | 153/362 → 181/383 | 0 → 0 | FAIL / FAIL |
| 의료영상 리뷰 | 4/6 → 4/6 | 219/220 → 233/234 | 214/548 → 228/538 | 1 → 0 | FAIL / FAIL |
| Jinek 인간 세포 편집 | 6/6 → 6/6 | 194/194 → 154/155 | 206/280 → 143/210 | 0 → 0 | FAIL / FAIL |
| DESeq2 | 4/6 → 4/6 | 198/200 → 210/211 | 135/234 → 147/237 | 1 → 0 | FAIL / FAIL |
| 실물 UR5 | 4/6 → 5/6 | 194/195 → 193/196 | 155/235 → 145/258 | 0 → 2 | FAIL / FAIL |

숫자 원본은 [논문별 비교 CSV](assets/gpt-6-luna/prompt-eval-20261001/final-paper-comparison-20261003.csv)와 [집계 JSON](assets/gpt-6-luna/prompt-eval-20261001/comparison-summary-20261003.json)에 있다. 강점/약점, 비교, 절별 설명, 적용 제안의 사실도 전수 판정에 포함했다.

## 실제 개선과 퇴보

### DESeq2: 수치를 보존하면서 척도 오류가 해소됨

A(`response-009`)의 `key_results`는 모의실험 조건을 “실제 LFC” 2/3/4라고 썼다. 원문 PDF p9의 simulation 조건은 **true fold change 2/3/4배**다. log₂ 척도로 바꾸면 각각 1, 1.584963, 2이므로 두 표현은 같지 않다. B(`response-003`)는 같은 2/3/4배를 **실제 폴드 변화**로 정확히 보존했다. 해당 수치를 생략해서 오류가 사라진 사례가 아니다.

원문: *Simulation benchmark* 및 관련 비교 설명, PDF pp9–10. 생성 문구/주장: [바이오 판정](assets/gpt-6-luna/prompt-eval-20261001/reviews/bio/review.json)의 `response-009.C048`; [독립 교차확인과 계산](assets/gpt-6-luna/prompt-eval-20261001/reviews/dp_survey/crosscheck.md). 그러나 두 응답 모두 독립 표본과 기술 반복 구별(Q5), 지정한 완전한 재현 환경 미확인 범위(Q6)를 충분히 채우지 못해 필수 질문은 4/6이다.

### Bell: 단위 방향 조건은 보완됐으나 새 정의/방향 오류가 생김

A(`response-006`)는 방향벡터의 단위길이 조건이 없어 Q3가 실패했다. B(`response-004`)는 a/b를 단위 측정 방향으로 정의하고 같은 상관함수 정의역에서 c를 사용해 해당 조건을 충족했다. 전체 필수 질문은 4/6→5/6으로 증가했다.

B의 다른 문장에는 두 중대 오류가 남았다. `problem_definition`은 “그 추가 변수가 멀리 떨어진 측정 장치의 설정에 영향을 받지 않는다는 국소성 조건”이라고 썼다. 원문 II의 국소성은 **결과 A/B의 원격 설정 독립성**이며, λ 자체의 비영향과는 다르다. 또한 `key_results`는 식 (22)의 조건을 “수학적 상한”이라고 불렀다. 원문은 `4(ε+δ) ≥ √2−1`, 즉 `ε ≥ (√2−1)/4−δ`라는 하한이다. 식 자체를 맞게 쓰고 해설의 방향을 뒤집은 오류로 구분했다.

A도 정확하지 않았다. δ를 각도 폭으로 설명했지만 원문 식 (17)은 평균 내적과 원래 내적의 차이에 대한 상계를 정의한다. 원문: PDF pp2–5(인쇄 pp196–199), II/III/V, 식 (17)/(22). [이론 판정](assets/gpt-6-luna/prompt-eval-20261001/reviews/theory_ur5/review.json), [수식 교차확인](assets/gpt-6-luna/prompt-eval-20261001/reviews/dp_survey/crosscheck.md), [국소성 정의 교차확인](assets/gpt-6-luna/prompt-eval-20261001/reviews/dp_survey/crosscheck-definition.md).

### UR5: 독립 시행 정보는 보완됐으나 검증 범위와 차원을 혼동함

A(`response-001`)는 같은 초기 네트워크/목표열 각 5개를 설명했지만 실험 변형당 **5회 독립 시행**이라는 구성요소는 명시하지 않았다. B(`response-010`)는 이를 명시해 Q3를 충족했고, 필수 질문은 4/6→5/6이 됐다.

B의 `solution`은 계산 동시성/순서까지 바꾸어 성능을 비교했다고 설명했다. 원문 VI는 앞의 세 가설을 변형 실험으로 평가하고 병렬성은 전망으로 남긴다. `section_answers[2].explanation`과 `transfer_checks[1].paper_condition`에서는 6관절 과제의 0.7×0.5×0.4 m 손끝 공간을 6차원 작업 공간으로 불렀다. 원문 III는 이 경계를 **3차원**으로 정의한다. 치수는 맞고 관절 수와 공간 차원을 혼동한 것이므로 두 출현을 하나의 근본 오류로 셌다.

원문: PDF p2 III, p5 V, p6 VI. [UR5 판정](assets/gpt-6-luna/prompt-eval-20261001/reviews/theory_ur5/review.json), [선택 구절 교차확인](assets/gpt-6-luna/prompt-eval-20261001/reviews/dp_survey/crosscheck.md). 두 응답 모두 payload의 미확인을 빠뜨려 Q6는 실패했다.

### 나머지 세 편

- **Diffusion Policy:** B의 평가된 사실 218개는 모두 원문 지지를 받았다. A에는 causal attention 설명 및 실물 평가 횟수 범위의 결함이 있었다. 두 조건 모두 10 Hz→125 Hz 조건, UR5/Franka 제어 인터페이스 구분, T블록 질량/마찰계수의 미확인 범위 등 고정 구성요소가 부족해 3/6이다. [판정](assets/gpt-6-luna/prompt-eval-20261001/reviews/dp_survey/review.md).
- **의료영상 리뷰:** A는 *standard feed-forward neural networks with handcrafted features*라는 결합 제외조건을 독립된 표준 feed-forward 제외조건으로 넓혔다. B는 이 결합을 보존했지만 리뷰의 입력과 개별 학습 방법의 입력을 혼용한 문장은 근거 불충분/낮은 심각도로 남았다. 두 응답 모두 308편의 수치는 맞으나 그 정확한 수치를 지지하는 §5 출처 연결과 지정 Q6가 부족해 4/6이다. [원문 문구와 문맥 정정](assets/gpt-6-luna/prompt-eval-20261001/reviews/dp_survey/review.md).
- **Jinek 인간 세포 편집:** 두 응답 모두 핵심 여섯 질문을 충족했다. B는 사실 1개가 근거 불충분했고, 양쪽 모두 개별 claim-ref 연결에서 지지 범위가 부족한 사례가 있어 엄격 PASS는 아니다. 과거 실험의 Sanger 누락을 이번 A에 그대로 적용하지 않았다. [판정](assets/gpt-6-luna/prompt-eval-20261001/reviews/bio/review.md).

각 판정의 생성 문구, JSON 경로, 원문 위치, 짧은 근거와 이유는 [사실 판정 CSV](assets/gpt-6-luna/prompt-eval-20261001/source-claims-20261003.csv), [출처 판정 CSV](assets/gpt-6-luna/prompt-eval-20261001/source-citations-20261003.csv), [필수 질문 판정 CSV](assets/gpt-6-luna/prompt-eval-20261001/required-judgements-20261003.csv)에 있다.

## 비용과 처리시간

| 논문 | A 생성비 USD | B 생성비 USD | A 생성 초 | B 생성 초 | B/A 시간 |
|---|---:|---:|---:|---:|---:|
| Bell | 0.00626192 | 0.00611755 | 60.323 | 58.817 | 0.9750 |
| Diffusion Policy | 0.01340305 | 0.01316018 | 91.403 | 94.941 | 1.0387 |
| 의료영상 리뷰 | 0.01325742 | 0.01327455 | 86.467 | 84.723 | 0.9798 |
| Jinek 인간 세포 편집 | 0.00766155 | 0.00666868 | 84.249 | 70.326 | 0.8347 |
| DESeq2 | 0.01091742 | 0.01179655 | 84.455 | 100.645 | 1.1917 |
| 실물 UR5 | 0.00712580 | 0.00687592 | 76.460 | 68.055 | 0.8901 |

총 생성비는 **US$0.11652059**이고, 보고 사용량과 공식 단가로 독립 재계산한 값이 요청별 정산과 모두 일치했다. B의 생성비 감소율 `1−sum(B)/sum(A)`는 **1.2515%**다. token-count API 요금은 여전히 미확인이므로 count를 포함한 청구 총비용과 그 감소율은 `null`로 보류했다. 비용 0으로 대체하지 않았다.

성공한 대응 쌍은 6개다. 생성 시간 B/A의 **중앙값은 0.97744**, 범위는 **0.83474–1.19170**이다. 이 여섯 단회 관측에서 중앙값 기준 약 2.26% 짧았지만, DESeq2에서는 B가 약 19.17% 길었다. 일반적인 속도 우세나 안정성을 뜻하지 않는다. 이번 실패 요청은 0개라 실패 요청 비용/시간 합계도 실제 0이며, 성공한 요청만 선별해 실패를 제외한 결과가 아니다.

측정 구간은 사전에 고정했다. 생성 시간은 SDK `Responses.create` 진입부터 응답/usage 수신까지로 count, 큐 대기, 원응답 파일 쓰기와 제품 파싱을 제외한다. 제품 전체 처리시간은 각 요청의 PDF 로딩 전부터 직전 count, 예약, 생성, 파싱/검증까지이며 초기 사전 count 12개는 별도다. 총 SDK 생성 구간 합계는 **960.863초**, count 합계는 **94.535초**, 직렬 cohort wall time은 **1,057.241초(약 17분 37초)**다. 원문 검토는 생성과 일부 겹쳐 진행됐고 이 생성 시간 합계에 포함하지 않는다.

모든 응답의 cache read는 0이고 cache write는 입력 tokens보다 3개 적었다. 입력/출력/cache write/read/reasoning 및 실제 tier를 [요청별 실행 CSV](assets/gpt-6-luna/prompt-eval-20261001/execution-requests-20261003.csv)에 보존했다. reasoning은 출력 tokens에 이미 포함돼 있어 비용에 다시 더하지 않았다. 장문 가산 임계값을 넘은 요청은 없고, 지역 가산 없는 standard endpoint와 `default` tier였다. 공식 단가는 실행일에 재확인했다. [공식 모델 가격](https://developers.openai.com/api/docs/models/gpt-6-luna), [확인 원문](assets/gpt-6-luna/prompt-eval-20261001/pricing/model-20261003.md).

승인은 생성 12회, count 24회, 이번 생성비 추가 상한 US$0.25였다. 기존 누적 US$1 제한도 유지했다. 정확한 사전 계산 예약 합계는 US$0.15870103이었고 실제 생성비는 그 아래였다. 누적 원장 생성비는 **US$0.73535317**, 미정산 생성 요청은 **0건**이다. 새 디렉터리로 과거 지출을 초기화하지 않았다. [승인 기록](assets/gpt-6-luna/prompt-eval-20261001/approval-20261003.json), [예약/정산 원장](assets/gpt-6-luna/prompt-eval-20261001/ledger.jsonl), [usage 독립 감사](assets/gpt-6-luna/prompt-eval-20261001/execution-audit-20261003.json).

## 고정 조건과 검증 근거

A/B 모두 `gpt-6-luna`, `high`, 원본 PDF 동일 바이트, `detail=high`, 단독 deep_dive, 이전 응답/분석 없음, undergrad, neutral system, 개인화 없음, 동일 strict schema/validator, 16,000 출력 상한이다. 생성에 외부 도구/검색은 없고 SDK/adapter/형식 복구 재시도도 0이다. 앱 캐시는 격리/우회했고 provider 캐시 옵션은 바꾸지 않았다. 요청/반환 모델은 12개 모두 `gpt-6-luna`였다. 존재하지 않는 날짜 snapshot을 만들지 않았다.

실행 순서는 theory A→B, robotics2 B→A, review A→B, bio1 B→A, bio2 A→B, robotics1 B→A로 유지했다. 시작 시점 A와 후보 v1, 평가 기준은 생성 중 변경하지 않았다. [원래 계획](assets/gpt-6-luna/prompt-eval-20261001/experiment-plan.json), [A](assets/gpt-6-luna/prompt-eval-20261001/prompts/baseline.txt), [B](assets/gpt-6-luna/prompt-eval-20261001/prompts/v1.txt), [diff](assets/gpt-6-luna/prompt-eval-20261001/prompts/baseline-to-v1.diff).

- A SHA-256: `af94abf1b4181ca13879bad26bbf30b28f0f8700d8331be5eadecd89655d721e`
- B SHA-256: `d62965f16de40aea1bb9e8fe607c22a887012ad0a04eb614829ef56e4387e9d3`
- 소스 HEAD: `eb7db2c4c0220094bd27eb9c5c075a8f3ae38f82`, 보존한 dirty diff와 함께 사용.
- Python 3.14.6, OpenAI SDK 3.6.0, macOS arm64. release CI Python 3.12/패키지 환경 검증은 이번 범위 밖이다.

제품 요청을 생성 직전에 포착한 오프라인 검사에서 지시문을 제외한 app/wire 입력이 6쌍 모두 같았다. 실제 원응답의 모델/effort/cap/schema/tier/대화 상태/도구/usage를 다시 대조했다. full SDK 응답은 `*.provider.json`, 모델 원문과 정규화 usage는 `*.result.json`, 파싱 결과는 `*.validation.json`, SDK 시간은 `*.provider-timing.json`, count는 `counts/`에 있다. 원본 PDF base64를 요청 로그에 복사하지 않았다.

준비 단계의 관련 **101 tests와 7 subtests**, py_compile, 파일 해시 검사가 통과했다. 실행 뒤 사용량/비용/요청 지문, 원문 인용 substring, 모든 문자열 필드 coverage, claim/ref ID와 고정 6문항 연결도 검사했다. SDK 전체 응답은 `model_dump`의 내부 별칭 `schema_`를 사용해 최초 오프라인 감사가 KeyError로 중단됐고, 감사기의 읽기만 수정했다. 요청/원응답/점수 기준은 바꾸지 않았고 추가 API 호출도 없었다. [감사 수정 기록](assets/gpt-6-luna/prompt-eval-20261001/checks/execution-audit-initial-failure.json).

기존 자료 1,852개는 바이트 단위로 그대로이고 기존 campaign registry 1개에는 새 경로만 추가됐다. registry의 이전 바이트 prefix 해시가 원본과 일치한다. 사용자 tracked diff와 고정 파일 44개도 유지됐다. [보존 확인](assets/gpt-6-luna/prompt-eval-20261001/checks/post-execution-preservation.json).

## 판정 규칙, 블라인드와 한계

[고정 rubric](assets/gpt-6-luna/prompt-eval-20261001/evaluation-rubric.json)의 필수 질문은 논문별 여섯 **복합 그룹**이다. 그룹의 필수 구성요소가 모두 정확해야 1점을 주며 부분점수는 없다. 따라서 27/36은 원자 정보 75%라는 뜻으로 확대하지 않고, 고정한 복합 질문의 충족률로 읽는다. 이론의 Q6도 올바른 비적용 설명을 평가하므로 분모에 남는다.

사실 지지율은 모든 필드의 평가 가능한 **주장 출현 수**를 분모로 한다. 반복 사실도 출현별로 들어가므로 독립 시행 수와 다르다. 순수 제안/질문은 제외하지만 안에 포함된 사실 전제는 평가했다. 중대 오류는 같은 근본 오류의 여러 출현을 묶는다. 비율 분모가 0이면 N/A 규칙을 적용하며, 이번 최종 사실/출처 분모에는 0이 없다.

출처 정확성은 **개별 claim-ref 연결**의 지지율이다. 복수 출처를 묶은 경우 원칙적으로 각 주장과 각 locator를 대조하고, 생성문이 명시적으로 범위를 나누면 그 범위를 따른다. 따라서 출처 위치가 존재하면서도 연결된 특정 수치를 지지하지 않는 조합이 분모에 들어간다. 이를 사실 오류나 중대 환각 개수와 합치지 않았다. 출처가 붙지 않은 사실 출현은 A 428개, B 432개로 별도 기록했고, 출력되지 않은 인용을 정확한 인용으로 계산하지 않았다.

독립 문맥의 AI 검토자 3명에게 원본 PDF, 익명 응답과 고정 기준만 제공했다. A/B, 프롬프트, 사용량, 가격과 시간은 제공하지 않았다. 자료 디렉터리에 모델명이 포함돼 **모델 계열을 추정할 수 있으므로 모델명 완전 블라인드는 아니다.** 생성/집계 담당자는 실행을 위해 조건을 알았지만 원문 판정은 분리했다. [검토 경계 기록](assets/gpt-6-luna/prompt-eval-20261001/review-provenance.json).

판정 파일을 [해시로 봉인](assets/gpt-6-luna/prompt-eval-20261001/primary-review-seal.json)한 뒤 A/B와 연결했다. 정규화의 수학적 함의, 같은 상관함수 정의역의 단위 방향, 상위 범위의 오차 미확인 설명은 의미가 같으면 인정했다. 특정 단어의 일치 조건을 새로 추가하지 않았다. 문헌 리뷰의 입력에 관한 모호한 한 문장은 전체 문맥 확인 후 중대 오류에서 낮은 심각도로 정밀화했다. 출처 연결 23건은 고정된 명시적 범위 예외를 적용해 초안의 과도한 연결을 정정했으며 중복 제거는 아니었다. 공개 전 정정 이유는 각 검토 보고서에 보존했다.

선택한 주요 **6개 구절**은 다른 검토자가 원문을 다시 읽고 확인했다. Bell 식과 FC→log₂FC에는 독립 수치 검산을 적용했다. 전체 12개 응답을 두 번 전수 판정한 것은 아니며, 전문가 판정과의 false-pass/false-fail 보정은 수행하지 않았다. AI 검토자들의 동의 자체를 근거로 쓰지 않고 원문 위치/짧은 근거/계산을 연결했다.

이번 여섯 편은 이미 프롬프트 개선에 참고한 회귀 자료다. 논문당 1쌍뿐이므로 일반적 정확도, 안정성, 반복 실패 빈도, 다른 논문으로의 일반화를 주장하지 않는다. 실제 `visual→recipe→deep_dive` 체인, GUI, 저장 결과의 근거 링크 동작은 이번에 검증하지 않았다. 운영 프롬프트와 기본 모델 적용은 이번 실측과 별도의 의사결정으로 남겼다.

## 재현과 제출물

원문 판정과 usage 감사는 API를 호출하지 않고 다시 확인할 수 있다. 다음 명령은 고정된 소스/자료 상태에서 실행한다.

```bash
cd sasoo/backend
./.venv/bin/python ../../docs/validation/assets/gpt-6-luna/prompt-eval-20261001/audit_execution.py --check
./.venv/bin/python ../../docs/validation/assets/gpt-6-luna/prompt-eval-20261001/audit_reviews.py --require-complete
./.venv/bin/python ../../docs/validation/assets/gpt-6-luna/prompt-eval-20261001/summarize_comparison.py --check
./.venv/bin/python ../../docs/validation/assets/gpt-6-luna/prompt-eval-20261001/reviews/theory_ur5/bell-check.py
```

[최종 검사 결과](assets/gpt-6-luna/prompt-eval-20261001/checks/final-delivery/results.json)에 재계산과 링크/인용 무결성 검사를 기록했다. `FINAL-SHA256SUMS`는 최종 제출물의 무결성을 검사한다. 프롬프트/원문/스키마/코드가 바뀌면 기존 검증을 새 상태에 적용하지 않는다. PDF 임시 경로가 사라졌다면 [원본 manifest](assets/gpt-6-luna/prompt-eval-20261001/sources-verified.json)의 고정 버전과 해시로 복구한다. 새 모델 생성은 위 재현 명령에 포함되지 않으며 완료한 cohort를 재발행하지 않는다.

- [계획과 고정 기준](assets/gpt-6-luna/prompt-eval-20261001/experiment-plan.json), [프롬프트 diff/hash](assets/gpt-6-luna/prompt-eval-20261001/prompts/baseline-to-v1.diff)
- [12개 최종 요청 상태](assets/gpt-6-luna/prompt-eval-20261001/final-request-status-20261003.jsonl), [실행/사용량/비용 CSV](assets/gpt-6-luna/prompt-eval-20261001/execution-requests-20261003.csv), [원장](assets/gpt-6-luna/prompt-eval-20261001/ledger.jsonl)
- [원문 사실 판정](assets/gpt-6-luna/prompt-eval-20261001/source-claims-20261003.csv), [출처 판정](assets/gpt-6-luna/prompt-eval-20261001/source-citations-20261003.csv), [필수 질문 판정](assets/gpt-6-luna/prompt-eval-20261001/required-judgements-20261003.csv)
- [논문별 A/B 비교](assets/gpt-6-luna/prompt-eval-20261001/final-paper-comparison-20261003.csv), [전체 집계](assets/gpt-6-luna/prompt-eval-20261001/comparison-summary-20261003.json)

재사용할 핵심은 **많은 문장이 맞는지, 필요한 정보가 채워졌는지, 중요한 정의가 틀리지 않았는지를 따로 측정하는 것**이다. 이번에는 B의 평균 지표 일부가 좋아져도 국소성의 주어, 부등식 방향, 공간 차원의 오류가 남았다. 같은 PDF와 봉인한 판정표/계산으로 확인할 수 있으며, JSON 통과나 전체 지지율만으로 이런 오류를 가리는 것이 주요 함정이다.
