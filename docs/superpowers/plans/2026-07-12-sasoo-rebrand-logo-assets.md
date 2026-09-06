# Sasoo 리브랜딩 로고 자산 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 스펙(`docs/superpowers/specs/2026-07-12-sasoo-rebrand-logo-design.md`)의 ㅅㅅ 모노그램 + G2 리퀴드 글라스 아이콘을 SVG 마스터 자산으로 구현하고, 앱(타이틀바·사이드바·파비콘·Electron 아이콘)과 README 히어로에 적용한다.

**Architecture:** 모든 자산은 `sasoo/frontend/src/assets/brand/`의 수기 SVG 6종을 원본으로 하고, PNG(Electron 아이콘·파비콘 폴백·README 히어로)는 sharp 기반 생성 스크립트로 파생한다. 손보정 PNG는 만들지 않는다.

**Tech Stack:** SVG, sharp(devDependency 신규), Vite 정적 자산 import, electron-builder(`buildResources: "build"` 기존 설정).

## Global Constraints

- 마크 기하(스펙 2장 값 그대로): 앞 ㅅ `M38 146 L96 28 L154 146`, 뒤 ㅅ `M122 146 L166 57 L210 146`, stroke-width 28, round cap/join, viewBox `0 0 240 170`. 뒤 ㅅ을 먼저 그린다(V1 크로스).
- 마크 단독 배색: 라이트 `#683DCC`/`#A1A1AA`, 다크 `#7C5AE8`/`#52525B`. 타일 위: white 100%/55%.
- 타일: `rx=30`(140 기준), 수직 그라데이션 `#8B67E9`→`#5B2FC7`.
- 크기별 파생(스펙 3.1): 64px+ 풀 글래스 / 32~63px 림만(글리프 stroke 34) / 16px 플랫(`rx=34`, 글리프 stroke 40).
- 앱 이름("Sasoo")·v2 컬러 토큰·`ExperimentPlanTab.tsx` 카피 변경 금지.
- 프론트 테스트 러너 없음 — 검증은 생성 스크립트의 자체 assert + `npm run build`/`lint` + 육안 확인으로 한다.
- 커밋 메시지는 리포 관례(한국어 + conventional prefix)를 따른다.

---

### Task 1: 브랜드 SVG 마스터 자산 6종 작성

**Files:**
- Create: `sasoo/frontend/src/assets/brand/logo-mark-light.svg`
- Create: `sasoo/frontend/src/assets/brand/logo-mark-dark.svg`
- Create: `sasoo/frontend/src/assets/brand/app-icon.svg`
- Create: `sasoo/frontend/src/assets/brand/app-icon-32.svg`
- Create: `sasoo/frontend/src/assets/brand/app-icon-flat.svg`
- Create: `sasoo/frontend/src/assets/brand/hero.svg`

**Interfaces:**
- Consumes: 없음 (스펙 수치만)
- Produces: 위 6개 파일 경로. Task 2의 스크립트가 `app-icon.svg`·`app-icon-flat.svg`·`hero.svg`를 읽고, Task 3이 `app-icon-flat.svg`·`app-icon-32.svg`를 import한다.

- [ ] **Step 1: 마크 단독 SVG 2종 작성**

`sasoo/frontend/src/assets/brand/logo-mark-light.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 170">
  <path d="M122 146 L166 57 L210 146" fill="none" stroke="#A1A1AA" stroke-width="28" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M38 146 L96 28 L154 146" fill="none" stroke="#683DCC" stroke-width="28" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
```

`sasoo/frontend/src/assets/brand/logo-mark-dark.svg`: 위와 동일하되 stroke만 `#52525B`(뒤 ㅅ), `#7C5AE8`(앞 ㅅ).

- [ ] **Step 2: 앱 아이콘 G2 풀 글래스 SVG 작성**

