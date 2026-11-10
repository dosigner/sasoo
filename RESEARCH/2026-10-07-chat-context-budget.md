# 채팅 맥락 표시 단위: 메시지 개수 vs 토큰 예산 (조사)

확인일: 2026-10-07. 모든 수치는 아래 URL의 공식 문서를 이 날짜에 읽은 값이다. "확인 못 함"은 문서에서 찾지 못한 항목이고, 추정은 [추정]으로 따로 표시했다.

## 현재 코드 (실측: 파일을 읽은 사실)

- `sasoo/backend/api/analysis_routes.py` 1327행: `for msg in history[-20:]`. 오래된 메시지는 조용히 잘리고, 잘린 뒤에도 사용자 입력 1건(`message`)은 항상 추가된다.
- 시스템 프롬프트(논문 컨텍스트 + 5단계 분석 결과)는 히스토리와 별개로 매 요청 붙는다. 이 길이는 이번 조사에서 측정하지 않았다.
- chat 모델: Gemini는 `gemini-3.8-flash`(thinking 인자 없음), OpenAI는 `gpt-6-luna`(effort low). `sasoo/backend/services/model_registry.py` 66, 87행.

## 1. 컨텍스트 창과 출력 한도

| 모델 | 입력 | 출력 | 출처 |
|---|---|---|---|
| gemini-3.8-flash | 입력 토큰 한도 1,048,576 | 65,536 | https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash |
| gpt-6-luna | 컨텍스트 창 1,050,000, 최대 입력 922,000 | 최대 출력 128,000 | https://developers.openai.com/api/docs/models/gpt-6-luna |

두 모델 모두 약 100만 토큰급이다. 한국어 채팅 20개 메시지가 창에 닿을 가능성은 사실상 없다 [추정: 메시지당 수백~수천 토큰이면 합계 수만 토큰, 창의 수% 이하. 실제 분포는 미측정].

## 2. 요청 전 입력 토큰 계산

