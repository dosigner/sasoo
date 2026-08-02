# AI 공급사 선택 (OpenAI / Gemini) 설계

- 작성일: 2026-07-31
- 개정: 2026-08-03 (하단 "개정 1" 섹션 — 이중 자문 감사 반영)
- 상태: 설계 확정, 구현 대기
- 관련: `services/models.py`, `api/settings.py`, `services/llm/`, `services/viz/figure_gen.py`

## 배경

sasoo는 현재 Gemini 전용 스택이다. `services/models.py`가 phase→model 매핑의 단일
소스이고, 텍스트 경로는 `gemini-3.6-flash`로 하드코딩되어 있다.

한편 설정에는 provider 관련 값이 이미 셋 존재하며 기본값이 서로 엇갈려 있다.

| 설정 | 현재 기본값 | 실제 의미 |
|---|---|---|
| `image_provider` | `openai` | 그림 생성 → gpt-image-2 |
| `pdf_visual_engine` | `gemini` | PDF 시각 파싱 |
| (설정 없음) | — | 텍스트 분석은 코드에 하드코딩 |

즉 현재 상태는 "텍스트는 Gemini, 그림 생성은 OpenAI"라는 혼합이다. 사용자는 이를
공급사 단위의 일관된 선택으로 바꾸기를 원한다.

### 모델 선정 근거

2026-07-30 OpenAI가 Luna 80%, Terra 20% 인하를 발표했다. 조사 결과 선택지는
`gpt-5.6-luna`와 `gemini-3.6-flash`로 좁혀졌다.

| 지표 | GPT-5.6 Luna | Gemini 3.6 Flash | 출처 |
|---|---|---|---|
| Intelligence Index (max) | 51 | 50 | Artificial Analysis |
| Intelligence Index (xhigh) | 49 | — | Artificial Analysis |
| 블렌디드 $/1M | $0.17 | $1.16 | Artificial Analysis |
| 입력 / 출력 $/1M | $0.20 / $1.20 | $1.50 / $7.50 | 각 공식 문서 |
| MMMU-Pro (vision) | 78.4% | 미공개 (전작 83.6%) | OpenAI 공식 / llm-stats |
| 출력 속도 | 175 tok/s | 215 tok/s | Artificial Analysis |
| TTFT (max) | 117.0초 | 14.7초 | Artificial Analysis |

effort는 `xhigh`를 기준으로 한다. `xhigh`(49) → `max`(51)는 +2점에 비용 +50%,
속도는 오히려 8% 느리다. OpenAI 문서도 `max`를 "xhigh를 쓰고 있다면 max가 더 나은지
평가하라"는 특수 설정으로 안내한다.

롱컨텍스트(MRCR)는 판단 기준에서 제외한다. sasoo 실행 기록 204건 실측 결과 논문 1편
분석의 입력 토큰 최대치가 80,882로, MRCR 측정 구간(256K~)에 도달하지 않는다.

## 확정된 결정

| # | 결정 사항 | 선택 |
|---|---|---|
| 1 | 분기 범위 | provider 통짜 전환 (vision 포함 전 단계) |
| 2 | 기존 provider 설정 통합 | 하나(`ai_provider`)로 통합 |
| 3 | 전환 시 캐시 | 캐시 키에 모델 포함 + 재분석은 수동 |
| 4 | effort 매핑 | 기존 단계별 사다리를 그대로 이식 |
| 5 | 키 삭제 시 | 남은 키로 자동 전환 + 알림 |
| 6 | 기존 설치본 마이그레이션 | 신규·기존 구분 없이 키 규칙 그대로 |

### 결정 1에 대한 명시적 판단

Luna는 vision이 Gemini 3.6 Flash보다 5.2%p 낮다(MMMU-Pro 78.4% vs 83.6%). 직전
커밋 `c22548a`에서 그림 추출 12편 전편 오차 0을 달성했으므로 OpenAI 경로가 이를
깨뜨릴 위험이 있다.

