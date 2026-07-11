# 논문 도해 생성 모듈 (figure_gen) 설계

2026-07-11 · sasoo backend · PaperBanana 패키지 대체

## 배경

PaperBanana 패키지(커뮤니티 재구현체)가 asyncio 이벤트 루프 안에서 동기 Gemini 호출을
실행해, 이미지 생성 중 서버 전체가 응답 불능이 된다. 2026-07-11 실측에서 이미지 호출이
행에 걸리자 asyncio 기반 타임아웃도 발화하지 못했고(루프 자체가 블로킹), PythonManager가
크래시로 오판해 재시작을 6회 시도하다 포기, 시각화 결과 전체가 유실됐다. 패키지 README에는
Google 특허로 인한 상용 제약도 명시돼 있다. 이를 자체 2단 파이프라인으로 대체한다.

## 확정된 결정

| 항목 | 결정 |
|---|---|
| 파이프라인 | 2단: Planner → Render (Critic 없음) |
| 레퍼런스 이미지 | 사용 안 함 (텍스트 기술서만) |
| 렌더 프로바이더 | gpt-image-2 (quality=high 기본) ↔ Nano Banana 2 (`gemini-3.1-flash-image`), 설정으로 전환 |
| 폴백 | 선호 프로바이더 실패 시 다른 쪽 자동 폴백, 사용된 프로바이더를 결과에 기록 |
| gpt-image-2 "thinking" | 존재하지 않음 확인(공식 문서 0회) — quality=high + Planner 단계가 그 역할 |

## 아키텍처

새 모듈 `backend/services/viz/figure_gen.py` 하나. 외부 계약은 기존 브릿지와 동일:
`is_available` / `last_error` / `await generate_illustration(viz_target, paper_dir) → Optional[str]`,
저장 경로 `{paper_dir}/paperbanana/{name}.png` (프론트 URL 호환 위해 디렉터리명 유지).

### [1] Planner — Gemini 3.1-pro (GeminiClient 재사용, 재시도 내장)

viz_target(제목·설명·카테고리)을 받아 **상세 기술서**를 생성한다. PaperBanana Planner의
요체를 이식한 프롬프트: 배경 스타일, 색상 팔레트, 선 굵기, 아이콘 스타일, 포함할 모든
라벨 텍스트를 명시하고, 모호한 지정을 금지하며, figure 제목은 이미지에 넣지 않는다.

### [2] Render — ImageProvider 프로토콜

```python
class ImageProvider(Protocol):
    name: str
    def available(self) -> bool: ...        # 키 존재 여부 등
    def generate(self, description: str) -> bytes:  # 동기, PNG bytes
```

- `OpenAIImageProvider`: POST /v1/images/generations (httpx 직접), model=gpt-image-2,
  quality=설정값(기본 high), size 1536x1024, b64 디코드. httpx 클라이언트 타임아웃 명시.
- `GeminiImageProvider`: google-genai, model=`gemini-3.1-flash-image` (Nano Banana 2),
  http_options 타임아웃 명시.

### 격리와 타임아웃 (사고 재발 방지의 핵심)

렌더 호출은 반드시 `asyncio.wait_for(asyncio.to_thread(provider.generate, desc), timeout=180)`.
스레드로 빼면 이벤트 루프가 살아 있어 서버가 계속 응답하고, 타임아웃 타이머도 실제로
발화한다. HTTP 클라이언트 타임아웃(연결/읽기)과 이중 방어.

### 폴백 순서

설정 `image_provider`가 1순위, 나머지가 2순위. `available() == False`(키 없음)이거나
generate가 예외/타임아웃이면 다음 프로바이더. 전부 실패하면 해당 항목만 실패 처리하고
다음 항목 진행. 결과 dict에 `provider`, `duration_s`, `cost_usd` 기록.

## 호출부·설정 변경

1. `analysis_routes._generate_single_paperbanana` → figure_gen 호출로 교체.
   **항목 하나 완료될 때마다 DB에 즉시 저장** (전체 완료 후 일괄 저장 구조 폐기).
2. 기동 시 `analyzing` 고착 논문을 `error`로 정리하는 복구 로직.
3. 설정 추가: `openai_api_key`(crypto 암호화, `_API_KEY_FIELDS` 등재), `image_provider`
   (`openai`|`gemini`, 기본 `openai`), `image_quality`(`low`|`medium`|`high`, 기본 `high`).
   Settings 화면에 OpenAI 키 입력란(기존 Gemini 키 UI 패턴 재사용)과 프로바이더/품질 선택.
4. `pricing.py`: gpt-image-2 quality·size별 장당 단가, Nano Banana 2 $0.067 유지.
5. 제거: `paperbanana` 패키지 의존, `services/viz/paperbanana_bridge.py`,
   `api/settings.py`의 paperbanana 진단 엔드포인트, `GOOGLE_API_KEY` 동기화 핵
   (main.py·settings.py — 중복 경고의 원인).

## 에러 처리

- 항목별 격리: 한 도해 실패가 다른 항목/페이즈를 막지 않는다. 실패 사유를 DB에 기록.
- Planner 실패(Gemini 재시도 3회 소진) 시 해당 항목 실패 처리.
- 프로바이더 키가 둘 다 없으면 시각화 항목을 skipped로 기록하고 파이프라인은 정상 종료.

## 테스트

- 단위: 폴백 순서(가짜 프로바이더), 타임아웃 발화(sleep하는 가짜 프로바이더로 루프
  생존 확인), available() 판정(키 유무), 파일명 안전성, 항목별 DB 저장.
- 실키 스모크: OpenAI 키를 Settings 화면에서 입력 후(채팅 전달 금지) PredictionNet
  논문(paper_id=49)의 viz_plan 4건 재생성 — 프로바이더별 1건 이상, 타이밍 로그 기록.

## 성공 기준

1. 이미지 생성 중 `/health`가 200을 유지한다 (이번 사고의 직접 재현 조건).
2. 행 걸린 호출이 180초에 실제로 잘리고 다음 항목으로 넘어간다.
3. paper_id=49의 도해 4건이 생성되고 항목별로 DB에 저장된다.
4. `import paperbanana`가 코드베이스에서 사라진다.
