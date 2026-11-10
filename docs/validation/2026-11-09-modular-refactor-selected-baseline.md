# 모듈 리팩토링 선택 기준선

사용자는 기존 미커밋 작업을 보존한 현재 작업 트리의 격리 스냅샷을 기준으로 선택했다. 원본에서 커밋, reset, stash, 정리 또는 데이터 삭제는 수행하지 않았다. 이 기록 자체는 스냅샷 생성 이후에 작성됐다.

## 스냅샷

- 위치: `/Users/dongj/dev/.sasoo-refactor-baselines/2026-11-09-worktree.dhiWhiN8/tree/`
- 기준 HEAD: `3d0e7d20abf251341ca4396eeb8dc981e2b0b643`. 이 HEAD만으로 스냅샷 내용을 재현할 수 없다. 스냅샷은 그 위의 미커밋 수정과 미추적 파일도 포함한다.
- Git이 인식하는 tracked 파일과 무시되지 않은 untracked 파일 23,414개를 복사했다. 무시된 파일은 포함하지 않았다. 특히 원본 `.env`, `.venv`, 사용자 라이브러리 등은 이 기준선에 포함되지 않는다. `.git` 및 Git 이력도 복사하지 않았다.
- 복사 전후의 Git 파일 목록과 상태가 바뀌지 않았고, `rsync`의 checksum 비교에서 비디렉터리 파일 차이는 없었다. 검증에서 디렉터리 메타데이터 차이는 있었다. 파일 내용 기준의 비교이며 디렉터리 시각과 권한까지 동일하다는 뜻은 아니다.
- 파일별 SHA-256, 파일 크기, 모드, 심볼릭 링크 대상은 상위 폴더 `manifest.sha256.jsonl`에 보관했다. manifest 자체의 SHA-256은 `9cc3721d2b8d35f33de5eeca24dbaeab63535342277e4efc839216b49e3c5db0`이다. 목록과 스냅샷은 별도 사용자 전용 디렉터리에 보관한다.

## 독립 검증

선택된 스냅샷에서 backend 소스와 필요한 고정 테스트 자료를 별도 임시 폴더로 복사했다. 스냅샷 backend와 검증 복사본 사이 checksum 비교에서 비디렉터리 파일 차이는 없었다. 기존 backend 가상환경의 Python 3.14 실행 파일과 의존성을 사용했다. 별도 HOME, 앱 데이터, 임시 디렉터리 및 Java 임시 경로를 지정하고 macOS sandbox에서 외부 송신과 격리 폴더 밖의 쓰기를 차단했다. 실제 `.env`와 사용자 라이브러리는 사용하지 않았다.

`python -m pytest services api models tools --disable-warnings -q` 결과: **1,359 passed, 7 skipped, 236 subtests passed**. 외부 socket 가드의 차단 2건은 테스트 양성 대조다. 로그는 `/private/tmp/sasoo-baseline-check.deNC6xzZ/baseline.log`에 있으며 임시 파일이다.

## 범위와 한계

이 스냅샷은 선택한 **파일 내용 기준선**이다. 별도 commit과 `.git`이 없으므로 마스터 플랜 0-A에 적힌 깨끗한 Git HEAD worktree 검증을 수행한 것은 아니다. 사용자 선택에 따라 기존 작업 트리 전체를 보존하는 기준으로 진행한다. Python 3.12 CI, Windows, 실제 사용자 DB 및 라이브러리, Electron GUI와 패키징 앱, 외부 공급사와 실제 청구는 검증하지 않았다. 네트워크 가드의 기록은 해당 Python 메서드 범위이며, sandbox의 모든 연결 시도를 전수 계측한 것은 아니다.
