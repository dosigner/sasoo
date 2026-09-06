# Sasoo 효율성 개선 실행 계획

**Goal:** 진단 보고서의 주요 개선안 1~10을 기존 변경 위에 적용하고 항목별 근거를 남긴다.
**Architecture:** React 요청 트리거와 SQLite 반환 행을 줄이고, 파일 검사는 요청 안에서 재사용한다. 분석 실행은 서비스가 소유하고 기존 HTTP 계약을 보존한다.
**Tech Stack:** 기존 Electron, React/Vite, FastAPI, aiosqlite, pnpm, pytest/vitest.
**Spec:** `output/codebase-efficiency-2026-09-06/report.md`

## 제약

- 기존 사용자 변경 8개와 미추적 산출물 보존. 커밋, 푸시, 배포, 유료 모델 호출 제외.
- DB와 라이브러리는 임시 경로로 격리. Java 단일 모드, artifact stale 검사 유지.
- Windows 실행 검증과 macOS 정적 검증을 구분. 추정 속도 개선률 제시 금지.

## 구현 및 검증 체크리스트

- [x] 1. `hooks/useAnalysis.ts`, `api/analysis_routes.py`: 완료 변화/세션/갱신 기준 결과 조회, 상태 계산 재사용. 요청 횟수, 재시도, 재분석, 완료 상태 검증.
- [x] 2. `api/settings.py`, `main.py`, `services/model_registry.py`: 초기화와 SELECT 조회 분리. 반복 쓰기 0회, 설정 변경과 키 마이그레이션 검증.
- [x] 3. `api/papers.py`, `services/artifact_status.py`, `services/odl_parser.py`: 두 일괄 집계, manifest/signature 공유, blocking executor 사용. 20/100개 SQL 수, 누락 PDF/그림, health 동시 응답 검증.
- [x] 4. `services/analysis_results.py`, `models/database.py`: 최신 ID SQL 선별. 빈 필터, 동률/NULL, 손상 JSON, error/다른 논문 분리 검증.
- [x] 5. `frontend/vite.config.ts`, Mermaid/내보내기 경로: 실제 lazy chunk 분리. 프로덕션 그래프와 종합 뷰/ZIP 확인.
- [x] 6. `hooks/usePapers.ts`, `models/schemas.py`, 목록 응답: 동일 필터 가드, completed_count, 최신 요청만 반영. 초기 호출/응답 역전 검증.
- [x] 7. `services/paper_library.py`: 현재 전체 참조 검색 후 삭제. 전체 테스트와 격리 API CRUD 검증.
- [x] 8. `.github/workflows/build-check.yml`: clean 선행, 빌드 산출물 재사용, artifact verifier 유지. 명령 그래프 정적 검사와 로컬 컴파일 수행.
- [x] 9. `services/analysis_supervisor.py`: SQL SUM. 빈 월/NULL/error/12월/한도 경계 검증.
- [x] 10. 분석 라우터/워커, `artifact_status.py`, `AnalysisPanel.tsx`: 실행 서비스 및 실제 구획 추출, 카운트 helper 통합. 호출 방향, 취소/실패/generation, 전체 회귀 검증.

## 진행

- 완료: 10개 항목 구현 및 로컬 검증. 최종 backend 849, frontend 188, Electron/TS 209 통과. Windows 실행 검증 제한은 결과 문서에 명시.
- 검증 결과는 `output/codebase-efficiency-2026-09-06/implementation*.md`에 기록한다.
