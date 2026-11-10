# GPT Image 2.5 Flare와 도해 글자 배치 검증

2026-09-27. Sasoo 소스의 OpenAI 이미지 모델을 `gpt-image-2.5-flare`로 변경했다. 기존 개발 설정은 `ai_provider=openai`, `image_provider=openai`, `image_quality=medium`이었다. 저장된 설정은 수정하지 않았다.

## 변경과 근거

- 모델 상수와 설정 화면 안내를 Flare로 변경했다.
- 도해 설계와 실제 이미지 요청 양쪽에 일반 폭의 Arial/Helvetica 계열 글꼴, 자연스러운 글자 비율과 자간, 라벨 공간 우선 배치, 긴 라벨 줄바꿈을 지시했다. 글자를 가로로 압축하거나 작게 줄여 공간에 맞추지 않도록 했다. 1536x1024에서 28px 이상은 생성 지시이며 실제 폰트 크기를 강제하는 코드가 아니다.
- `PaperBananaViewer`는 기존에 `w-full h-auto object-contain`으로 종횡비를 유지한다. 이번에는 이미지 표시 CSS를 변경하지 않았다.
- GPT Image 2의 고정 장당 가격을 Flare에 재사용하지 않았다. 직접 Images API 응답의 입력 텍스트/이미지 토큰과 출력 토큰으로 계산한다. 사용량이 없거나 잘못되면 이미지는 보존하고 비용은 미확인으로 남긴다.

공식 근거: [Flare 모델과 요율](https://developers.openai.com/api/docs/models/gpt-image-2.5-flare), [이미지 생성과 사용량](https://developers.openai.com/api/docs/guides/image-generation), [이미지 프롬프트 지침](https://developers.openai.com/api/docs/guides/image-prompting). 직접 Images API에는 캐시 할인 요율이 적용되지 않는다.

## 검증

- `backend/.venv/bin/python -m pytest services/test_figure_gen.py services/test_pricing_images.py services/test_pricing.py services/test_model_registry.py services/test_model_pins.py -q`: 121 passed, 49 subtests passed. 기존 SWIG deprecation warning 5건.
- `frontend/pnpm build`: TypeScript 검사와 Vite 빌드 성공.
- `pnpm exec eslint src/pages/Settings.tsx src/lib/strings.ts`: 성공.
- `git diff --check`: 성공.
- 실제 Chrome에서 빌드된 설정 화면을 1440x1000과 1024x768로 확인했다. API는 격리된 설정 데이터로 대체했다. `medium → high → medium` 선택, Flare 안내, 고정 가격 제거를 확인했다. 비용 API를 503으로 대체해도 설정 화면과 선택이 동작했다. 최종 검증의 JavaScript 예외는 0건이며 1024px 화면의 가로 넘침은 없었다. 실제 설정 저장 및 패키지 앱 설치는 수행하지 않았다.

Flare 직접 API 호출은 앱의 `OpenAIImageProvider.generate()`를 사용했다. 원고나 개인 논문 대신 동일한 합성 도해 설명을 사용하고 품질만 바꿨다. 실제 플래너 모델 호출은 생략했으며 플래너 지시 전달은 위 회귀 테스트에서 확인했다.

| 품질 | 크기 | 입력 토큰 | 출력 토큰 | 계산 비용 USD | 응답 시간 |
|---|---|---:|---:|---:|---:|
| medium | 1536x1024 | 265 | 343 | 0.011615 | 13.192초 |
| high | 1536x1024 | 265 | 1372 | 0.042485 | 32.798초 |

두 샘플을 직접 열어 요청한 6개 라벨의 철자와 줄바꿈을 확인했다. `Shack-Hartmann sensor`, `Deformable mirror`, `Wavelength 532 nm`가 줄바꿈되어 읽히며 눈에 띄는 가로 압축은 관측되지 않았다. 전후 비교 실험은 아니며 품질별 1회 결과다. 모든 논문과 복잡한 도해의 글꼴 재현성을 보장하지 않는다. 이 샘플은 글자 배치 확인용으로, 광학 장치의 물리적 정확성을 검증한 그림은 아니다.

증거:

- [medium 이미지](assets/image-flare-2026-09-27/typography-medium.png), [요청과 사용량](assets/image-flare-2026-09-27/render-medium-check.json)
- [high 이미지](assets/image-flare-2026-09-27/typography-sample.png), [요청과 사용량](assets/image-flare-2026-09-27/render-check.json)
- [1440px 설정 화면](assets/image-flare-2026-09-27/settings-1440.png), [1024px 설정 화면](assets/image-flare-2026-09-27/settings-1024.png), [GUI 결과](assets/image-flare-2026-09-27/ui-check.json)

## GPT-6 Luna 활용 제안

이번 변경은 이미지 모델에 한정했다. GPT-6 Luna는 도해 기술서 작성이나 생성 이미지의 라벨/단위 누락 검토에 먼저 비교 적용하는 편이 좋다. 이미지를 입력으로 읽고 텍스트를 출력하는 기능은 [공식 모델 문서](https://developers.openai.com/api/docs/models/gpt-6-luna)에 있다. 기존 플래너를 후보 모델로 바꿔 같은 자료에서 비교한 뒤 채택할 수 있으며, 자동 재생성 루프를 먼저 추가할 필요는 없다.

전체 논문 분석 기본값을 바꾸는 것은 별도 판단이다. [9월 23일 저장된 비교 기록](2026-09-23-gpt-6-luna-comparison.md)은 GPT-6 Luna의 비용/시간 개선과 정확성 기준 미통과를 함께 기록한다. 이번 작업에서는 그 비교를 재실행하지 않았다.

학습 메모: 도해의 글자 폭은 생성된 이미지의 일부이므로 CSS의 자간 변경으로 고칠 수 없다. 레이아웃에서 먼저 글자 공간을 확보하고, 같은 긴 라벨을 실제 생성해서 확인해야 한다. 프롬프트는 배치 지시이며 확정적인 폰트 엔진은 아니라는 점이 한계다. 정확한 폰트가 필수인 출판 작업에는 별도 텍스트 합성이 필요하다.
