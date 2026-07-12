# Gemini Interactions API 전환 + 에이전트 편성 UX 재설계

날짜: 2026-07-12
브랜치 기점: feature/gui-redesign
상태: 사용자 승인 완료 (설계 대화에서 섹션별 승인)

## 배경과 문제

1. **에이전트 편성 UX**: `sasoo/frontend/src/pages/Agents.tsx`(1,399줄)는 에이전트 1개를 만드는 데
   생성 방식 선택 모달 → 기본 정보 폼 → 4개 탭(Screening/Visual/Recipe/DeepDive) 프롬프트 편집 →
   Raw 마크다운/YAML 편집까지 요구한다. 그러나 백엔드 실체는 고정 6단계 파이프라인에
   도메인별 프롬프트 오버레이 1개가 자동 선택되는 구조라, UI 복잡도가 실제 기능과 비례하지 않는다.
   연구자(비개발자)가 쓸 수 없는 수준이다.
2. **구식 API**: 백엔드는 이미 100% Gemini이지만(`google-genai` SDK) 구식 `generate_content`
   단발 호출을 쓴다. 매 단계마다 이전 결과와 문서 컨텍스트를 텍스트로 이어붙여 재전송하므로
   토큰 낭비가 크고, thought signature·서버측 상태 유지 등 신기능을 못 쓴다.

## 확정된 방향 (사용자 결정)

| 결정 항목 | 선택 |
|---|---|
| 작업 범위 | API 전환 + UX 단순화 동시 진행 |
| 편성 UX | 에이전트 개념 자체를 숨김 (자동 분야 감지) |
| 상태 관리 | 상태 유지 (`store=true`, `previous_interaction_id` 체인) |
| 모델 편성 | 본 파이프라인 `gemini-3.5-flash` 단일화, 스크리닝은 `gemini-3.1-flash-lite` 유지 |
| 페르소나 | 보이는 쪽만 유지 (편성/편집 UI 제거, 캐릭터 연출 유지) |
| 아키텍처 | B. 하이브리드 체인 (스크리닝 독립 호출 + 본 분석 단일 체인) |

## 백엔드 설계

### 1. LLM 클라이언트 계층 통합

- `services/llm/gemini_client.py` + `api/analysis_helpers.py`의 `_call_gemini()`를
  새 모듈 `services/llm/interactions_client.py` 하나로 통합.
- 제공 기능: `client.interactions.create` 래핑, 재시도 3회(기존 정책 유지),
  `interaction.usage` 기반 비용 기록(`total_thought_tokens` 포함),
  Pydantic 스키마 → `response_format={"type":"text","mime_type":"application/json","schema":...}` 변환.
- SDK: `google-genai` ≥ 2.3.0 으로 업그레이드.
- Gemini 3.5 권장에 따라 `temperature`/`top_p`/`top_k` 제거, `thinking_budget` → `thinking_level`.

### 2. 문서 처리: PDF 직접 입력

- 분석 시작 시 논문 PDF를 Files API로 1회 업로드, `file_uri`를 DB에 저장.
- 파일 유효기간 48시간 → 재분석/체인 재개 시 만료면 자동 재업로드.
- 기존 `document_context`(사전 추출 텍스트+피규어 캡션을 프롬프트에 삽입) 방식은
  체인 첫 호출에 PDF 원본(`{"type":"document","uri":...}`)을 넣는 방식으로 대체.
  Gemini가 레이아웃·그림·표를 직접 보므로 추출 파이프라인 코드가 크게 줄어든다.
- 제한: PDF 최대 50MB/1,000페이지, 페이지당 258토큰.

### 3. 파이프라인 재구성 (`_run_full_analysis`)

- **스크리닝**: 독립 stateless 호출, `gemini-3.1-flash-lite`, structured output으로
  `{domain, summary, ...}` 반환. 분야 자동 감지 → 페르소나 자동 선택이 여기서 일어난다.
- **본 체인**: `gemini-3.5-flash` 단일 모델.
  - 첫 interaction(Visual): PDF 파일 참조 + system_instruction
    (페르소나·도메인 오버레이 + 연구 분야 소개 + 분석 초점 + 설명 수준).
  - 이후 Recipe → Deep Dive → Viz 플래닝을 `previous_interaction_id`로 연결.
  - `previous_interaction_id` 사용 시에도 system_instruction과 tools는 매 호출 재지정 필요(문서 명시).
  - 각 단계 Pydantic 스키마 structured output.
  - 단계별 `thinking_level`: Visual=low, Recipe=medium, DeepDive=high, Viz플래닝=medium.
- **체크포인트**: 각 단계 완료 시 interaction id를 DB에 저장 → 중간 실패 시 실패 지점부터
  체인 재개 (기존 viz 체크포인트 패턴과 동일 접근).
- thought signature는 stateful 모드에서 서버가 자동 관리 — 클라이언트 처리 불필요.

### 4. 에이전트 시스템 강등

