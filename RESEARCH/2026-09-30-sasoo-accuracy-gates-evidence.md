# GPT-6 Luna 도입과 프롬프트 변경 후 검증 원칙 (2026-09-30)

공식 OpenAI 문서의 평가, Structured Outputs, agent 검증 지침을 읽고 Sasoo에 적용할 최소 검증 절차를 정리했다. 아래 공식 원칙은 일반 API/agent 지침이다. 이 문서만으로 GPT-6 Luna의 모델별 지원 기능, 추론 강도, PDF 정확성을 확인한 것은 아니다. 모델별 문서와 실제 Sasoo 경로는 별도 확인이 필요하다. 유료 생성 실행과 운영 코드 변경은 수행하지 않았다.

## 1. 프롬프트를 코드에서 버전 관리하고, 변경 전에 비교 기준을 고정한다

**직접 확인한 내용.** OpenAI는 모델 계열 안에서도 snapshot에 따라 결과가 달라질 수 있으므로 모델 snapshot 고정과 평가 suite를 권고한다. 현재 문서는 생산 프롬프트를 애플리케이션 코드에서 관리하고, 변경 전 대표 fixtures와 평가를 준비하도록 안내한다. 확인한 원문: “Store production prompts in your application code”. [Prompt engineering](https://developers.openai.com/api/docs/guides/prompt-engineering#version-prompts-in-code)

**Sasoo 적용 제안.** 기존과 변경 프롬프트를 같은 PDF, 모델, effort, 스키마, 입력 전달 경로로 비교한다. prompt 버전/해시와 실제 모델 ID, 입력 경로를 결과에 남긴다. 모델과 프롬프트를 함께 바꾸는 경우에는 기존 모델+기존 프롬프트, 새 모델+기존 프롬프트, 새 모델+새 프롬프트를 구분해야 개선 원인을 해석할 수 있다. 이 비교 설계는 제안이며 아직 실측하지 않았다.

## 2. JSON 형식과 사실 정확성을 각각 검증한다

**직접 확인한 내용.** Structured Outputs는 지정 JSON Schema 준수를 위한 기능이다. 입력에서 요구 값을 구할 수 없을 때의 동작을 지시하지 않으면, 모델이 스키마를 채우려다가 환각을 만들 수 있다고 설명한다. 원문은 “Structured Outputs can still contain mistakes.”라고 명시한다. [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs#tips-and-best-practices)

**Sasoo 적용 제안.** 핵심 주장에는 원문 위치, 짧은 근거, 수치/단위/조건을 같이 요구한다. 논문에서 찾지 못한 값은 `null` 또는 명시적인 `not_found` 상태를 허용한다. 실제 존재하는 인용문인지 확인하는 검사와, 그 인용문이 주장 전체를 지지하는지 확인하는 검사를 구분한다. 근거 추출 후 설명을 작성하는 순서는 시험할 후보이며, 호출을 나눈다는 사실만으로 정확성이 보장되지는 않는다.

## 3. 검증 agent는 원문을 보고 좁은 질문을 판정하게 한다

**직접 확인한 내용.** 공식 평가 가이드는 열린 설명 생성보다 pairwise 비교, 분류, 구체 기준 채점을 권고한다. 자동 채점은 인간 판단과 맞춰야 하며 LLM judge에는 응답 순서, 길이 편향이 있다. 또한 agent를 여러 개로 나눌지는 eval로 결정해야 한다고 안내한다. 원문: “Use human feedback to calibrate automated scoring.” [Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)

공식 grader 지침도 답변, 전문가 답변, ground-truth grades를 함께 준비해서 채점기가 품질 차이를 제대로 구분하는지 평가하도록 설명한다. 높은 자동 점수가 전문가 평가와 어긋나는 grader hacking도 별도로 경고한다. [Graders](https://developers.openai.com/api/docs/guides/graders#how-to-write-grader-prompts)

**Sasoo 적용 제안.** 검증 입력은 생성된 설명과 원문 근거다. 질문은 “이 수치, 조건, 비교 대상이 해당 원문에 의해 지지되는가?”처럼 좁힌다. 결과는 `supported`, `contradicted`, `insufficient_evidence`로 구분하고 판정 근거를 남긴다. 같은 모델의 재확인이나 상위 모델의 검토만으로 독립 검증이 완료됐다고 판단하지 않는다. 소수의 전문가 채점 사례로 false pass와 false fail을 확인한 뒤 자동 판정 범위를 넓힌다.

## 4. 최종 점수와 단계별 실패를 함께 본다

**직접 확인한 내용.** 공식 agent 평가 문서는 디버깅 단계에서 trace를 먼저 보고, 반복 비교가 필요해지면 dataset/eval run으로 옮기라고 안내한다. Trace는 모델 호출, tool 호출, guardrail, handoff를 포함하는 실행 기록이다. 원문 소제목은 “Start with traces when you are still debugging behavior”이다. [Evaluate agent workflows](https://developers.openai.com/api/docs/guides/agent-evals)

**Sasoo 적용 제안.** 원문 전달, 근거 추출, 설명 생성, 검증에서 어디가 실패했는지를 나눈다. 최소 평가 항목은 다음과 같다. 수치는 공인 기준이 아니라 제품 목표에 맞춰 결정할 항목이다.

| 항목 | 확인할 내용 |
|---|---|
| 사실 지지율 | 평가 대상 주장 중 원문이 지지하는 비율 |
| 핵심 정보 충족 | 사전에 정의한 핵심 결과/조건 중 정확히 포함된 비율 |
| 중대 오류 | 핵심 수치, 단위, 방향, 비교 대상 오류 수 |
| 유보 동작 | 근거가 없는 정보를 지어내지 않고 미확인으로 표시하는지 |
| 형식/렌더 | 스키마 준수와 실제 표시 성공 |

사실 지지율만 높으면 필요한 설명을 모두 생략한 출력이 높은 점수를 받을 수 있다. 그러므로 완전성과 유보를 같이 본다. 원문에 없는 정보와 원문에 있는데 누락한 정보도 구분한다. 이 항목 설계는 Sasoo 제안이다.

## 5. 변경 뒤에는 회귀 사례와 미사용 논문을 따로 검증한다

**직접 확인한 내용.** 공식 평가 가이드는 대표 사례, edge/adversarial 사례, 전문가 label과 held-out 평가를 예시로 들고, 모든 변경에 평가를 반복하도록 안내한다. 프롬프트 최적화 문서는 변경된 프롬프트가 특정 입력에서 기존보다 나빠질 수 있으므로 생산 사용 전 평가와 수동 검토를 요구한다. 원문: “Always evaluate and manually review optimized prompts before using them in production.” [Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices), [Prompt optimizer](https://developers.openai.com/api/docs/guides/prompt-optimizer)

**Sasoo 적용 제안.** 이미 실패 분석과 프롬프트 개선에 쓴 논문은 회귀 검사에 둔다. 최종 일반화 평가는 프롬프트 개선에 쓰지 않은 논문으로 별도 수행한다. PDF 원문은 정상 입력이지만, 평가 정답과 평가용 위치 힌트는 생산 프롬프트에 섞지 않는다. 한 번 실패한 실행만 고치는 대신 동일 설정 반복에서 실패 빈도를 확인한다. 생성 비용이 발생하는 새 평가 실행은 별도 결정 대상이다.

## 플랫폼 선택에 영향을 주는 현재 공지

OpenAI는 Evals 플랫폼을 2026-10-31 read-only로 전환하고 2026-11-30 dashboard/API를 종료할 예정이라고 공지한다. 재사용 prompt 객체의 `v1/prompts`도 2026-11-30 종료 예정이다. 평가 원칙과 특정 서비스 도입은 구분해야 한다. Sasoo는 코드에 저장된 프롬프트와 기존 로컬 비교 harness를 활용하는 방향이 합리적이다. 이 마지막 문장은 적용 제안이다. [Deprecations](https://developers.openai.com/api/docs/deprecations#2026-06-03-evals-platform)

## 보조 연구 근거와 한계

[FActScore, EMNLP 2023](https://arxiv.org/abs/2305.14251)은 긴 생성을 atomic facts로 나누고 신뢰할 근거가 지지하는 사실의 비율을 측정한다. 주된 실험은 인물 전기이며 Sasoo의 과학 논문, 수식, PDF 입력에 대한 검증 결과는 아니다. [ALCE, EMNLP 2023](https://arxiv.org/abs/2305.14627)은 fluency, correctness, citation quality를 구분한다. 이를 참고해 주장 정확성과 인용 품질을 분리할 수 있지만, 인용을 붙이는 것만으로 과학 요약의 정확성이 보장되지는 않는다. 여기서는 두 논문의 원문 초록에 명시된 방법 정의만 사용했다.

핵심 재사용 원칙은 모델이 준수하는 출력 형식, 원문이 지지하는 사실, 사용자가 필요한 정보의 충족을 각각 확인하는 것이다. 동일 입력 비교와 미사용 논문 검증으로 재현할 수 있다. 가장 흔한 함정은 형식 검사 통과나 자동 reviewer 점수를 사실 정확성의 독립 증거로 해석하는 것이다.
