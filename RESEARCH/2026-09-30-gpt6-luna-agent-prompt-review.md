# GPT-6 Luna의 agent 운용과 Sasoo 프롬프트 변경안

확인일: 2026-09-30. 대상 모델: `gpt-6-luna`. 공식 문서, Sol/Luna 안전 부록, 현재 Sasoo 코드를 대조한 조사다. 새 프롬프트의 정확성 개선은 아직 실측하지 않았다.

## 1. 결론

Sasoo에서는 기존 분석 체인을 유지하면서 각 역할의 완료 조건과 원문 대조를 강화하는 것이 첫 변경으로 적절하다. Luna는 범위가 분명한 작업에 배치하고, 백엔드가 입력 범위, 출력 계약, 작업 순서, 재시도와 예산을 관리한다. 모델에 자유로운 agent 분할이나 반복 검토를 맡기는 구조는 이번 변경의 전제가 아니다.

먼저 심층 분석 프롬프트의 필수 정보 충족을 개선하고 기존 6편으로 회귀를 검사한다. 추가 검증 호출은 그 다음 실험 변수로 둔다. 이렇게 해야 프롬프트 개선과 호출 수 증가의 효과를 나눠서 판단할 수 있다.

## 2. 공식 근거와 해석의 범위

### Luna에 직접 해당하는 내용

공식 모델 페이지는 Luna를 범위가 집중된 대량 작업에 적합한 효율 모델로 설명한다. 지원 effort는 `none`, `low`, `medium`(기본값), `high`, `xhigh`, `max`다. 도구를 사용하는 reasoning은 Responses로 구성하며, Chat Completions의 함수 호출은 `reasoning_effort=none`에서만 지원한다. 모델 페이지의 현재 snapshot 목록에는 `gpt-6-luna`만 있다. 없는 날짜 snapshot ID를 만들어 고정해서는 안 된다. [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)

안전 부록 Table 29의 Luna 비교는 다음과 같다. 점수는 길이 보정 점수이며, 답변 길이는 평균 문자 수다.

| 평가 | GPT-5.6 Luna | GPT-6 Luna | 해석 범위 |
|---|---:|---:|---|
| HealthBench Professional | 55.7 | 60.8 | 해당 의료 평가에서 개선 |
| HealthBench | 55.8 | 54.5 | 해당 평가에서 감소 |
| HealthBench Hard | 32.0 | 31.4 | 해당 평가에서 감소 |
| HealthBench 평균 답변 길이 | 1,930자 | 1,255자 | 기본 verbosity에서 약 35% 짧아짐 |

