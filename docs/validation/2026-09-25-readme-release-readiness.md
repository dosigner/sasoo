# v1.0.1 공개 및 README 연결 결과

2026-09-25. [v1.0.1 정식 릴리스](https://github.com/dosigner/sasoo/releases/tag/v1.0.1)를 공개했다. `isDraft=false`, `isPrerelease=false`이며 `releases/latest`도 v1.0.1을 반환한다. 공개 시각은 2026-09-25 08:33:55 UTC다.

## 커밋과 CI

- 앱/릴리스 커밋: `073835293454fd57ac2284e91b935ecb926ca139`.
- `v1.0.1` annotated tag는 위 커밋을 가리킨다.
- [Windows Build Check](https://github.com/dosigner/sasoo/actions/runs/36111906029): 성공.
- [Release](https://github.com/dosigner/sasoo/actions/runs/36112642035): macOS/Windows 빌드, 산출물 검증, 릴리스 업로드 모두 성공.
- 공개 자산 8개: macOS ZIP/DMG와 각각의 blockmap, Windows EXE/blockmap, latest-mac.yml, latest.yml.
- DMG/ZIP/EXE와 두 업데이트 manifest의 공개 URL은 모두 HTTP 200을 확인했다.

## 실제 확인한 범위

- 프런트엔드 TypeScript/lint와 314개 테스트 통과.
- Electron/공통 로직 267개 테스트 통과.
- 로컬 Python 3.14: 백엔드 1,062개 테스트 통과.
- 릴리스 Python 3.12 환경: 백엔드 1,053개 통과, 9개 건너뜀. 전체 통과로 합쳐 적지 않는다.
- 루트/프런트엔드 pnpm audit: 알려진 취약점 0건.
- 독립 복사본에서 macOS 1.0.1 빌드와 ZIP/업데이트 manifest 검사 통과.
- 로컬 ZIP 패키지의 PDF 업로드, 2쪽 이동, 확대/너비 맞춤, 질문 도우미 열기/닫기, API 키 없는 분석 요청 HTTP 400 차단, 종료 후 보관함 유지와 PDF 재열기 확인.
- 추가로 **공식 Release CI의 macOS ZIP**을 받아 공개 latest-mac.yml의 SHA-512와 크기를 대조했다. 해당 ZIP에서 꺼낸 앱도 실행해 저장된 논문과 두 PDF canvas를 다시 열었고, 인증된 backend 응답의 version=1.0.1을 확인했다.
- 실제 모델 생성 0회. smoke DB의 analysis_results와 analysis_runs 모두 0건.
- Windows는 실제 Windows CI에서 빌드/산출물을 검증했다. 설치 후 수동 GUI 조작은 미실행이다.

[구조화된 검증 기록](assets/readme-archify-2026-09-25/release-checks.json), [공식 macOS ZIP 실행 화면](assets/readme-archify-2026-09-25/v1.0.1-macos-ci-pdf.png).

## 과학 검증 및 배포 판단

사용자가 v1.0.1의 실제 공개와 연결을 핵심 요청으로 재확인하여, 현재 기술 검증 범위와 알려진 한계를 릴리스 노트에 명시하고 공개했다. 기존 원문 정확성 판정을 통과로 바꾸지 않았다. Diffusion Policy의 평가 범위/조건 귀속과 일부 미확인 정보 누락 등 기존 FAIL은 그대로다. 기본 모델을 GPT-6으로 승격하지 않았고, 새 원문 정확성 실험을 수행하지 않았다.

과거 노출 공급사 키의 폐기 여부는 이번 도구 실행으로 독립 확인하지 못했다. 이를 완료된 보안 검사로 표시하지 않는다. macOS는 미서명/미공증, Windows는 미서명이라는 배포 조건을 공개 노트에 명시했다.

## 도식과 Graphify

한영 Archify workflow/기술 구성/분석 파이프라인 6개, 각 showcase 9/9와 브라우저 크기 검사 통과. README는 언어 2개, 폭 390/1280, 밝은/어두운 배경의 8개 조합에서 이미지 21개가 모두 로드되고 가로 넘침 없이 렌더됐다.

Graphify는 앱 소스 294개와 문서 16개에서 노드 4,997개, 연결 11,023개, 커뮤니티 255개를 생성했다. 원시 추출의 dangling endpoint 678건, self-loop 26건, 무방향 병합 318건의 경고를 보존한다. 비용/토큰 사용량은 호스트 도구가 제공하지 않아 미확인이며 외부 모델 API 호출은 없다.

## 검증 도구 수정 이력

- Graphify의 stdin 기반 병렬 AST 실행이 macOS multiprocessing에서 실패해 도구가 순차 추출로 복구했다. 최종 294개 코드 파일 추출이 완료됐다.
- 최초 smoke용 임시 DB에 settings.updated_at을 빠뜨려 시작이 실패했다. 실패 DB를 보존하고 실제 앱 스키마로 새 DB를 만든 뒤 검사했다.
- 재실행 시 워크벤치 위치가 복원돼 보관함 sidebar selector가 보이지 않았다. 실제 헤더의 라이브러리 버튼으로 이동하도록 하네스를 수정했다.
- 위 하네스 수정에서 제품 소스나 테스트 기대 결과는 변경하지 않았다.
