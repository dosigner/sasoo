<div align="center">

<img src="sasoo/docs/assets/logo.png" alt="Sasoo 로고" width="96" />

# Sasoo

### 논문을 읽고, 근거로 돌아가다

PDF 원문 옆에서 논문의 흐름을 이해하고, 그림과 표를 확인하고, 실험 조건을 정리하는 AI 연구 워크벤치.

<p align="center">
  <a href="sasoo/package.json"><img src="https://img.shields.io/badge/Electron-43-47848F?style=for-the-badge&amp;logo=electron&amp;logoColor=white" alt="Electron 43" /></a>
  <a href="sasoo/frontend/package.json"><img src="https://img.shields.io/badge/React-19-149ECA?style=for-the-badge&amp;logo=react&amp;logoColor=white" alt="React 19" /></a>
  <a href="sasoo/frontend/package.json"><img src="https://img.shields.io/badge/TypeScript-6-3178C6?style=for-the-badge&amp;logo=typescript&amp;logoColor=white" alt="TypeScript 6" /></a>
  <a href="sasoo/frontend/package.json"><img src="https://img.shields.io/badge/Vite-8-646CFF?style=for-the-badge&amp;logo=vite&amp;logoColor=white" alt="Vite 8" /></a>
  <a href="sasoo/frontend/package.json"><img src="https://img.shields.io/badge/Tailwind%20CSS-4-0F766E?style=for-the-badge&amp;logo=tailwindcss&amp;logoColor=white" alt="Tailwind CSS 4" /></a>
  <a href=".github/workflows/release.yml"><img src="https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&amp;logo=python&amp;logoColor=white" alt="Python 3.12" /></a>
</p>

<p align="center">
  <a href="sasoo/backend/requirements.txt"><img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&amp;logo=fastapi&amp;logoColor=white" alt="FastAPI" /></a>
  <a href="sasoo/backend/requirements.txt"><img src="https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&amp;logo=sqlite&amp;logoColor=white" alt="SQLite" /></a>
  <a href="sasoo/frontend/package.json"><img src="https://img.shields.io/badge/PDF.js-C43D2D?style=for-the-badge" alt="PDF.js" /></a>
  <a href="sasoo/frontend/package.json"><img src="https://img.shields.io/badge/Mermaid-C43778?style=for-the-badge&amp;logo=mermaid&amp;logoColor=white" alt="Mermaid" /></a>
  <a href="sasoo/backend/services/model_registry.py"><img src="https://img.shields.io/badge/OpenAI-412991?style=for-the-badge" alt="OpenAI" /></a>
  <a href="sasoo/backend/services/model_registry.py"><img src="https://img.shields.io/badge/Gemini-8861DD?style=for-the-badge&amp;logo=googlegemini&amp;logoColor=white" alt="Gemini" /></a>
</p>

<sub>개발 소스의 기술 스택. 배지를 누르면 실제 의존성 또는 모델 설정으로 이동합니다.</sub>