Gemini
- `models.countTokens` (`POST https://generativelanguage.googleapis.com/v1beta/{model=models/*}:countTokens`). `contents[]` 또는 `generateContentRequest`(시스템 지시와 함수 선언 포함)를 받고 `totalTokens`, `cachedContentTokenCount`, `promptTokensDetails[]`를 돌려준다. https://ai.google.dev/api/tokens
- 비용: "Requests to the `GetTokens` API are not billed, and they don't count against inference quota." https://ai.google.dev/gemini-api/docs/billing
- 레이트 리밋: "The maximum quota for the Count Tokens API is 3000 requests per minute (RPM)." 단 이 문장은 Firebase AI Logic 문서에 있고(https://firebase.google.com/docs/ai-logic/count-tokens), Gemini Developer API 쪽 공식 문서(rate-limits, tokens, API reference)에서는 같은 수치를 확인 못 함. 같은 백엔드라는 것은 추정.
- 지연: 문서에 수치 없음. 확인 못 함.
- 로컬 토크나이저: 공식 문서에 언급 없음. 확인 못 함. 대략 "1 token per 4 characters"만 안내된다(https://ai.google.dev/gemini-api/docs/tokens). 한국어에 이 비율이 맞는지는 문서에 없다.
- 실제 사용량은 응답의 usage로도 얻는다(요청 후 값).

OpenAI
- 입력 토큰 카운트 API `POST /v1/responses/input_tokens`. Responses API와 같은 입력(텍스트, 메시지, 이미지, 파일, 도구, conversation)을 받는다. https://developers.openai.com/api/docs/guides/token-counting
- 로컬 대안 tiktoken은 평문 추정용이며 도구와 스키마 토큰은 로컬로 세기 어렵다고 문서가 직접 밝힌다. 같은 페이지.
- 비용, 레이트 리밋, 지연: 가이드 페이지에 명시 없음. API reference URL(`.../responses/subresources/input_tokens/methods/count`)은 404였다. 확인 못 함.
- gpt-6-luna 기본 레이트 리밋(채팅 호출 자체): Build 5,000 RPM / 2M TPM, Launch 10,000 RPM / 10M TPM, Grow 30,000 RPM / 180M TPM. https://developers.openai.com/api/docs/models/gpt-6-luna

앱 관점의 함의: 카운트 호출은 요청 1건당 네트워크 왕복을 하나 더 만든다. 두 SDK 모두 응답 usage로 "직전 요청의 실제 입력 토큰"은 공짜로 얻으므로, 사전 계산 없이 직전 값을 표시에 쓰는 방식도 가능하다(구현 판단은 이 문서 범위 밖).

## 3. 단가 구간과 캐시

gemini-3.8-flash (https://ai.google.dev/gemini-api/docs/pricing)
- 입력 $0.75 / 출력 $3.75 per 1M (2026-12-31까지). 2027-01-01부터 $1.50 / $7.50.
- 프롬프트 길이에 따른 단가 구간 없음("no differentiation by prompt length", 페이지 요약 기준. 200K 초과 상승은 3.8 Flash에는 해당 없음).
- 캐시 읽기 $0.075 (2027-01-01부터 $0.15), 저장 $0.50 per 1M tokens per hour (2027-01-01부터 $1.00).
- 암묵 캐시: 3.8/3.7/3.6/3.5 Flash 최소 4,096 토큰, 자동 적용, 적중은 `usage.total_cached_tokens`. Interactions API는 암묵 캐시만 지원하고 명시 캐시는 미지원. https://ai.google.dev/gemini-api/docs/caching

gpt-6-luna (https://developers.openai.com/api/docs/models/gpt-6-luna)
- 입력 $0.1, 캐시 입력 $0.01, 캐시 쓰기 $0.125, 출력 $0.5 per 1M.
- 구간: "Prompts with more than 272K input tokens are priced at 2x input and cache rates and 1.5x output for the full request." 요청 전체에 적용.
- 캐시(GPT-5.6+ 기준 문서, luna에 그대로 적용되는지는 모델 페이지에 명시 없어 추정): 최소 1,024 토큰, 읽기 0.1배, 보존 최근 쓰기/재사용 후 30분, 기본 활성, `usage.input_tokens_details.cached_tokens`. https://developers.openai.com/api/docs/guides/prompt-caching

참고: 위 가격은 이 앱 모델 페이지에서 읽은 값이며 실제 청구 단가 검증(실호출 대조)은 하지 않았다.

## 4. 표시 단위 선택지별 근거 (결정 아님)

수치 요약: 20개 메시지 상한이 만드는 입력은 [추정] 수만 토큰 수준이고, 두 모델의 창(약 105만, 92.2만 입력)과 단가 구간 임계(OpenAI 272K)에는 한참 못 미친다. 현재 상한은 비용이나 창 한도 때문에 걸리는 것이 아니라 자르기 정책으로만 존재한다.

1. 메시지 개수 ("대화 12/20")
   - 장점: 코드의 실제 절단 규칙(`history[-20:]`)과 정확히 일치해 표시가 거짓이 될 수 없다. 추가 API 호출, 지연, 쿼터 소모 0. 프로바이더와 무관하게 동일.
   - 단점: 메시지 길이 편차(한 줄 질문 vs 긴 답변)를 반영하지 못한다. 20개가 가득 차도 창의 극히 일부일 수 있어 "곧 잘린다"는 신호가 비용 측면에서는 과장일 수 있다.
2. 토큰 예산 ("12.4K / 1.0M" 등)
   - 장점: 실제 한도(창, 272K 구간, 캐시 임계 4,096/1,024)와 같은 단위로 말할 수 있다.
   - 단점: 현재 코드는 토큰이 아니라 개수로 자르므로, 표시를 토큰으로 바꾸면 절단 규칙도 바꾸지 않는 한 표시와 동작이 어긋난다. 정확한 사전 계산은 Gemini countTokens(무료, 단 앱 경로의 리밋 수치는 미확인)나 OpenAI input_tokens(비용, 리밋 미확인)의 왕복 호출이 필요하고, 로컬 근사는 공식 토크나이저가 Gemini에 없어 오차가 한국어에서 얼마인지 문서로 확인 못 함. 두 프로바이더가 서로 다른 토크나이저를 쓰므로 프로바이더 전환 시 같은 대화의 수치가 달라진다.
3. 혼합 (개수 표시 + 직전 요청의 실제 usage 토큰을 보조 표시)
   - 장점: 추가 호출 없이 응답 usage만으로 실측 토큰을 얻는다(두 SDK 모두 usage 제공).
   - 단점: 값이 "직전 요청 기준"이라 한 턴 늦고, 프로바이더 전환 직후 값이 비어 있다.

## 확인 못 한 항목

1. Gemini countTokens의 Gemini Developer API 쪽 레이트 리밋 수치와 지연(3000 RPM은 Firebase AI Logic 문서 출처).
2. OpenAI `input_tokens` 엔드포인트의 비용, 레이트 리밋, 지연(가이드와 API reference 모두 명시 없음, reference URL 404).
3. Gemini 공식 로컬 토크나이저 존재 여부와 한국어 토큰/문자 비.
4. gpt-6-luna에 GPT-5.6+ 캐시 규칙(1,024 토큰, 30분)이 그대로 적용되는지(모델 페이지에는 캐시 가격만 있음).
5. 이 앱의 실제 시스템 프롬프트(분석 결과 포함)와 메시지 길이 분포: 미측정.