`sasoo/frontend/src/assets/brand/app-icon.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 140 140">
  <defs>
    <linearGradient id="base" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#8B67E9"/>
      <stop offset="1" stop-color="#5B2FC7"/>
    </linearGradient>
    <linearGradient id="rim" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.9"/>
      <stop offset="0.35" stop-color="#FFFFFF" stop-opacity="0.25"/>
      <stop offset="1" stop-color="#FFFFFF" stop-opacity="0.07"/>
    </linearGradient>
    <linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.30"/>
      <stop offset="1" stop-color="#FFFFFF" stop-opacity="0.02"/>
    </linearGradient>
    <clipPath id="tile"><rect width="140" height="140" rx="30"/></clipPath>
    <filter id="soft" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="7"/></filter>
  </defs>
  <rect width="140" height="140" rx="30" fill="url(#base)"/>
  <g clip-path="url(#tile)">
    <path d="M0 0 H140 V50 Q70 76 0 50 Z" fill="url(#sheen)"/>
    <ellipse cx="70" cy="152" rx="86" ry="26" fill="#1E0C46" fill-opacity="0.35" filter="url(#soft)"/>
  </g>
  <rect x="1.25" y="1.25" width="137.5" height="137.5" rx="28.75" fill="none" stroke="url(#rim)" stroke-width="2.5"/>
  <g transform="translate(12,31.5) scale(0.47)" opacity="0.3" fill="none" stroke="#2A1360" stroke-width="30" stroke-linecap="round" stroke-linejoin="round">
    <path d="M122 146 L166 57 L210 146"/>
    <path d="M38 146 L96 28 L154 146"/>
  </g>
  <g transform="translate(12,30) scale(0.47)" fill="none" stroke-width="30" stroke-linecap="round" stroke-linejoin="round">
    <path d="M122 146 L166 57 L210 146" stroke="#FFFFFF" stroke-opacity="0.55"/>
    <path d="M38 146 L96 28 L154 146" stroke="#FFFFFF"/>
  </g>
</svg>
```

- [ ] **Step 3: 32px 림-온리 파생 SVG 작성**

`sasoo/frontend/src/assets/brand/app-icon-32.svg` (시트·이너 섀도·깊이 그림자 제거, 림 stroke 4, 글리프 stroke 34):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 140 140">
  <defs>
    <linearGradient id="base32" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#8B67E9"/>
      <stop offset="1" stop-color="#5B2FC7"/>
    </linearGradient>
    <linearGradient id="rim32" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.9"/>
      <stop offset="1" stop-color="#FFFFFF" stop-opacity="0.06"/>
    </linearGradient>
  </defs>
  <rect width="140" height="140" rx="30" fill="url(#base32)"/>
  <rect x="2" y="2" width="136" height="136" rx="28" fill="none" stroke="url(#rim32)" stroke-width="4"/>
  <g transform="translate(12,30) scale(0.47)" fill="none" stroke-width="34" stroke-linecap="round" stroke-linejoin="round">
    <path d="M122 146 L166 57 L210 146" stroke="#FFFFFF" stroke-opacity="0.55"/>
    <path d="M38 146 L96 28 L154 146" stroke="#FFFFFF"/>
  </g>
</svg>
```

- [ ] **Step 4: 16px 플랫 파생 SVG 작성**

`sasoo/frontend/src/assets/brand/app-icon-flat.svg` (그라데이션+글리프만, `rx=34`, 글리프 stroke 40):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 140 140">
  <defs>
    <linearGradient id="baseFlat" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#8B67E9"/>
      <stop offset="1" stop-color="#5B2FC7"/>
    </linearGradient>
  </defs>
  <rect width="140" height="140" rx="34" fill="url(#baseFlat)"/>
  <g transform="translate(10,28) scale(0.49)" fill="none" stroke-width="40" stroke-linecap="round" stroke-linejoin="round">
    <path d="M122 146 L166 57 L210 146" stroke="#FFFFFF" stroke-opacity="0.6"/>
    <path d="M38 146 L96 28 L154 146" stroke="#FFFFFF"/>
  </g>
</svg>
```

- [ ] **Step 5: G3 프로스티드 히어로 SVG 작성**