**그럼에도 vision만 Gemini로 고정하는 폴백은 넣지 않는다.** 사용자가 OpenAI를
선택하면 그림 판독도 OpenAI로 돌린다. 12편 정답셋 검증은 완료 게이트가 아니라
품질 차이를 측정·기록하는 용도로만 수행한다.

## 설계

### A. 설정 스키마

`DEFAULT_SETTINGS`에 `ai_provider`를 추가하고 이를 단일 소스로 삼는다.

```python
"ai_provider": "openai",   # "openai" | "gemini"
```

`image_provider`와 `pdf_visual_engine`은 **삭제하지 않는다.** 이미 이 값을 읽는
코드가 있어 한 번에 걷어내면 회귀 위험이 크다. `ai_provider`가 바뀔 때 두 값을
lockstep으로 함께 갱신하면 기존 코드는 수정 없이 동작한다.

읽기는 `ai_provider`가 권위를 갖는다. 두 레거시 키는 쓰기 전용 미러다.

#### 마이그레이션

신규·기존 설치를 구분하지 않는다. 코드에 예외 분기를 남기지 않기 위해서다.

```
키가 하나만 있으면      → 그 provider
키가 둘 다 있으면       → openai
키가 하나도 없으면      → openai (기본값, 단 동작은 잠김)
```

기존 사용자에게 실제로 바뀌는 것은 텍스트 분석이 `gemini-3.6-flash` → `gpt-5.6-luna`로
가는 것 하나다. 그림 생성은 이미 `gpt-image-2`라 그대로 유지되고, 기존 분석 결과는
결정 3의 배지 방식으로 보존된다.

### B. 모델 레지스트리

`services/models.py`를 provider × role 표로 확장한다. OpenAI 쪽은 모델이
`gpt-5.6-luna` 하나로 고정되고 effort만 변주된다.

| role | Gemini 모델 / thinking | OpenAI 모델 / effort |
|---|---|---|
| screening | `gemini-3.5-flash-lite` | `gpt-5.6-luna` / `low` |
| visual | `gemini-3.6-flash` / low | `gpt-5.6-luna` / `low` |
| citation | `gemini-3.6-flash` | `gpt-5.6-luna` / `medium` |
| recipe | `gemini-3.6-flash` / medium | `gpt-5.6-luna` / `medium` |
| deep_dive | `gemini-3.6-flash` / high | `gpt-5.6-luna` / **`xhigh`** |
| viz_planning | `gemini-3.6-flash` / medium | `gpt-5.6-luna` / `medium` |
| mermaid | `gemini-3.6-flash` | `gpt-5.6-luna` / `medium` |
| chat | `gemini-3.6-flash` | `gpt-5.6-luna` / `medium` |
| figure_explain | `gemini-3.6-flash` | `gpt-5.6-luna` / `medium` |
| image | `gemini-3.1-flash-image` | `gpt-image-2` |

기존 `_STAGE_THINKING`(analysis_routes.py)의 low/medium/high 배분을 그대로 이식한
것이다. 검증된 배분을 재사용하고, 쉬운 단계에 `xhigh`를 태우지 않아 비용과 지연을
함께 아낀다.

단 `_STAGE_THINKING`이 다루는 것은 `visual` / `recipe` / `deep_dive` /
`visualization` 넷뿐이다. `citation` · `mermaid` · `chat` · `figure_explain`의
effort는 이 스펙에서 새로 정한 값이며(`medium`), 기존 배분에서 유도한 것이
아니다. 근거가 약한 쪽이므로 2단계에서 실제 출력을 보고 조정할 수 있다.

`MODEL_SCREENING` 등 기존 상수는 Gemini 값을 그대로 유지한 채 남긴다(유지+추가).
새 코드는 레지스트리를 조회한다.

### C. LLM 클라이언트 추상화

가장 큰 작업이다. 현재 `services/llm/interactions_client.py`는 google-genai
전용이다 — Files API 업로드, `previous_interaction_id` 서버측 체인, `store=True`가
모두 Gemini 개념이다.