[**다운로드**](https://github.com/dosigner/sasoo/releases/latest) | [시작하기](#시작하기) | [개발](#개발) | [English](README.en.md)

<img src="sasoo/docs/assets/readme-2026-09-25/paper-connections.png" alt="논문 속 강조 구절이 그림과 메모로 이어지는 보라색 연결선. 제품의 읽기 흐름을 표현한 AI 생성 일러스트입니다." width="900" />

</div>

## 원문과 해설을 한 화면에서

Sasoo는 논문을 읽는 동안 원문을 곁에 둡니다. 요약에서 전체 흐름을 잡고, 섹션별 질문으로 내용을 따라가며, 연결된 Figure와 Table을 눌러 근거를 확인할 수 있습니다. PDF와 분석 결과는 로컬 라이브러리에 보관해 다시 열어 볼 수 있습니다.

> **개발 미리보기:** 아래 화면과 기능 설명은 2026-09-25 개발 작업 트리 기준입니다. 저장된 분석을 불러온 한국어 UI이며, 일부 화면 변경은 미커밋 상태입니다. 공개 설치본은 [v1.0.0](https://github.com/dosigner/sasoo/releases/tag/v1.0.0)으로, 화면과 기능이 다를 수 있습니다. v1.0.1은 검증 중입니다.

<p align="center">
  <img src="sasoo/docs/assets/readme-2026-09-25/workbench-light.png" alt="왼쪽의 Diffusion Policy 원본 PDF와 오른쪽의 요약을 나란히 보여주는 Sasoo 개발 화면" width="1000" />
</p>

## 논문 한 편의 workflow

PDF를 올리고 분석을 시작한 뒤, 해설과 원문을 오가며 읽습니다. 저장된 결과는 라이브러리에서 다시 열 수 있습니다.

<p align="center">
  <a href="sasoo/docs/assets/architecture-2026-09-25/reading-workflow.ko.svg"><img src="sasoo/docs/assets/architecture-2026-09-25/reading-workflow.ko.svg" alt="PDF 업로드, 문맥 준비, 외부 AI 분석, 워크벤치 읽기와 근거 복귀, 로컬 저장을 연결한 workflow" width="1000" /></a>
</p>

[확대 보기](sasoo/docs/assets/architecture-2026-09-25/reading-workflow.ko.svg) | [탐색용 HTML](sasoo/docs/assets/architecture-2026-09-25/reading-workflow.ko.html)

도식은 Archify로 제작했습니다. 탐색용 HTML은 파일을 내려받아 브라우저에서 열면 검색, 확대, 연결 관계 탐색을 사용할 수 있습니다. 한국어 도식의 고정 뷰어 버튼은 영어입니다.

## 읽는 동안 필요한 도구

### 질문을 따라 논문 이해하기

**요약**에서 문제, 기존 접근, 해결 원리, 결과와 한계를 읽습니다. 섹션별 질문과 짧은 답을 먼저 훑고, 필요한 곳에서 근거와 설명을 펼쳐 보세요. **읽기 안내**에는 원문에서 확인할 질문과 조건이 모입니다.

<p align="center">
  <img src="sasoo/docs/assets/readme-2026-09-25/summary-detail.png" alt="논문 섹션별 질문, 짧은 답, 근거와 설명 펼치기 버튼을 보여주는 요약 확대 화면" width="685" />
</p>

### 설명에서 그림과 표로, 다시 읽던 곳으로

요약에 연결된 Figure/Table을 누르면 해당 자료와 PDF 페이지로 이동합니다. **요약으로 돌아가기**를 누르면 읽던 위치로 복귀합니다. 연결할 원문 자료가 있는 참조에서 사용할 수 있습니다.

<p align="center">
  <img src="sasoo/docs/assets/readme-2026-09-25/evidence-return.gif" alt="요약의 Figure 참조를 눌러 그림과 원본 PDF 페이지를 확인한 뒤 요약의 같은 위치로 돌아오는 실제 앱 동작" width="1000" />
</p>

요약의 참조 선택 → 그림과 PDF 페이지 확인 → 요약으로 복귀. 데모의 그림 미리보기는 원본 PDF 페이지를 사용합니다. [정지 화면 보기](sasoo/docs/assets/readme-2026-09-25/evidence-source.png).

### 실험 조건을 다음 작업에 활용하기

**레시피**에서 실험 절차와 파라미터를 모아 보고 CSV로 내보낼 수 있습니다. 값과 함께 근거 상태, 빠진 정보를 확인하세요. 아래 예시의 **검증 미실행**은 해당 값의 근거 검증 기록이 없다는 뜻입니다.

<p align="center">
  <img src="sasoo/docs/assets/readme-2026-09-25/recipe-detail.png" alt="실험 파라미터의 이름, 값, 설명과 검증 미실행 표시가 함께 있는 레시피 확대 화면" width="685" />
</p>

워크벤치에는 **요약, 종합, 읽기 안내, 그림, 표, 레시피** 여섯 탭이 있습니다. 종합 화면은 주요 내용을 한데 모으고, 채팅에서는 논문과 분석에 관해 후속 질문을 할 수 있습니다. 분야별 에이전트 Photon(광학), Cell(바이오), Neural(딥러닝), Circuit(회로)이 설명의 관점을 조정하며, 사용자 데이터 폴더의 Markdown 파일로 에이전트를 확장할 수 있습니다.

AI 해설과 추출 값은 원문과 대조해 사용하세요. 분석 완료나 출처 링크가 정확성 또는 실험 재현성을 보장하지는 않습니다. 일부 원문만 제공한 분석은 전체 논문을 검토한 결과가 아닙니다. 화면은 저장된 응답의 표시와 탐색 예시이며, [캡처 출처와 범위](sasoo/docs/assets/readme-2026-09-25/PROVENANCE.md)에 제작 기준을 기록했습니다.

## 시작하기

1. **설치:** [공식 GitHub Releases](https://github.com/dosigner/sasoo/releases/latest)에서 운영체제에 맞는 파일을 받아 설치합니다.
2. **설정:** 사용할 공급사의 API 키를 입력하고, 공급사 선택, 라이브러리 경로, 자동 분석 설정을 확인합니다.
3. **첫 논문:** PDF를 업로드한 뒤 분석을 시작하고, 워크벤치에서 원문과 결과를 나란히 읽습니다. 자동 분석을 켜 두면 업로드 후 API 요청이 시작될 수 있습니다.

**외부 AI API 사용료는 별도입니다.** API 키와 해당 모델을 사용할 권한이 필요하며, 무료 분석을 보장하지 않습니다.

### 설치 파일

2026-09-25 확인한 공개 버전은 **v1.0.0**입니다.

| 플랫폼 | 공식 릴리스 파일 | 참고 |
| --- | --- | --- |
| macOS Apple Silicon | [DMG](https://github.com/dosigner/sasoo/releases/download/v1.0.0/Sasoo-1.0.0-arm64.dmg) / [ZIP](https://github.com/dosigner/sasoo/releases/download/v1.0.0/Sasoo-1.0.0-arm64-mac.zip) | 미서명, 미공증 |
| Windows x64 | [설치 EXE](https://github.com/dosigner/sasoo/releases/download/v1.0.0/Sasoo-Setup-1.0.0.exe) | 미서명, SmartScreen 경고 가능 |

Linux와 Intel Mac용 공식 설치 파일은 없습니다. Linux 소스 빌드 명령은 있지만, 위 배포 지원 범위에는 포함되지 않습니다.

<details>
<summary>macOS에서 실행이 차단될 때</summary>

공식 릴리스에서 받은 `Sasoo.app`를 `/Applications`로 옮깁니다. Gatekeeper가 실행을 차단할 때만 출처를 확인한 해당 앱에 다음 명령을 사용하세요.

```bash
xattr -dr com.apple.quarantine /Applications/Sasoo.app
```

필요하면 Finder에서 앱을 우클릭하고 **열기**를 선택합니다. 이 명령은 quarantine 보호를 제거하며, 발행자를 검증하거나 Apple 서명/공증을 대신하지 않습니다. 제3자가 배포한 앱에는 사용하지 마세요.

</details>

<details>
<summary>Windows에서 SmartScreen 경고가 나올 때</summary>

공식 릴리스의 설치 EXE를 실행합니다. 미서명 빌드는 알 수 없는 게시자로 표시될 수 있습니다. 공식 다운로드 출처를 확인한 경우에만 **추가 정보 → 실행**을 선택하세요.

</details>

## API 키와 비용

OpenAI와 Gemini 중 사용할 공급사를 설정에서 선택합니다. 한 공급사의 키만 저장했다면 사용 가능한 키에 맞춰 공급사가 선택됩니다. 키를 저장했더라도 잔액, 권한 또는 모델 접근 제한으로 요청이 실패할 수 있습니다.

| 공급사 | API 키 발급 | 사용 기능 |
| --- | --- | --- |
| OpenAI | [OpenAI API 키](https://platform.openai.com/api-keys) | 논문 분석, 채팅, 그림 해설, 개념도 생성 |
| Gemini | [Google AI Studio](https://aistudio.google.com/apikey) | 논문 분석, 채팅, 그림 해설, 개념도 생성 |

개발 소스의 기본 분석 공급사는 OpenAI이며 텍스트 분석 모델은 `gpt-5.6-luna`입니다. 이미지 생성 모델과 단계별 배정은 별도로 관리됩니다. 실제 배정은 [모델 레지스트리](sasoo/backend/services/model_registry.py)와 [모델 ID](sasoo/backend/services/models.py)에서 확인할 수 있습니다.

설정 화면의 비용은 보고된 사용량과 앱에 등록된 단가로 계산한 **추정치**입니다. 공급사의 청구액과 다를 수 있으며, 사용량을 확인하지 못한 요청이 무료라는 뜻은 아닙니다.

## 데이터와 개인정보

**보관은 로컬에서, AI 처리는 외부 API에서 이루어집니다.** PDF와 분석 결과는 로컬 라이브러리에 저장됩니다. 분석, 채팅, 이미지 생성 시에는 기능에 필요한 자료가 선택한 공급사로 전송됩니다.

| 작업 | 외부 API에 전달될 수 있는 자료 |
| --- | --- |
| 논문 분석 | 원본 PDF, 추출 텍스트, 그림과 표 이미지 |
| 채팅 / 그림 해설 | 질문, 관련 원문과 분석 내용, 대상 이미지 |
| 개념도 생성 | 분석을 바탕으로 만든 설명과 생성 요청 |

개발 소스의 OpenAI 분석은 원본 PDF를 `input_file`로 첨부하며, Gemini 분석도 PDF를 공급사에 업로드할 수 있습니다. 로컬 Java 파서로 추출하더라도 이후 AI 처리에서 외부 전송이 일어날 수 있습니다. 생성 개념도는 논문 원본 그림과 구분합니다.

전송할 권한이 있는 문서를 사용하고 공급사의 데이터 정책을 확인하세요. API 키는 로컬에서 암호화해 저장하고, 암호화 키는 macOS Keychain 또는 Windows Credential Manager 등 OS 자격 증명 저장소에 보관합니다. 구형 `.sasoo_key`는 가능한 경우 자동 이전하며, 이전할 수 없거나 폐기한 API 키는 다시 입력해야 합니다.

## 개발

앱 코드는 `sasoo/`에 있습니다. Electron이 React/Vite 화면과 로컬 FastAPI 백엔드를 실행하며, SQLite와 파일시스템에 데이터를 보관합니다. PDF 추출에는 Java 기반 OpenDataLoader를 사용합니다.

### 시스템 구성

로컬 앱의 화면, 분석 엔진, 저장소와 외부 AI 공급사의 관계입니다. 문서는 로컬에 저장되며, AI 기능을 실행하면 필요한 내용이 외부 API로 전달됩니다.

<p align="center">
  <a href="sasoo/docs/assets/architecture-2026-09-25/system-architecture.ko.svg"><img src="sasoo/docs/assets/architecture-2026-09-25/system-architecture.ko.svg" alt="Electron 화면과 React, FastAPI, PDF 추출, 로컬 저장소, 외부 AI 공급사의 기술 구성도" width="1000" /></a>
</p>

[확대 보기](sasoo/docs/assets/architecture-2026-09-25/system-architecture.ko.svg) | [탐색용 HTML](sasoo/docs/assets/architecture-2026-09-25/system-architecture.ko.html)

### 분석 파이프라인

PDF 문맥을 준비한 뒤 다음 순서로 주요 분석을 수행합니다. 분야별 에이전트는 스크리닝 결과를 바탕으로 선택됩니다.

<p align="center">
  <a href="sasoo/docs/assets/architecture-2026-09-25/analysis-pipeline.ko.svg"><img src="sasoo/docs/assets/architecture-2026-09-25/analysis-pipeline.ko.svg" alt="스크리닝, 인용 분석, 시각 자료 분석, 레시피 추출, 심층 분석 순서를 보여주는 도식" width="1000" /></a>
</p>

[확대 보기](sasoo/docs/assets/architecture-2026-09-25/analysis-pipeline.ko.svg) | [탐색용 HTML](sasoo/docs/assets/architecture-2026-09-25/analysis-pipeline.ko.html)

이 도식은 주요 단계의 순서를 보여줍니다. 논문 내용과 실행 상태에 따라 단계가 건너뛰어지거나 중단될 수 있습니다. 종합 결과와 추가 시각화는 별도로 생성됩니다. 실제 실행 로직은 [analysis_execution.py](sasoo/backend/services/analysis_execution.py)에 있습니다.

### 로컬 실행

[패키지 요구사항](sasoo/package.json)은 Node.js **22.13 이상**입니다. [릴리스 CI](.github/workflows/release.yml)는 **Node.js 24, pnpm 10, Python 3.12, Java 21**을 사용합니다. 로컬 개발에서도 해당 버전을 기준으로 환경을 준비하세요. PDF 추출에 쓸 Java 런타임은 `JAVA_HOME` 또는 `SASOO_JAVA_HOME`으로 지정할 수 있습니다.

```bash
git clone https://github.com/dosigner/sasoo.git
cd sasoo/sasoo
pnpm install --frozen-lockfile
python3.12 -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install -r backend/requirements.txt -r backend/requirements-test.txt pyinstaller
pnpm dev
```

위 명령은 macOS/Linux 셸 기준입니다. Windows PowerShell에서는 가상환경 생성에 `py -3.12 -m venv backend/.venv`, 활성화에 `.\backend\.venv\Scripts\Activate.ps1`을 사용합니다.

<details>
<summary>테스트와 패키징 명령</summary>

`sasoo/`에서 실행합니다.

```bash
pnpm --dir=frontend test
pnpm --dir=frontend tsc --noEmit
pnpm --dir=frontend lint
pnpm test:unit
```

활성화한 Python 가상환경에서 백엔드 테스트를 실행합니다.

```bash
cd backend
python -m pytest services api models
cd ..
```

```bash
pnpm build:mac:release  # Run on macOS.
pnpm build:win:release  # Run on Windows.
```

일반 `pnpm build`는 백엔드를 새로 묶지 않습니다. 플랫폼별 release 명령은 백엔드 빌드와 산출물 검증을 포함합니다. 개발 화면 확인, 논문 원문 정확성 검토, 패키지 설치 검증은 각각 필요합니다. Windows 설치 파일이 생성됐다는 사실만으로 실기기 동작을 검증한 것은 아닙니다.

패키징 세부 사항은 [릴리스 체크리스트](sasoo/docs/03-release/release-checklist.md)와 [릴리스 워크플로](.github/workflows/release.yml)를 참고하세요.

</details>

## 라이선스

패키지 메타데이터에는 [MIT](sasoo/package.json)로 표기되어 있습니다. 저장소에는 별도의 프로젝트 `LICENSE` 파일이 아직 없습니다.