- `.md` 에이전트 로더(`services/agents/md_loader.py`)는 백엔드 내부 리소스로 유지.
  번들 4종(photon/cell/neural/circuit) + 사용자 커스텀 디렉토리 계속 로드(기존 사용자 보호).
- 에이전트 CRUD API 중 생성/편집/AI초안(`POST /api/agents/generate` 등) 엔드포인트 제거,
  조회(페르소나 표시용)만 유지.
- `agent_profiles/*.yaml`은 `.md`와 중복인 레거시 → 이번에 제거.

### 5. 잔재 정리

- `services/pricing.py`의 Claude 가격 테이블 제거, `gemini-3.5-flash` 가격 반영.

## 프론트엔드 UX 설계

### 1. Agents 페이지 제거

- `Agents.tsx`와 사이드바 "에이전트" 메뉴 제거. 편성·생성·프롬프트 편집 UI 전부 삭제.
- 메뉴 구성은 기존 OpenAI Platform 스타일 리디자인 스펙(81a99ea)과 정합 유지.

### 2. 연구자 설정 (설정 페이지)

- `연구 분야 소개` 한 줄 입력(`research_context`): 분석 체인 system_instruction에 삽입.
  비우면 자동 감지에만 의존.
- `기본 설명 수준`: 아래 6단계 슬라이더의 전역 기본값. 기본 석사생.

### 3. 페르소나 = 만나는 존재

- 업로드 → 스크리닝 완료 시 감지된 분야 배지 + 자동 선택 페르소나(이름·아바타) 표시.
- 채팅·피규어 설명의 캐릭터 연출(이름·말투·인용구)은 현행 유지.
- 페르소나 배지에 변경 드롭다운(번들 4종 + 사용자 커스텀) 1개 — 유일한 "에이전트 선택" UI.
- 감지 실패/매칭 없음 → `general` 페르소나 폴백(현행 유지).

### 4. 분석 초점 (논문별, 업로드 시점)

- 빠른 초점 칩(복수 선택): `재현 방법` `핵심 기여` `한계·후속 연구` `수식·이론` `선행연구 대비`.
  44px 터치 타깃.
- 자유 입력 한 줄 "이 논문에서 특별히 궁금한 점" (선택, 상시 라벨 + 헬퍼 텍스트,
  placeholder-only 금지). 비우면 균형 분석.
- 값은 본 체인 system_instruction에 반영되어 Recipe/Deep Dive 비중을 조절.

### 5. 설명 수준 6단계 슬라이더

- 단계: `초등학생 – 중학생 – 고등학생 – 학부생 – 석사생 – 박사생` (불연속 discrete).
- 각 스텝 라벨 상시 표시(색상만으로 구분 금지), 선택 스텝은 굵기+색 강조.
- 슬라이더 아래 실시간 예시 문장 프리뷰: 같은 개념을 선택 수준의 문체로 보여줌
  (프론트에 하드코딩된 예시 문장 6개, LLM 호출 없음).
- 배치: 설정(전역 기본값) + 업로드 화면(논문별 오버라이드, 접힌 상태 기본 —
  progressive disclosure) + 결과 화면(재노출).

### 6. 수준 변경 = 체인 연장 (Interactions API 대표 활용)

- 분석 완료 후 결과 화면에서 수준 변경 시 전체 재분석 없이 기존 체인에
  "이 섹션을 ○○ 수준으로 다시 써줘" interaction 1개 추가.
  서버가 PDF·분석 컨텍스트를 보유하므로 재업로드/재분석 비용 없음.
- 수준별 재작성 결과는 캐시 — 슬라이더를 오가도 재호출하지 않음.
- 체인 interaction id가 만료·유실된 경우(55일 보관 한도 등) 폴백:
  해당 섹션 원문을 포함한 새 stateless 호출로 재작성.

## 에러 처리

- 도메인 감지 실패 → `general` 페르소나 폴백.
- 체인 중간 실패 → 저장된 interaction id에서 재개. 진행률 UI는 기존과 동일.
- Files API 만료(48h) → 자동 재업로드 후 체인 재개.
- interaction 보관 만료 → 섹션 재작성은 stateless 폴백(위 6번).

## 테스트

- `interactions_client`: `interactions.create` 목킹 단위 테스트 —
  체인 연결(previous_interaction_id 전달), 재시도, 파일 만료 재업로드, structured output 파싱.
- 파이프라인: 실제 논문 PDF 1건 엔드투엔드 스모크 테스트, 단계별 결과 스키마 검증.
- 프론트: Agents 라우트 제거 후 빌드 통과 + 기존 화면 회귀 확인,
  업로드 화면 초점/수준 컨트롤 동작 확인.

## 범위 밖 (이번 작업에서 안 함)

- 이미지 생성 프로바이더(OpenAI gpt-image-2 / Gemini Nano Banana) 구조 변경 —
  기존 `figure_gen` 유지.
- 에이전트 채팅(`chat_with_agent`)의 체인 전환 — 분석 파이프라인 안정화 후 후속 작업.
- Batch API (Interactions API 미지원).