`sasoo/frontend/src/assets/brand/hero.svg` (README·랜딩 전용, 스펙 5장):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 170">
  <defs>
    <clipPath id="heroTile"><rect x="45" y="30" width="110" height="110" rx="24"/></clipPath>
    <filter id="heroBlur" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="9"/></filter>
    <linearGradient id="heroRim" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.95"/>
      <stop offset="0.45" stop-color="#FFFFFF" stop-opacity="0.35"/>
      <stop offset="1" stop-color="#FFFFFF" stop-opacity="0.15"/>
    </linearGradient>
  </defs>
  <rect width="200" height="170" fill="#EFEBF8"/>
  <circle cx="38" cy="42" r="46" fill="#C9BAF5"/>
  <circle cx="172" cy="122" r="58" fill="#8B67E9" opacity="0.55"/>
  <circle cx="128" cy="18" r="32" fill="#A1A1AA" opacity="0.35"/>
  <g clip-path="url(#heroTile)">
    <g filter="url(#heroBlur)">
      <rect width="200" height="170" fill="#EFEBF8"/>
      <circle cx="38" cy="42" r="46" fill="#C9BAF5"/>
      <circle cx="172" cy="122" r="58" fill="#8B67E9" opacity="0.55"/>
      <circle cx="128" cy="18" r="32" fill="#A1A1AA" opacity="0.35"/>
    </g>
    <rect x="45" y="30" width="110" height="110" fill="#FFFFFF" fill-opacity="0.40"/>
  </g>
  <rect x="46" y="31" width="108" height="108" rx="23" fill="none" stroke="url(#heroRim)" stroke-width="2"/>
  <g transform="translate(54,53) scale(0.37)" fill="none" stroke-width="30" stroke-linecap="round" stroke-linejoin="round">
    <path d="M122 146 L166 57 L210 146" stroke="#8F89A3"/>
    <path d="M38 146 L96 28 L154 146" stroke="#683DCC"/>
  </g>
