# 실행 manifest 저장 경계 부분 구현

이 문서는 완료 보고가 아니다. 실제 분석 파이프라인, DB 마이그레이션, API에는 연결하지 않았다. 공급사 요청은 실행하지 않았다.

## 현재 구현과 관찰

`services/analysis_manifest_store.py`는 독립 aiosqlite 연결의 `BEGIN IMMEDIATE` 안에서 실행 및 attempt, 실행 중인 worker generation을 확인하고 기존 결과 갱신과 UTF-8 바이트 SHA-256 스냅샷, 이벤트, 명시적 입력 역할을 함께 기록하는 실험적 기반이다. 버전과 이벤트 및 입력 연결의 UPDATE와 DELETE는 트리거로 거부한다. 별도 테스트에서 과거 내용 복원, generation 변경 후 거부, 이벤트 저장 장애 시 롤백을 합성 SQLite DB로 확인했다. 이 원형은 삽입 경로, 캐시, 이미지, 실제 실행과 연결되지 않아 제품에서 fence를 보장하지 않는다.

실제 `run_full_analysis`는 worker generation을 받지 않고 기존 결과 저장 헬퍼는 개별 커밋을 한다. 따라서 이 원형만으로 소유권이나 소비 관계를 보장한다고 해석할 수 없다. execution 및 attempt 발급, 원문과 적용 설정 고정, 재개 충돌, 불변 이미지 바이트, 결과 삽입과 체크포인트 및 캐시 경로, 선택 실행의 복원과 완료 검증을 연결해야 한다. 현재 원형은 해당 연결 전에 소유 토큰 및 attempt 종료 조건을 강화하고 동시성, 다른 논문 참조, 장애 지점, 무결성 검사를 확대해야 한다.

기존 Gemini 텍스트와 스트림은 usage 부재를 0으로 대체하는 경로가 있다. 요청 시도 원장이 없으므로 이 값으로 청구가 없다고 판단할 수 없다. HTML 검사 격리 및 신뢰 가능한 검사 증거도 구현하지 않았다. 기존 자료를 재생성하거나 과거 요청을 재발행하지 않았다.

집중 검사: `cd sasoo/backend && ./.venv/bin/python -m pytest services/test_analysis_manifest_store.py services/test_analysis_completion.py -q`에서 59개가 통과했다. 구체적인 전제는 테스트 소스의 합성 DB를 따른다. 원형은 이미지, 실제 동시 writer, 실제 worker와 실행 재개, API나 GUI를 검증하지 않는다.

## 이번 수정 이후 회귀

- 격리 앱 데이터 디렉터리와 공급사 키를 제거한 환경에서 `python -m pytest services api models tools/test_luna_compare.py -q`: 1,281 passed, 4 skipped, 272 subtests passed. 경고 44개.
- `python -m py_compile main.py`: 통과. 별도 pycache 경로 사용.
- 프런트엔드 `pnpm test`: 45개 파일, 377개 테스트 통과. `pnpm tsc --noEmit`, `pnpm lint`: 통과.
- `pnpm build`: 기존 dist를 보존하기 위해 소스 복사본과 기존 node_modules 연결을 사용하는 별도 임시 경로에서 통과했다.
- Electron 코드는 수정하지 않았으며 격리 Electron 검사는 수행하지 않았다. 따라서 이 회귀는 최종 완료 기준이 아니다.
