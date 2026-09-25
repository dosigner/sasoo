# README 시각 자료 / README visual assets

## 한국어

2026-09-25에 한국어와 영어 README를 위해 준비한 자료입니다. 앱 화면은 `65487cedb3b537483bf1d7a17a2bc7602bed7ed0`을 기반으로 기존 미커밋 UI 변경을 포함한 개발 작업 트리에서 새로 빌드하고 캡처했습니다. 공개 v1.0.0 설치본의 화면은 아닙니다.

| 파일 | 출처와 역할 |
| --- | --- |
| `paper-connections.png` | 앞선 README 디자인 작업에서 내장 imagegen으로 만든 수정 시안. 이번 작업에서 재생성하거나 편집하지 않고 복사했습니다. 제품 화면과 과학적 결과를 나타내지 않는 브랜드 일러스트입니다. |
| `workbench-light.png` | 실제 개발 Electron의 PDF/요약 화면. OS 제목 표시줄을 제외한 화면 캡처입니다. |
| `summary-detail.png` | 같은 앱에서 섹션별 질문과 답 영역을 확대해 볼 수 있도록 캡처한 일부 영역입니다. |
| `recipe-detail.png` | 저장된 레시피 응답의 파라미터 영역입니다. 근거 검증 기록이 없어 `검증 미실행` 표시를 그대로 유지했습니다. |
| `evidence-return.gif` | 실제 Electron renderer의 화면을 CDP screencast로 녹화했습니다. Figure 2 선택, PDF 3쪽 이동, 요약 복귀를 담았습니다. GIF는 8 fps, 너비 1000px이며 캡처 타임스탬프의 간격을 유지하고 마지막 화면에 2초를 두었습니다. |
| `evidence-source.png` | GIF와 같은 근거 확인 상태의 정지 화면입니다. |

