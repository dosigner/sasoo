// ESLint flat config for the Vite + React + TS frontend.
// Toolchain: eslint v10 + typescript-eslint v8 + react-hooks v7 + react-refresh v0.5
//
// eslint v9부터 flat config만 지원한다(.eslintrc.cjs는 더 읽지 않는다). 이 파일은
// 옛 .eslintrc.cjs의 규칙을 의미 그대로 옮긴 것이고, 각 조정의 근거 주석도 함께 옮겼다.
// 규칙을 새로 추가하거나 강도를 바꾸지 않았다 — 툴체인만 올린 변경이다.
//
// 철학: recommended 프리셋에서 출발해 에러로 유지하고, 기존 코드를 다시 쓰지 않고
// 초록으로 만드는 데 필요한 최소한의 조정만 한다. 각 조정에는 근거를 적는다.
import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';

export default tseslint.config(
  // 빌드 산출물, 의존성, node 쪽 스크립트, 설정 파일은 검사 범위 밖.
  // flat config에서는 ignorePatterns 대신 ignores만 담은 항목을 쓴다.
  {
    ignores: [
      'dist',
      'node_modules',
      'scripts',
      '**/*.config.js',
      '**/*.config.ts',
      '**/*.config.d.ts',
      'vite-env.d.ts',
    ],
  },

  js.configs.recommended,
  ...tseslint.configs.recommended,
  reactHooks.configs.flat['recommended-latest'],

  {
    // 옛 스크립트가 `eslint . --ext ts,tsx`였다. --ext는 eslint 9에서 제거돼
    // 대상 지정을 여기로 옮긴다(package.json의 lint 스크립트도 함께 고쳤다).
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.es2020,
        ...globals.node,
      },
    },
    plugins: {
      'react-refresh': reactRefresh,
    },
    rules: {
      // 의도적으로 안 쓰는 바인딩에 `_` 접두사를 붙이는 기존 관례를 존중한다
      // (예: `{ node: _node, ... }`, `variant: _variant`). 규칙을 느슨하게 하는 게
      // 아니라 코드가 이미 쓰인 방식에 맞추는 것이다.
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
          ignoreRestSiblings: true,
        },
      ],
      // lib/api.ts의 스트림 리더처럼 의도한 무한 루프를 허용한다.
      // if/삼항 등의 상수 조건은 여전히 잡는다.
      'no-constant-condition': ['error', { checkLoops: false }],
      // 권고 성격의 규칙. 하드 에러로 강제하면 기존 훅들의 의존성 배열을 바꿔야 하고
      // 그건 런타임 동작을 바꿀 수 있다. 정확성 규칙인 rules-of-hooks는 에러로 유지.
      'react-hooks/exhaustive-deps': 'off',
      // Vite fast-refresh DX 힌트일 뿐(정확성 영향 없음). 이 코드베이스는 여러 파일에서
      // 헬퍼·상수를 컴포넌트와 같이 두는데, 에러로 강제하면 그 모듈들을 재구성해야 한다.
      'react-refresh/only-export-components': 'off',

      // --- eslint-plugin-react-hooks v7에서 새로 들어온 규칙들 (아래 전부 off) ---
      //
      // v4의 recommended는 rules-of-hooks와 exhaustive-deps 둘뿐이었다. v7은 React
      // Compiler 계열까지 17개로 늘었다. 이번 변경은 툴체인 버전만 올리는 것이라
      // 규칙 강도는 그대로 둔다. 끄지 않으면 조용히 규칙 15개가 추가되는 셈이다.
      //
      // 실측(2026-08-19, 코드 무수정 상태): 22건이 걸린다.
      //   15건 set-state-in-effect  effect 안에서 setState를 부르는 자리
      //    6건 refs                 렌더 중 ref 접근
      //    1건 preserve-manual-memoization
      //
      // 전부 진짜 지적이지만 고치면 **렌더 동작이 바뀐다.** 화면 확인 없이 손댈 자리가
      // 아니라 별도 과제로 남긴다. 켤 때는 한 규칙씩 켜고 실제로 앱을 띄워 확인해라.
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/refs': 'off',
      'react-hooks/preserve-manual-memoization': 'off',
      'react-hooks/static-components': 'off',
      'react-hooks/use-memo': 'off',
      'react-hooks/void-use-memo': 'off',
      'react-hooks/incompatible-library': 'off',
      'react-hooks/immutability': 'off',
      'react-hooks/globals': 'off',
      'react-hooks/error-boundaries': 'off',
      'react-hooks/purity': 'off',
      'react-hooks/set-state-in-render': 'off',
      'react-hooks/unsupported-syntax': 'off',
      'react-hooks/config': 'off',
      'react-hooks/gating': 'off',
    },
  },

  {
    // PdfViewer는 pdfjs-dist를 감싼다. 그 라이브러리의 런타임 객체가 약하게 타입돼 있어
    // 여기 any는 상호운용을 위한 것이다. no-explicit-any는 나머지 전역에서 에러로 유지.
    files: ['src/components/PdfViewer.tsx'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
);