부록은 짧아진 답변과 평가 rubric의 세부 정보 충족 감소가 함께 나타났다고 설명한다. 별도의 사용자 신고 환각 사례 평가에서는 Luna의 사실 오류 감소를 보고한다. 따라서 누락과 허위 사실을 따로 측정해야 한다. 이것은 Sasoo 논문 요약의 성능 보장이나 실패 원인의 인과 증명이 아니다. [Sol/Luna 안전 부록, §11.4.1/Table 29와 §11.5.1](https://deploymentsafety.openai.com/gpt-6-astra/sec%3Aappendix-sol-luna)

### 다른 모델의 기능과 구분해야 하는 내용

GPT-6 공통 prompting 안내는 Astra에서 관찰한 행동을 출발점으로 제시하며 선택한 모델과 실제 작업에서 평가하라고 명시한다. Astra의 질문, 위임, 테스트 성향을 Luna에서 관찰된 사실로 서술하지 않는다. [Using GPT-6, Prompting best practices](https://developers.openai.com/api/docs/guides/latest-model#prompting-best-practices)

현재 내장 Responses Multi-agent 베타의 지원 목록은 GPT-6.1 Sol과 모든 GPT-5.6 모델이다. Luna 모델 페이지에도 `multi_agent` 지원이 명시돼 있지 않다. 따라서 `gpt-6-luna`에 내장 Multi-agent 옵션을 붙일 근거가 부족하다. 앱이 여러 Luna 호출을 조율하는 구조와 이 내장 기능은 구분한다. 문서의 지원 목록을 확인한 결과이며 실제 계정의 API 거절 여부를 실험한 것은 아니다. [Responses Multi-agent](https://developers.openai.com/api/docs/guides/responses-multi-agent)

`reasoning.context=all_turns`도 현재 호환 표가 GPT-5.6 모델과 GPT-6.1 Sol을 명시한다. Luna에 같은 지원을 가정하지 않는다. 이전 응답 연결과 숨겨진 reasoning의 재사용은 다른 기능이다. 모델 계열을 바꾸면 호환되지 않는 reasoning은 전달되지 않는다. [Reasoning, Preserve reasoning across calls](https://developers.openai.com/api/docs/guides/reasoning#preserve-reasoning-across-calls)

## 3. 현재 Sasoo에서 확인한 문제

| 현재 상태 | 확인 위치 | 변경이 필요한 이유 |
|---|---|---|
| 운영 기본 모델은 5.6 Luna, 6 Luna는 후보 상수 | [models.py](../sasoo/backend/services/models.py:45) | 후보 지원과 운영 승격을 구분해야 함 |
| OpenAI 역할은 low/medium/high로 나뉨 | [model_registry.py](../sasoo/backend/services/model_registry.py:46) | 모델 교체와 effort 변경을 동시에 하면 효과를 구분하기 어려움 |
| 심층 분석 지시문은 이미 원문 우선, 수치/조건/출처 확인을 요구 | [analysis_execution.py](../sasoo/backend/services/analysis_execution.py:1187) | 새로운 금지 문장만 추가하는 접근의 이득은 미확인 |
| 결과는 1~2문단, 절별 answer는 1~2문장이라는 분량 지침 | [analysis_execution.py](../sasoo/backend/services/analysis_execution.py:1227) | 중요한 조건을 유지하는 우선순위를 명시할 필요가 있음 |
| 적용 조건은 최대 8개, 절별 답변은 최대 12개 | [summary_contract.py](../sasoo/backend/services/summary_contract.py:1) | 배열 존재만으로 필수 정보 충족을 판단할 수 없음 |
| validator는 타입, 개수, enum, 출처 문자열 존재를 확인 | [summary_contract.py](../sasoo/backend/services/summary_contract.py:58) | 출처가 실제 주장 전체를 지지하는지 판정하지 않음 |
| 어댑터는 Responses와 previous_response_id 사용, text.format 설정 | [openai_client.py](../sasoo/backend/services/llm/openai_client.py:136) | 현재 어댑터에 도구 정의나 tool-call 실행 루프는 없음 |
| system 지시문에 독자 수준, 연구 맥락, 관심 초점을 조립 | [analysis_context.py](../sasoo/backend/api/analysis_context.py:121) | 개인화와 편집 지침이 사실/조건 충족을 낮추지 않게 해야 함 |

현재 심층 분석 지시문은 3,694자다. 길다는 이유만으로 문제라고 판단하지 않는다. 분석 시작 시점의 지시문 SHA-256은 `af94abf1b4181ca13879bad26bbf30b28f0f8700d8331be5eadecd89655d721e`다.

[기존 비교 기록](../docs/validation/2026-09-23-gpt-6-luna-comparison.md)은 동일 PDF, high effort, 16k 상한에서 형식 6/6 통과와 엄격 원문 기준 0/6 통과를 함께 기록한다. 단위벡터 조건, return 정의, 미확인 사항, 실제 검증 방법과 정확한 근거 위치의 누락이 포함된다. 이는 생성된 모든 사실의 0%가 맞다는 뜻이 아니다. 12개 비교 응답은 모두 완료됐으므로 출력 상한 부족이 이번 실패의 확인된 원인은 아니다.

기존 [source_audit_pilot.py](../sasoo/backend/tools/source_audit_pilot.py:21)는 원문과 보존 초안을 대조하는 실험이다. 저장된 DP 결과의 과학 검증 상태는 `pending_independent_source_review`이며 모델도 5.6 Luna다. 이를 Luna 6의 검토 효과나 검증 완료로 인용하지 않는다.

## 4. Agent 운용 제안

### 첫 변경은 기존 체인의 역할 계약을 강화한다

각 역할에 입력, 해야 할 일, 반환 형식, 완료 조건을 준다. 예를 들어 visual은 도식의 관측/행동 방향과 읽을 수 있는 표기를 보고하고, recipe는 재현 조건과 입력/출력 인터페이스를 추출하고, deep_dive는 원문으로 앞 단계의 주장을 확인한 뒤 설명한다. 앞 단계 결과는 탐색 힌트이며 정답 자료가 아니다.

| 책임 | 담당 |
|---|---|
| 원본 PDF, 제공 부록, 입력 범위와 해시 | 백엔드 |
| 역할별 좁은 추출과 설명 | 현재 Luna 생성 단계 |
| 스키마, 상태, 중복 키와 불완전 응답 검사 | 기존 validator/어댑터 |
| 근거 위치 존재와 핵심 항목 충족 검사 | 원문 기반 평가, 필요 시 좁은 검증 호출 |
| 호출 한도, 재시도, 결과 저장, 취소 | 백엔드 |

추가 reviewer가 필요하면 기존 audit 실험을 출발점으로 삼는다. reviewer는 초안을 증거로 삼지 않고 원문을 읽으며, 특정 주장에 대해 `supported`, `contradicted`, `insufficient_evidence`를 반환하는 실험으로 좁힌다. 이 값들은 검증 단계의 제안이며 현재 제품 스키마에 추가한 enum이 아니다. 수정 반복의 횟수와 비용은 앱이 제한하고, 해결되지 않은 결함을 완료로 표시하지 않는다.

자동 reviewer의 판정도 전문가 판정에 맞춰 확인해야 한다. 같은 모델의 동의나 상위 모델의 점수만으로 원문 검증을 대신하지 않는다. 추가 호출 여부는 이득과 오판을 측정한 뒤 정한다. [Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices), [Graders](https://developers.openai.com/api/docs/guides/graders)

### Effort는 첫 비교에서 유지한다

screening/리졸버/naming의 low, recipe의 medium, deep_dive의 high를 첫 후보 비교에 유지한다. 범위가 좁은 작업에서 none/low, 어려운 원문 대조에서 medium/high를 비교하는 것은 후속 실험이다. xhigh/max 지원이 모든 역할을 그 값으로 바꿀 근거는 아니다. 이전 5.6 측정으로 6 Luna의 최적 effort를 확정하지 않는다.

## 5. 프롬프트 변경안

### 유지할 부분

공용 서비스 규칙의 한국어 출력, ID/단위/고유명사 보존, 문서 내 지시를 데이터로 취급하는 경계, 사실과 추론의 구분을 유지한다. 기존 JSON 필드와 배열 상한, 중복 키/제어문자/불완전 응답 거절도 유지한다. 설명 수준과 페르소나는 표현을 조정하며 과학적 조건을 삭제하는 권한을 주지 않는다.

### 바꿀 부분

| 기존 지침 | 후보 변경 |
|---|---|
| 포괄적인 심층 분석을 제공 | 여섯 완료 질문의 내용을 기존 필드에서 충족 |
| 짧은 문장/문단 수 지침 | 편집 목표로 두고 핵심 근거, 조건, 지표 정의를 우선 |
| 필드/출처 배열이 존재 | 내용 충족과 출처의 실제 지지 여부도 검사 |
| 여러 단계 출력을 바탕으로 설명 | 앞 단계 주장을 원문으로 확인하고 설명 |
| 중요한 조건 최대 8개 | 연구 유형에 필요한 명시 조건과 중요한 미확인 사항을 우선 선정 |

다음은 심층 분석의 목적/완료 조건을 개편할 때 쓸 후보 블록이다. 기존 필드별 출력 계약과 분야별 지침에 합쳐 평가할 초안이며 운영 프롬프트를 교체한 결과가 아니다.

```text
역할: 제공된 논문을 원문에 근거해 한국어로 설명한다.
원문 PDF와 제공된 부록이 사실의 근거다. 이전 단계 출력은 검증할 초안과 탐색 힌트다.

완료 조건:
1. 문제와 연구 목적을 설명한다.
2. 핵심 방법이 작동하는 이유와 필요한 가정을 설명한다.
3. 주요 결과의 지표 정의, 값과 단위, 비교 대상, 적용 범위와 조건을 함께 설명한다.
4. 저자가 보고한 한계와 분석자의 해석을 구분한다.
5. 재현하거나 옮겨 쓰기 전에 확인할 핵심 조건을 명시한다.
6. 중요한 정보 중 제공 자료로 확정할 수 없는 것과 그 확인 범위를 밝힌다.

이 여섯 질문은 새로운 JSON 키가 아니다. 기존 출력 필드에 해당 내용을 배치한다.
이론과 리뷰에는 실험 항목을 강요하지 않고, 비적용인 항목은 이유를 설명한다.

결과를 주장하기 전에 해당 원문 문장, 표의 행/열, 그림 범례 또는 수식을 확인한다.
수치와 지표의 정의, 방법 변형과 실험 범위를 한 묶음으로 유지한다.
확인하지 못한 정보는 미확인으로 서술하고, 중요한 이유가 있는 항목만 선정한다.
미제공 보충자료와 제공 원문에서 찾지 못한 정보를 구분한다.

간결한 설명은 핵심 조건을 유지한 뒤 다듬는다. 문장 수는 편집 목표다.
필수 조건이나 근거가 빠지면 보완하되 출력 스키마, 배열 상한과 출력 예산을 지킨다.
출처 식별자는 직접 확인한 표기만 쓰며, 미확인 위치나 값을 만들어 채우지 않는다.
출력은 현재 단계의 JSON 계약을 따른다.
```

숨겨진 사고 과정을 길게 출력하도록 요구하지 않는다. 필요한 것은 검산에 쓸 근거, 가정, 수식/수치 정의와 결론이다. 일반 reasoning 지침도 직접적인 목표와 성공 조건, 입력 구분을 권고한다. 이는 Luna 전용 성능 측정이 아니라 공통 출발점이다. [Reasoning best practices](https://developers.openai.com/api/docs/guides/reasoning-best-practices)

현재 문자열 필드에 임의로 `null`을 넣거나 `condition_basis`에 새 상태를 추가하지 않는다. 별도 근거 추출 구조를 시험한다면 원문 위치와 짧은 근거를 전달하되, 그 구조 자체도 원문 대조가 필요하다. JSON Schema 준수는 사실 정확성의 보장이 아니다. [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs#tips-and-best-practices)

## 6. 요청 구성과 캐시

공통 규칙과 출력 계약을 앞에 고정하고 개인화, 이번 질문, 변경되는 초안을 뒤에 둔다. 동일 원문을 여러 단계에서 사용하는 경로는 원문 재사용과 요청 순서를 함께 측정한다. 현재 system 조립은 일부 개인화가 공통 접두부에 들어가므로 실제 캐시 적중과 비용을 확인한 뒤 위치를 조정한다.

공식 문서는 `prompt_cache_options.ttl`, implicit/explicit 모드, `prompt_cache_breakpoint`를 설명한다. top-level `instructions`에는 explicit breakpoint를 붙일 수 없으므로 이를 쓰려면 developer 메시지의 `input_text` 블록이 필요하다. 현재 어댑터는 `instructions`를 사용한다. SDK 3.6.0의 표준 요청 타입에는 `prompt_cache_options`가 있으나 실제 캐시 효과를 검증한 것은 아니다. 재사용 없는 cache write도 비용이므로 모든 suffix를 캐시 대상으로 만들지 않는다. [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)

같은 대화에서 effort를 바꾸는 `configuration_update`는 현재 공식 문서상 GPT-6 standard single-agent 경로의 기능이다. 독립 단계마다 새 호출을 하는 경우와 구분하고 필요할 때 적용한다. `all_turns`나 내장 Multi-agent 지원을 추정해 함께 켜지 않는다. [Reasoning, Change reasoning mid-conversation](https://developers.openai.com/api/docs/guides/reasoning#change-reasoning-mid-conversation)

API background mode와 창 닫기 이후 앱 작업 지속성은 별도 검증 범위다. 프롬프트 변경 실험에 Electron 종료/알림 변경을 섞지 않는다.

## 7. 변경 후 검증 순서

1. **기준 상태 고정:** PDF/hash, 모델 ID, 실제 반환 모델, prompt/hash, schema/hash, effort, 출력 상한, 체인/단독 입력 경로, 사용량과 요청 지문을 보존한다. 제공 부록과 미제공 외부 자료를 명시한다.
2. **프롬프트 효과 분리:** 먼저 GPT-6 Luna+기존 프롬프트와 GPT-6 Luna+후보 프롬프트를 같은 조건에서 비교한다. 기존 5.6 결과는 참고 기준으로 보존한다. 모델과 프롬프트를 동시에 바꾸어 생긴 차이를 프롬프트 효과로 발표하지 않는다.
3. **기존 6편 회귀:** 현재 원문 기준의 질문과 필수 내용을 그대로 판정한다. 평가 정답, 정답 위치 힌트와 과거 reviewer 코멘트는 생성 입력에 넣지 않는다. 원본 PDF의 내용과 위치 표기는 정상 입력이다.
4. **지표 분리:** 엄격 논문 PASS/FAIL을 유지하고 사실 지지, 핵심 항목 충족, 출처 정확성, 중요한 미확인 사항, 형식/완료를 각각 기록한다. 중대한 수치/단위/방향/비교 대상 오류는 별도로 센다. 많이 생략한 답변의 높은 사실 지지율만으로 승격하지 않는다.
5. **Reviewer 효과 분리:** 프롬프트 변경만으로 남은 실패를 확인한 뒤 추가 검토를 켠/끈 비교를 한다. false pass는 틀린 답의 통과, false fail은 맞는 답의 탈락이다. 둘 다 원문 판정과 대조한다.
6. **미사용 논문과 반복:** 개선에 쓰지 않은 논문에서 일반화를 확인한다. 같은 설정의 반복과 블라인드 판정으로 실패 빈도와 순서 편향을 본다. 한 번의 완벽한 결과를 일반적 정확성으로 해석하지 않는다.
7. **실제 체인과 GUI:** 후보가 단독 deep_dive에서 통과해도 실제 체인에서 재검증한다. 대표 그림의 방향/축/수식, 지표와 근거 링크, 저장된 모델/버전/비용을 화면과 대조한다. 형식/렌더 통과를 원문 정확성으로 합산하지 않는다.
8. **판정:** 기존 엄격 기준과 실제 경로를 충족한 뒤 비용/시간을 보고 모델 승격을 판단한다. 필요한 새 생성 수와 상한 비용은 실행 전에 산정한다.

프롬프트는 코드와 함께 버전 관리하며 대표 사례와 미사용 평가를 준비한다. 현재 공식 Evals 플랫폼과 재사용 prompt 객체는 2026-11-30 종료 예정이므로 새 플랫폼 의존성을 만들기보다 기존 `luna_compare.py`와 로컬 기록을 활용한다. [Prompt engineering](https://developers.openai.com/api/docs/guides/prompt-engineering#version-prompts-in-code), [Deprecations](https://developers.openai.com/api/docs/deprecations#2026-06-03-evals-platform)

구체적인 평가 원칙과 직접 확인한 공식 출처는 [검증 근거 조사](2026-09-30-sasoo-accuracy-gates-evidence.md)에 정리했다.

## 8. 검증 범위와 재현

이번 조사에서 공식 Markdown 문서와 안전 부록 본문을 가져와 해당 문장을 확인했다. 안전 부록은 웹 opener 접근 제한 때문에 공식 URL을 curl로 가져와 본문을 확인했다. 시스템 Python의 인증서 확인 실패 후 인증서를 검증하는 curl로 문서를 가져왔으며 TLS 검증을 끄지 않았다.

현재 SDK는 3.6.0이고, `ResponseCreateParamsNonStreaming`의 `reasoning`, `text`, `prompt_cache_options` 필드를 확인했다. 표준 요청 타입에는 `multi_agent`가 없었다. 이 SDK 관찰과 공식 모델 지원 목록은 별도 근거이며 실제 계정 기능 테스트를 대신하지 않는다.

제품 코드나 운영 프롬프트를 변경하지 않았으며 새 유료 생성도 실행하지 않았다. 따라서 제안의 정확성, 비용과 시간 개선은 검증 전이다. 공식 자료의 모델별 지원 목록이 갱신되거나 현재 입력 경로가 바뀌면 호환성 판단도 다시 확인해야 한다.

핵심 재사용 원칙은 모델의 상세한 사고를 요구하는 대신 확인 가능한 완료 조건을 정하는 것이다. 같은 원문과 설정의 전후 비교로 효과를 검증한다. 형식 통과, 모델의 자기 확인, 일반 benchmark 개선을 과학적 정확성의 증거로 오인하는 것이 주요 함정이다.