논문은 Cheng Chi 외 저자의 [Diffusion Policy: Visuomotor Policy Learning via Action Diffusion](https://arxiv.org/abs/2303.04137), arXiv v5입니다. 원본 PDF의 SHA-256은 `b65c474b696a4802d8f1457d86b637ce2c5521412570d3aa928cd54563babc8f`입니다. 논문 내용과 그림은 원저자의 저작물입니다.

요약과 레시피는 이전 비교 실행에서 저장한 `gpt-6-luna` 응답을 격리된 QA 데이터베이스로 불러왔습니다. 화면의 모델 표시는 해당 저장 결과의 출처이며, 앱의 기본 모델을 뜻하지 않습니다. 앱 기본 분석 모델은 변경하지 않았습니다. 저장된 응답의 과학적 정확성을 이 README 작업에서 다시 검증하지 않았습니다.

그림 목록은 원본 PDF 페이지를 캡션과 페이지 번호로 연결한 QA 미리보기입니다. 실제 추출 품질의 예시로 해석하면 안 됩니다. 추출 준비 상태도 QA 설정을 재사용했습니다. 요약과 레시피 두 단계만 저장된 상태이며, 전체 분석이 완료된 것으로 바꾸지 않았습니다.

캡처용 백엔드는 조회와 종료만 허용하며 모델 생성/변경 요청을 거절합니다. 백엔드와 Electron의 외부 네트워크 요청도 차단했습니다. 캡처 세션에서 관찰한 생성 요청 4건(그림 해설 2건, 재분석 2건)은 모두 HTTP 409로 차단됐습니다. 저장하지 않은 종합/실험 계획 조회는 404를 반환했으며, JavaScript page error는 0건입니다. 이번 작업의 새 모델 분석 호출은 0회입니다. 데모에서 Figure 2의 PDF 페이지가 3임을 확인했고, 복귀 전후 요약 스크롤은 2543px로 같았습니다.

## English

Prepared on September 25, 2026. App images were captured from a fresh build of the development working tree based on commit `65487cedb3b537483bf1d7a17a2bc7602bed7ed0`, including existing uncommitted UI changes. They do not depict the public v1.0.0 package.

The paper illustration was copied unchanged from the earlier built-in imagegen draft. It is a brand illustration, not an app screen or a scientific result. The other images are actual Electron captures, with the OS title bar excluded from full views and selected regions used for the summary and recipe details. The GIF records an actual Figure 2 → PDF page 3 → summary interaction through a CDP screencast. It uses 8 fps, a width of 1000px, captured frame intervals, and a two-second final hold. A still image is provided alongside it.

The source paper is [Diffusion Policy](https://arxiv.org/abs/2303.04137) by Cheng Chi et al., arXiv v5. Its PDF SHA-256 is listed above. Paper content and figures belong to their original authors.

The summary and recipe replay saved `gpt-6-luna` responses from an earlier comparison run in an isolated QA database. The model label identifies those saved responses; it does not identify the app's default model. No default model was changed, and the scientific accuracy of these responses was not revalidated for the README.

Figure cards use original PDF pages indexed by caption and page number as QA previews. They do not demonstrate extraction quality. QA extraction-readiness settings were reused. Only the summary and recipe stages have saved results; the app was not made to report a completed full analysis. Recipe values retain their unverified evidence labels.

The capture backend allowed reads and shutdown while rejecting generation and mutation requests. Both the backend and Electron blocked outbound network requests. Four observed generation requests (two figure explanations and two analysis runs) were rejected with HTTP 409. Reads for absent synthesis and experiment-plan results returned 404; there were no JavaScript page errors. No new model analysis calls were made. The demo reached PDF page 3 for Figure 2 and restored the summary scroll position exactly: 2543px before and after.

## 검증 기록 / Validation record

[validation.json](validation.json) records asset hashes, sizes, source hashes, navigation checks, and local README render checks. Both READMEs were rendered at widths of 390px and 1280px on light and dark backgrounds, using a local CommonMark renderer with tables and GitHub-like CSS. This is local rendering evidence, not a claim of GitHub server rendering, scientific validation, or packaged-app validation.


## 기술 배지와 도식 추가 / Badges and diagrams

같은 날짜의 후속 편집에서 한영 README에 기술 배지 12개와 Mermaid 도식 3개(읽기 workflow, 시스템 구성, 주요 분석 단계)를 추가했습니다. 배지는 [Shields.io](https://shields.io/badges/static-badge)에서 제공하는 SVG이며, 표시한 버전은 패키지 선언 또는 릴리스 CI 기준입니다. 배지는 실행 검증이나 품질 인증을 나타내지 않습니다. 각 배지는 실제 설정 파일로 연결됩니다.

도식은 [GitHub에서 지원하는 Mermaid 코드 블록](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams)입니다. 주요 분석 단계의 순서는 저장소의 `analysis_execution.py`를 확인했습니다. 기존 이미지와 GIF는 변경하지 않았습니다. 새 문서는 한영, 390px/1280px, 밝은/어두운 배경 8개 조합에서 이미지 18개(기술 배지 12개 포함)와 Mermaid 도식 3개의 로딩/렌더를 확인했습니다. 가로 넘침과 JavaScript page error는 없었습니다.

A follow-up edit on the same date added 12 technology badges and three Mermaid diagrams to each README: reading workflow, system architecture, and the main analysis stages. Shields.io supplies the SVG badges; version labels reflect package declarations or release CI, and each badge links to its configuration. They do not indicate test results or quality certification. Pipeline order was checked against `analysis_execution.py`.

Existing images and the GIF were unchanged. Local rendering used the installed Mermaid dependency and loaded all 18 images (including 12 badges) plus three diagrams in each of the eight language, viewport, and theme combinations. No horizontal overflow or JavaScript page errors were observed. GitHub's own Mermaid renderer was not exercised.


## 현재 도식 형식 / Current diagram format

후속 Archify 편집으로 README의 Mermaid 코드 블록 세 개를 Archify의 한영 SVG 도식과 탐색용 HTML 링크로 교체했습니다. 위 Mermaid 기록은 이전 편집 단계의 검사 이력입니다. 현재 검증과 명세/HTML/내보내기 해시는 [Archify 검증 기록](../architecture-2026-09-25/validation.json)에 있습니다. 앱 화면과 GIF는 변경하지 않았습니다.

The subsequent Archify edit replaced the three Mermaid blocks with bilingual SVG diagrams and downloadable explorable HTML. The Mermaid checks above describe the earlier revision. See the linked Archify manifest for current diagram validation and hashes. App screenshots and the GIF were unchanged.