```
services/llm/
  base.py            신규 — 공통 인터페이스 (generate / chain / upload)
  gemini_client.py   기존 interactions_client.py 개명
  openai_client.py   신규 — Responses API
  __init__.py        ai_provider 보고 라우팅
```

체인 개념은 1:1로 대응된다.

| 개념 | Gemini | OpenAI |
|---|---|---|
| 서버측 체인 | `previous_interaction_id` | `previous_response_id` |
| 상태 저장 | `store=True` | `store=True` |
| 파일 업로드 | Files API (48h TTL) | Files API |
| 사고량 조절 | `thinking_level` | `reasoning.effort` |

lane 분리(`chat` / `pipeline`), 세마포어, 재시도 정책은 provider 무관이므로 공통
계층에 남긴다. `_RETRYABLE_CLIENT_STATUS = {408, 429}` 판정은 HTTP 상태 기반이라
그대로 재사용 가능하다.

#### 깨면 안 되는 계약

- lane을 명시하지 않는 호출을 만들지 않는다. 기본값을 두면 2026-07-11 채팅 SSE
  무한 대기 사고가 재발한다.
- `store=False`인데 체인 ID를 넘기면 `ValueError`를 올리는 현재 방어를 유지한다.
- 파이프라인 세마포어는 루프별로 생성한다(크로스루프 바인딩 방지).

### D. 캐시

`compute_input_hash`를 확장한다.

```python
# services/document_context.py
def compute_input_hash(input_text: str, *, model: str, effort: str | None = None) -> str
```

`effort`는 provider 중립 인자다. Gemini 경로는 `thinking_level`
(low/medium/high)을, OpenAI 경로는 `reasoning.effort`(low/medium/xhigh)를
넘긴다. 같은 모델이라도 사고량이 다르면 다른 결과가 나오므로 둘 다 키에 들어가야
한다.

조회는 2단계가 된다.

1. 현재 모델·effort 해시로 조회 → 히트하면 그대로 사용
2. 미스면 해당 phase의 최신 행을 조회해 "`gemini-3.6-flash`로 분석됨" 배지와 함께
   표시하고, 재분석 버튼을 노출한다

기존 행은 옛 해시를 갖고 있어 자동으로 2번 경로를 탄다. 별도 데이터 마이그레이션이
필요 없고, 되돌리기도 공짜다(원래 provider로 돌아가면 1번에서 히트).

인덱스 `idx_analysis_cache(paper_id, phase, input_hash)`는 그대로 쓴다.

### E. 키 상태 머신

```python
def effective_provider(settings) -> str | None:
    """저장된 선택을 키 가용성으로 보정한다."""
    # 저장된 ai_provider의 키가 있으면        -> 그대로
    # 없고 다른 쪽 키가 있으면                -> 자동 전환 (알림)
    # 둘 다 없으면                            -> None
```

`figure_gen.py`의 기존 `available()` 패턴(`os.environ.get("OPENAI_API_KEY")`)과
동일한 방식이다.

`None`이면 분석 라우트가 409를 반환하고 프론트는 분석 버튼을 비활성화한 뒤 설정으로
안내한다. 자동 전환이 일어나면 토스트로 알린다.

### F. 비용 추적

`services/pricing.py`에 추가한다.

```python
"gpt-5.6-luna": {"input": 0.20, "output": 1.20},   # 2026-07-30 인하 후
```

`gpt-image-2`는 quality별로 이미 존재한다(`low` 0.005 / `medium` 0.041 / `high` 0.165).