</svg>
```

- [ ] **Step 6: 6개 SVG가 XML로 유효한지 검증**

Run:
```bash
cd sasoo/frontend/src/assets/brand && for f in *.svg; do python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse('$f')" && echo "OK $f"; done
```
Expected: 6줄 모두 `OK <파일명>`, 에러 없음.

- [ ] **Step 7: 커밋**

```bash
git add sasoo/frontend/src/assets/brand/
git commit -m "feat(brand): ㅅㅅ 모노그램 SVG 마스터 자산 6종 추가 (스펙 2026-07-12)"
```

---

### Task 2: sharp 기반 PNG 파생 스크립트 + 파비콘 연결

**Files:**
- Create: `sasoo/frontend/scripts/generate-logo-assets.mjs`
- Modify: `sasoo/frontend/package.json` (devDependency `sharp`, script `gen:brand`)
- Modify: `sasoo/frontend/index.html` (favicon `<link>` 2줄, `<title>` 바로 아래)
- 생성 산출물: `sasoo/build/icon.png`(1024, 덮어씀), `sasoo/frontend/public/favicon.svg`, `public/favicon-32.png`, `public/favicon-16.png`, `sasoo/docs/assets/logo.png`(히어로 800px, 덮어씀)

**Interfaces:**
- Consumes: Task 1의 `app-icon.svg`, `app-icon-flat.svg`, `hero.svg`
- Produces: `npm run gen:brand` 커맨드. 산출물 경로는 위와 같고, 스크립트는 크기 불일치 시 non-zero exit.

- [ ] **Step 1: sharp 설치**

Run: `cd sasoo/frontend && npm install -D sharp`
Expected: `added N packages` 후 exit 0.

- [ ] **Step 2: 생성 스크립트 작성 (자체 검증 포함 — 이 스크립트가 이 태스크의 테스트다)**

`sasoo/frontend/scripts/generate-logo-assets.mjs`:

```js
import sharp from 'sharp';
import { copyFile, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const brand = (f) => join(root, 'src/assets/brand', f);

const jobs = [
  { src: brand('app-icon.svg'), out: join(root, '../build/icon.png'), width: 1024, height: 1024 },
  { src: brand('app-icon-flat.svg'), out: join(root, 'public/favicon-32.png'), width: 32, height: 32 },
  { src: brand('app-icon-flat.svg'), out: join(root, 'public/favicon-16.png'), width: 16, height: 16 },
  { src: brand('hero.svg'), out: join(root, '../docs/assets/logo.png'), width: 800, height: 680 },
];

for (const { src, out, width, height } of jobs) {
  await mkdir(dirname(out), { recursive: true });
  await sharp(src, { density: 300 }).resize(width, height).png().toFile(out);
  const meta = await sharp(out).metadata();
  if (meta.width !== width || meta.height !== height) {
    console.error(`FAIL ${out}: ${meta.width}x${meta.height}, expected ${width}x${height}`);
    process.exit(1);
  }
  console.log(`OK ${out} ${width}x${height}`);
}

await copyFile(brand('app-icon-flat.svg'), join(root, 'public/favicon.svg'));
console.log('OK public/favicon.svg (copy)');
```

- [ ] **Step 3: npm 스크립트 등록**

`sasoo/frontend/package.json` scripts에 추가:

```json
"gen:brand": "node scripts/generate-logo-assets.mjs"
```

- [ ] **Step 4: 실행 및 검증**

Run: `cd sasoo/frontend && npm run gen:brand`
Expected 출력 (5줄, exit 0):
```
OK .../build/icon.png 1024x1024
OK .../public/favicon-32.png 32x32
OK .../public/favicon-16.png 16x16
OK .../docs/assets/logo.png 800x680
OK public/favicon.svg (copy)
```

- [ ] **Step 5: index.html에 favicon 링크 추가**

`sasoo/frontend/index.html`의 `<title>Sasoo</title>` 바로 아래에 삽입:

```html
<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
<link rel="alternate icon" type="image/png" sizes="32x32" href="/favicon-32.png" />
```

- [ ] **Step 6: dev 서버에서 탭 아이콘 육안 확인**

Run: `cd sasoo/frontend && npm run dev` 후 브라우저에서 접속.
Expected: 브라우저 탭에 퍼플 타일 ㅅㅅ 파비콘 표시. 확인 후 서버 종료.

- [ ] **Step 7: 커밋**

```bash
git add sasoo/frontend/scripts/generate-logo-assets.mjs sasoo/frontend/package.json sasoo/frontend/package-lock.json sasoo/frontend/index.html sasoo/frontend/public/favicon.svg sasoo/frontend/public/favicon-32.png sasoo/frontend/public/favicon-16.png sasoo/build/icon.png sasoo/docs/assets/logo.png
git commit -m "feat(brand): sharp 파생 스크립트 + 파비콘/Electron 아이콘/README 히어로 생성"
```

참고: `README.md:3`·`README.en.md:3`은 `sasoo/docs/assets/logo.png`를 그대로 참조하므로 마크다운 수정 불필요 — 파일 내용만 히어로로 교체된다. electron-builder는 `buildResources: "build"`의 `icon.png`를 자동 인식하므로 `package.json` build 섹션 수정도 불필요. 스펙 7장의 "1024/512 PNG" 중 512는 소비처가 없어 생성하지 않는다(electron-builder가 1024에서 플랫폼별 크기를 자동 파생 — 의도된 스펙 축소).

---

### Task 3: 타이틀바·사이드바 로고 교체 및 구 자산 삭제

**Files:**
- Modify: `sasoo/frontend/src/components/Titlebar.tsx:2,46`
- Modify: `sasoo/frontend/src/components/layout/AppSidebar.tsx:4,51`
- Delete: `sasoo/frontend/src/assets/logo.png`

**Interfaces:**
- Consumes: Task 1의 `app-icon-flat.svg`(16px용), `app-icon-32.svg`(32px용)
- Produces: 없음 (말단 UI 변경)

- [ ] **Step 1: Titlebar 교체 (16px → 플랫 파생판, 스펙 3.1)**

`Titlebar.tsx` L2:
```tsx
// 변경 전
import logoImg from '@/assets/logo.png';
// 변경 후
import appIconFlat from '@/assets/brand/app-icon-flat.svg';
```
L46:
```tsx
// 변경 전
<img src={logoImg} alt="Sasoo" className="w-4 h-4" />
// 변경 후
<img src={appIconFlat} alt="Sasoo" className="w-4 h-4" />
```

- [ ] **Step 2: AppSidebar 교체 (32px → 림-온리 파생판)**

`AppSidebar.tsx` L4:
```tsx
// 변경 전
import logoImg from '@/assets/logo.png';
// 변경 후
import appIcon32 from '@/assets/brand/app-icon-32.svg';
```
L51 — `rounded-xl` 제거(타일 radius가 SVG에 내장돼 이중 클리핑 방지):
```tsx
// 변경 전
<img src={logoImg} alt="Sasoo" className="h-8 w-8 rounded-xl shrink-0" />
// 변경 후
<img src={appIcon32} alt="Sasoo" className="h-8 w-8 shrink-0" />
```

- [ ] **Step 3: 구 로고 삭제 및 잔여 참조 0건 확인**

Run:
```bash
git rm sasoo/frontend/src/assets/logo.png
grep -rn "assets/logo.png" sasoo/frontend/src/
```
Expected: `git rm` 성공, grep 결과 0건 (exit 1).

- [ ] **Step 4: 빌드로 import 무결성 검증**

Run: `cd sasoo/frontend && npm run build`
Expected: tsc·vite 모두 성공, exit 0.

- [ ] **Step 5: dev 서버에서 타이틀바·사이드바 육안 확인 (워드마크 락업 포함)**

Run: `cd sasoo/frontend && npm run dev`
Expected:
- 타이틀바 16px 플랫 아이콘, 사이드바 32px 림 아이콘이 선명하게 표시(블러·이중 라운딩 없음)
- 워드마크 락업(스펙 6장): 아이콘과 "Sasoo" 텍스트 간격 8px(`gap-2`), SemiBold(`font-semibold`), letter-spacing -0.01em(`tracking-[-0.01em]`). 기존 마크업이 이와 다르면 해당 컨테이너/텍스트 className을 위 세 클래스로 맞춘다 (텍스트 원문 `S.app.name`은 변경 금지).

확인 후 서버 종료.

- [ ] **Step 6: 커밋**

```bash
git add sasoo/frontend/src/components/Titlebar.tsx sasoo/frontend/src/components/layout/AppSidebar.tsx
git commit -m "feat(ui): 타이틀바·사이드바 로고를 신규 브랜드 아이콘으로 교체, 구 logo.png 제거"
```

---

### Task 4: 최종 검증

**Files:** 없음 (검증 전용)

**Interfaces:**
- Consumes: Task 1~3 전체
- Produces: 스펙 8장 성공 기준 충족 확인

- [ ] **Step 1: 클린 재생성으로 재현성 확인**

Run: `cd sasoo/frontend && npm run gen:brand`
Expected: 5줄 OK, exit 0 (스펙 8장 "모든 자산이 마스터에서 규칙으로 파생" 충족).

- [ ] **Step 2: lint + build 최종 통과**

Run: `cd sasoo/frontend && npm run lint && npm run build`
Expected: 둘 다 exit 0.

- [ ] **Step 3: 스펙 8장 성공 기준 대조 (육안)**

- 브라우저 탭(16px)에서 ㅅㅅ 판독 가능
- 라이트/다크 마크 SVG 2종 존재 (`logo-mark-light.svg`/`logo-mark-dark.svg`)
- `sasoo/build/icon.png`이 1024 G2 풀 글래스

Expected: 3항목 모두 충족. 미충족 항목은 해당 Task로 돌아가 수정.

- [ ] **Step 4: 미검증 항목 기록**

macOS Dock 실기기 확인(스펙 8장 4번째 기준)은 Electron 패키징이 필요하므로 이 계획 범위에서 **미검증**으로 남기고, 완료 보고에 명시한다.
