# 원본 PDF 분석과 최신 읽기 화면 통합

2026-09-24에 원본 PDF/요약 계약 변경과 최근 GUI 수정을 같은 소스에 통합했다. 기본 OpenAI 모델은 `gpt-5.6-luna`다. `gpt-6-luna`는 비교 도구에서 사용할 수 있는 후보이며 운영 기본값으로 승격하지 않았다.

## 통합 범위

- OpenAI 원본 PDF 입력, 응답 체인과 캐시 재시작, 입력 범위 메타데이터.
- 엄격한 새 요약 검증과 구형 결과 읽기 호환, 실패 응답의 사용량 보존.
- 캐시 읽기/쓰기와 요청별 비용 계산, 누적 예산을 관리하는 비교 CLI.
- 핵심 본문, 질문/짧은 답, 펼침 설명과 출처, 적용 조건, 내보내기.
- 최신 라이트/다크 화면, 읽기 위치 표시와 출처 왕복, 상태 표시, PDF WASM 자산.
- 종합 생성 단계의 PDF/응답 체인과 캐시 식별자, 저장된 실패 상태와 미확인 사용량 복원.
- 미확인 사용량의 보고서 표시와 알려진 부분 합계, 독립 HTML의 자동 외부 요청 차단.

## 자동 검사

제품 소스 커밋 `5649e9590314985b0ee3f9d22f6b635e2fede150`과 같은 파일 내용으로 실행했다. 각 최종 검사 전후 백엔드 소스 128개와 프런트엔드 소스 153개의 해시가 일치했다.

| 검사 | 결과 |
|---|---:|
| 백엔드 `services api models tools/test_luna_compare.py` | 1,078 tests, 223 subtests 통과 |
| 별도 `tools/test_provider_compare.py` | 22 tests 통과 |
| 프런트엔드 Vitest | 314 tests 통과 |
| Electron Vitest | 269 tests 통과 |
| 프런트엔드 타입 검사, lint, build | 통과 |
| Electron compile, backend entrypoint compile | 통과 |

재현 명령:

```bash
cd sasoo/backend
./.venv/bin/python -m py_compile main.py
./.venv/bin/python -m pytest services api models tools/test_luna_compare.py tools/test_provider_compare.py -q
cd ../frontend
pnpm test
pnpm tsc --noEmit
pnpm lint
pnpm build
cd ..
pnpm test:unit
pnpm build:electron
```

독립 검토에서 발견한 PDF 종합 연결 누락, nullable 사용량의 보고서 오류/완료 상태 오인, HTML 이미지 사전 요청은 실패 회귀검사를 보존하고 수정했다. 독립 재검토와 실제 GUI 검사는 이 자동 검사와 구분하며 해당 PR의 검증 기록을 따른다. 자동 검사 통과는 논문 내용의 정확성이나 패키지 실행의 통과를 뜻하지 않는다.

## 모델 비교의 결론 유지

2026-09-23에 같은 원본 PDF 6편으로 최초 비교 12회와 대표 역할 5회를 실행했다. 두 모델 모두 6편의 생성 완료/형식 검사는 통과했지만, 필수 조건과 근거 누락을 포함한 엄격한 원문 기준 통과는 5.6이 1/6, 6이 0/6이었다. 후보 판정은 `candidate_failed`다.

이 표본에서 6의 사용량 기반 비용은 56.45% 낮았고 논문별 생성 시간 비율의 중앙값은 0.5272였다. 단회 비교이며 일반적인 성능 우월성의 증거가 아니다. 기존 22회와 신규 17회를 합친 누적 추정 비용은 US$0.58928133, 미정산 요청은 0건이다. 이 통합 작업은 추가 유료 생성을 실행하지 않았다.

원응답, 비용 원장과 GUI 촬영 기록은 로컬 검증 자산으로 보존했다. 원본 논문, 검증용 DB, 인증정보와 대용량 임시 캡처는 이 소스 통합 커밋에 포함하지 않는다. 비교 CLI의 실제 실행에는 별도로 준비한 원문 manifest와 누적 원장이 필요하다.

모델 승격, 버전 변경과 공개 릴리스는 이 소스 통합의 결과로 자동 수행하지 않는다.