`services/models.py` 상단 주석의 계약("여기 있는 모든 ID는 PRICING 항목을 가져야
한다")을 지킨다.

### G. UI

**설정 화면 (`frontend/src/pages/Settings.tsx`)**

- AI 공급사 셀렉트 1개 (`OpenAI (GPT-5.6 Luna)` / `Google (Gemini 3.6 Flash)`)
- API 키 입력 2칸 (기존 유지)
- 키가 없는 공급사는 셀렉트에서 비활성 + 사유 표기
- 키 삭제로 자동 전환이 일어나면 토스트

**분석 화면**

- 현재 설정과 다른 모델로 분석된 결과에 배지 표시
- 배지 옆 재분석 버튼

## 구현 순서

두 단계로 나눈다. 1단계가 2단계의 안전망이 된다.

### 1단계 — provider 추상화 (동작 변경 없음)

Gemini 동작을 100% 그대로 유지하는 순수 리팩터. 기존 테스트로 회귀를 검증할 수 있다.

1. `services/llm/base.py` 인터페이스 정의
2. `interactions_client.py` → `gemini_client.py` 개명 + 인터페이스 준수
3. `services/models.py`에 provider × role 레지스트리 추가 (Gemini만 채움)
4. `ai_provider` 설정 추가, 값은 항상 `gemini`로 고정한 채 배선
5. `compute_input_hash`에 model/effort 인자 추가 (Gemini 값으로만 호출)

**완료 조건:** 기존 테스트 전부 통과. 12편 정답셋 오차 0 유지.

### 2단계 — OpenAI 경로 추가

6. `services/llm/openai_client.py` 구현 (Responses API + 체인 + 파일 업로드)
7. 레지스트리 OpenAI 열 채우기
8. `pricing.py`에 `gpt-5.6-luna` 추가
9. `effective_provider()` + 409 처리 + 자동 전환
10. `ai_provider` 마이그레이션 (키 규칙)
11. Settings UI + 분석 화면 배지·재분석 버튼

**완료 조건:** OpenAI 경로로 전체 파이프라인 완주. 키 상태 전이 4가지 시나리오
(OpenAI만 / Gemini만 / 둘 다 / 없음) 동작 확인. 12편 정답셋을 OpenAI 경로로 돌려
**결과를 기록**(게이트 아님).

## 리스크

| 리스크 | 영향 | 대응 |
|---|---|---|
| Luna vision 78.4% → 추출 정확도 하락 | 그림·표 오차 발생 가능 | 폴백 없음(결정). 12편 결과를 측정·기록해 사용자에게 고지 |
| `previous_response_id` 체인 의미 차이 | 다단계 분석 문맥 유실 | 1단계에서 인터페이스로 차이를 흡수, 2단계에서 체인 연속성 테스트 |
| OpenAI 파일 업로드 TTL·용량 제약 | 긴 PDF 실패 | Gemini의 47h TTL 방식을 참고해 provider별 TTL 상수 분리 |
| 레거시 설정 2개와 `ai_provider` 불일치 | 예측 불가 동작 | lockstep 갱신을 단일 함수로 강제, 직접 write 금지 |

## 범위 밖

- Terra·Sol 등 상위 티어 노출 (선별 승격은 별도 과제)
- phase별 개별 모델 선택 UI
- effort를 사용자에게 노출하는 슬라이더
- OpenRouter 등 중계 provider 지원

---

## 개정 1 (2026-08-03) — 이중 자문 감사 반영

원안 확정 후 독립 자문 2건(Opus deep-reasoner, Codex)으로 원안과 구현 플랜
(`docs/superpowers/plans/2026-08-01-ai-provider-selection.md`)을 감사했다.
아키텍처(§C gateway + 어댑터)는 양쪽 만장일치로 유지. 아래는 원안을 수정·보강하는
결정이며, 원안과 충돌하는 항목은 이 섹션이 우선한다.

### R1. OpenAI 체인의 문서 입력: PDF 업로드 → 로컬 추출 텍스트 (원안 §C 수정)

OpenAI 경로는 Files API에 PDF를 업로드하지 않는다. 첫 호출에 로컬 추출 텍스트
(기존 stateless 폴백이 쓰는 text artifacts)를 1회 주입하고 `previous_response_id`로
후속 스테이지를 잇는다. visual 스테이지는 추출된 그림 이미지 파트를 별도 첨부한다.

근거: OpenAI의 PDF 입력은 페이지 이미지를 함께 과금·입력하므로 (a) 비용 증가,
(b) "LLM 비전 PDF 파싱 제외" 범위와 충돌, (c) 50MB 한도·체인 내 파일 유지가 미검증.
부수 효과로 OpenAI 쪽 업로드 캐시·락·TTL 관리가 전부 불필요해지고,
`papers.pdf_file_uri`의 provider 오염 문제가 소멸한다. **`pdf_file_uri`는 Gemini
전용 컬럼으로 주석에 명시한다.**

### R2. 범위 명확화 (원안 결정 1 재해석)

"vision 포함 통짜 전환"은 **그림 단위 판독**(이미지 파트 입력: figure_explain,
figure/table_resolver, subfigure_detector)까지를 뜻한다. **PDF 전체 비전 파싱**
(`pdf_visual_engine=gemini`, `gemini_parser.py`)은 범위 밖이다 — OpenAI 키 단독
사용자는 로컬 ODL 파서 경로를 쓴다. (병합된 `provider_state.py`의 실동작과 일치)

### R3. deep_dive effort: xhigh → high (원안 §B 수정)

Gemini 사다리(deep_dive=high)와 대칭을 유지하고 플랜 전역 제약("low/medium/high만")
과 정합시킨다. xhigh 승격은 확장된 측정 도구에서 high 대비 품질 우위가 확인될 때만.

### R4. 레지스트리 role 전체 커버 (원안 §B 보강)

원안 표에 빠져 있던 role을 추가한다: `figure_resolver` / `table_resolver` /
`subfigure` / `naming`. 이들과 screening은 Gemini에서 `thinking_level="minimal"`을
쓰므로 OpenAI도 최저 effort로 매핑한다 — **`minimal` 지원 여부는 검증 스파이크
(R8-2) 결과에 따라 `minimal` 또는 `low`로 확정.**

### R5. OpenAI 클라이언트 필수 구현 범위 (플랜 Task 9 보강)

플랜 스케치에서 빠진 세 가지를 필수로 명시한다.

1. **파트 번역기**: `prompt: str | list[dict]`를 받아 `{"type":"image"}` →
   `input_image`(base64 data URL), `{"type":"text"}` → `input_text`로 변환.
   이미지 파트를 넘기는 프로덕션 호출부가 7곳이다(플랜의 `prompt: str` 가정은 오류).
2. **`stream_interaction` 등가**: `response.output_text.delta`/`response.completed`
   이벤트를 기존 `{"type":"token"}`/`{"type":"done"}` SSE 계약으로 정규화.
   재시도 정책은 현행 유지(첫 토큰 전 실패만 재시도, 토큰 후 실패는 terminal).
3. **클라이언트 캐싱**: `interactions_client.py:82-104`와 동일한 키별 캐시+락.
   재시도 예외는 `except Exception`으로 좁힌다(`BaseException`은
   `asyncio.CancelledError`까지 잡아 취소된 태스크를 재시도하는 버그).

또한 shim(`services/llm/__init__.py`)은 `stream_interaction`과 `media_resolution`
을 포함해 기존 시그니처 전체를 유지한다 — 리졸버·네이밍 등 9곳 호출부는 무수정.

### R6. 캐시 키와 스테이지 컨텍스트 (원안 §D 보강)

`compute_input_hash(input_text, *, provider, model, effort)`로 확장하되, model/effort
를 호출부마다 흩뿌리지 않는다 — **스테이지 진입 시 `(provider, model, effort)`를
한 번 확정해 컨텍스트로 내려** 읽기(`_get_cached_phase_result`)와
쓰기(`_insert_analysis_result`), 체크포인트 UPDATE(`_update_visualization_checkpoint`)
가 반드시 같은 키를 쓰게 한다(어긋나면 체크포인트 중복 INSERT).
`odl_parser.py:1907`의 파서 사용량 기록은 provider 무관 — 기본값으로 흡수.

### R7. 비용 정확성 (원안 §F 보강)

1. `pricing.py`의 `_FALLBACK`을 provider 접두사로 분리 — 미지의 `gpt-*` 모델을
   Gemini 단가로 조용히 계산하지 않는다.
2. OpenAI `usage.output_tokens`는 reasoning 토큰을 **이미 포함**한다.
   `reasoning_tokens`는 정보용으로만 기록하고 합산에 더하지 않는다(이중 계상 금지).
   (Gemini는 반대로 `output + thought` 합산이 맞다 — 현행 유지.)
3. 재시도는 attempt별로 `calc_cost`를 계산한 뒤 USD를 합산한다(토큰 합산 후 일괄
   계산 금지 — 모델·장문 임계값이 어긋난다).
4. `cached_tokens` 할인은 프로덕션 합산에 넣지 않는다(보수적 과다 보고 유지).
   측정 도구에서만 별도 계산.
5. **단가 게이트**: 원안의 Luna $0.20/$1.20와 자문 제시값 $1/$6이 5배 어긋난다.
   구현 1단계 착수 전 공식 가격 페이지에서 재확인해 `PRICING`에 반영하는 것을
   선행 태스크로 둔다.
6. 기존 버그(이 설계와 독립, 선행 수정 가능): 캐시 히트 시 과거 비용을 현재 실행
   `status.total_cost_usd`에 재합산(`analysis_routes.py:136` 인근).

### R8. 구현 전 검증 스파이크 (플랜 선행 태스크로 추가)

소형 스크립트로 실측 후 결과를 플랜에 기록한다. 실패 시 해당 설계 항목을 재검토.

1. `previous_response_id` 체인: `store=True` 연쇄, `resp.id` 재사용, 첫 턴 텍스트가
   후속 턴에 유지되는지, 보존 기간.
2. `reasoning.effort` 지원 값 집합 — 특히 `minimal` 유무 (R4 확정 조건).
3. `text.format=json_schema` + `strict:false` 동작: sasoo 스키마 4종을 그대로 보내
   준수율과 `_stage_result_defect` 재시도 발화율 측정. (strict:true는 현행 스키마
   구조상 불가 — 일부 required·minimum/maximum 사용.)
4. 스트리밍 이벤트명·usage 수신(`response.output_text.delta` /
   `response.completed`), 정상 완료·첫 토큰 전 실패·토큰 후 실패·연결 종료 4경로.
5. 429 응답의 `Retry-After` 헤더 유무 (현행 고정 백오프 `[2, 8]` 조정 판단).
6. refusal / `incomplete(max_output_tokens)` / 빈 output이 일반 JSON 결함과
   구분 가능한 형태로 오는지.
7. 이미지 파트(base64) 입력 1회 실측 (리졸버 경로 등가 확인).

### R9. 측정 도구 확장 (`tools/provider_compare.py`)

extraction_audit 관례(프로덕션 코드 무수정, JSON 산출) 유지. 확장: (a) 3개 스테이지
→ 5단계 전체, (b) `cached_tokens`·`reasoning_tokens`·재시도 발화율 기록,
(c) high vs xhigh 등 effort 승격 판단용 비교 실행. 앱 내 A/B 기능은 만들지 않는다.

### R10. 플랜 재작성 지침

`2026-08-01-ai-provider-selection.md`는 폐기하지 않되, 이 개정을 반영한 새 플랜을
writing-plans로 재작성한다. 순서 조정: 검증 스파이크(R8) → 1단계(게이트웨이,
동작 무변경) → OpenAI 클라이언트(Task 9 상당, R5 포함) → 캐시 키(R6) → stateless
경로 배선(screening·citation·Mermaid·naming·리졸버·그림설명) → 채팅 스트리밍 →
서버측 체인 4스테이지 → 키 상태 머신·UI. 캐시 키 확정에 R8-2(effort 값 집합)가
필요하므로 OpenAI 클라이언트 실측이 캐시 키 작업보다 앞선다.
