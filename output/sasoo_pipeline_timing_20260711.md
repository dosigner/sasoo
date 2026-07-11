# sasoo 파이프라인 실측 로그 — PredictionNet 논문 (2026-07-11)

대상: `PredictionNet: a long short-term memory-based attention network for atmospheric
turbulence prediction in adaptive optics` (Applied Optics 61(13), 2022, 23.9MB PDF)
paper_id=49, 모델 구성: 2026-07-11 세대 교체 후 (flash-lite / 3.5-flash / 3.1-pro / Nano Banana Pro)

## 단계별 실측 (벽시계 기준)

| 단계 | 모델 | 소요 | 토큰 in/out | 비용 | 비고 |
|---|---|---|---|---|---|
| 업로드+메타데이터+그림추출 시작 | (gemini 분류기 포함) | 5s | — | — | 도메인·폴더명 자동 분류 정확 |
| ① screening | gemini-3.1-flash-lite | ~5s | 533/186 | $0.0004 | |
| ② citation | gemini-3.5-flash | ~9s | 2,163/1,227 | $0.0143 | 42건 인용 전수 분석 |
| ③ visual | gemini-3.5-flash | ~12s | 1,643/381 | $0.0059 | 19개 figure |
| ④ recipe | gemini-3.1-pro | ~46s | 4,145/2,346 | $0.0364 | 파라미터 15개, 재현성 0.85 |
| ⑤ deep_dive | gemini-3.1-pro | ~37s | 3,190/1,545 | $0.0249 | |
| ⑥ viz_plan | gemini-3.1-pro | ~14s | 4,375/520 | $0.0150 | 4개 다이어그램 계획 |
| Mermaid 생성 (2건) | gemini-3.1-pro | ~38s | — | — | 18:22:45→18:23:23 |
| **PaperBanana 1번째 그림** | gemini-3-pro-image + 3.5-flash critic | **iter1 71s + critic 23s** | — | ~$0.14+/iter | **iter2에서 무한 행** |

**텍스트 파이프라인 합계: 2분 4초, $0.097** — 여기까지는 병목 없음.

## 발견된 결함 (심각순)

1. **PaperBanana가 이벤트 루프를 블로킹** — 이미지 생성 동기 호출이 asyncio 루프 안에서
   실행됨. 생성 중 서버 전체(/health 포함)가 응답 불능.
2. **행 걸린 이미지 호출 + 무효한 타임아웃** — iter2 이미지 생성이 32분+ 무응답.
   bridge의 5분 타임아웃은 asyncio 타이머라서, 루프 자체가 막히면 영원히 발화 못 함.
3. **PythonManager 오판 연쇄** — health 실패 → "크래시"로 판단 → 재시작 시도 →
   기존 프로세스가 살아있어 "Process already running" → 6회 후 포기. 실제로는
   프로세스가 죽은 적 없음. 재시작 로직이 기존 프로세스를 kill하지도 않음.
4. **시각화 결과 원자성** — viz 항목들이 전부 끝난 뒤 한 번에 DB 저장. 중간에 죽으면
   Mermaid 2건 생성분도 유실. paper 상태도 'analyzing'으로 영구 고착.
5. **Critic 루프 ROI 의문** — iter1 결과에 대한 critic 수정 요구가 표기 미세조정 수준
   ("φ(t) → φ(r,t)"). 반복당 ~$0.14 + 90s인데 개선 폭이 작음.

## 관찰 (경미)

- 매 Gemini 호출마다 `Both GOOGLE_API_KEY and GEMINI_API_KEY are set` 경고 반복
- dev 로그가 DEBUG 레벨로 aiosqlite 쿼리 전문 + LLM 응답 전문을 덤프 (로그 81k줄)
- citation 입력이 2.1k 토큰 — 이 논문(8쪽)은 문제없지만 긴 논문에서 잘림 여부 관찰 필요

## 재현 방법

1. `pnpm dev`로 앱 기동
2. `curl -X POST http://127.0.0.1:8000/api/papers/upload -F "file=@<pdf>"`
3. `curl -X POST http://127.0.0.1:8000/api/analysis/<id>/run -d '{}'`
4. 모니터: 3초 간격 `/api/analysis/<id>/status` 폴링 (스크립트:
   `~/.claude/jobs/165c501a/tmp/monitor_analysis.sh`)
5. PaperBanana 시작 후 `/health` 호출 → HTTP 000이면 결함 1 재현
