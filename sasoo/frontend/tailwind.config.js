/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Semantic tokens — single source in :root/.light (see src/index.css)
        bg: 'rgb(var(--bg) / <alpha-value>)',
        border: 'rgb(var(--border) / <alpha-value>)',
        fg: {
          DEFAULT: 'rgb(var(--fg) / <alpha-value>)',
          secondary: 'rgb(var(--fg-secondary) / <alpha-value>)',
          muted: 'rgb(var(--fg-muted) / <alpha-value>)',
        },
        accent: {
          DEFAULT: 'rgb(var(--accent) / <alpha-value>)',
          hover: 'rgb(var(--accent-hover) / <alpha-value>)',
          fg: 'rgb(var(--accent-fg) / <alpha-value>)',
        },
        danger: 'rgb(var(--danger) / <alpha-value>)',
        warning: 'rgb(var(--warning) / <alpha-value>)',
        success: 'rgb(var(--success) / <alpha-value>)',
        surface: {
          DEFAULT: 'rgb(var(--surface) / <alpha-value>)',
          hover: 'rgb(var(--surface-hover) / <alpha-value>)',
        },
      },
      fontFamily: {
        sans: [
          '"Pretendard Variable"',
          '-apple-system',
          'BlinkMacSystemFont',
          '"Apple SD Gothic Neo"',
          '"Noto Sans KR"',
          '"Segoe UI"',
          '"Helvetica Neue"',
          'Arial',
          'sans-serif',
        ],
        mono: [
          '"JetBrains Mono"',
          '"Fira Code"',
          'Menlo',
          'Monaco',
          'Consolas',
          'monospace',
        ],
      },
      fontSize: {
        // ref docs/04-design/design-tokens.md §3
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],      // 11px/16px
        'xs':  ['0.75rem',   { lineHeight: '1rem' }],      // 12px/16px
        'sm':  ['0.8125rem', { lineHeight: '1.25rem' }],   // 13px/20px
        'base':['0.9375rem', { lineHeight: '1.375rem' }],  // 15px/22px
        'lg':  ['1.0625rem', { lineHeight: '1.625rem' }],  // 17px/26px
      },
      letterSpacing: {
        'apple-body': '-0.01em',
      },
      spacing: {
        '18': '4.5rem',
        '88': '22rem',
        '112': '28rem',
        '128': '32rem',
      },
      animation: {
        // ≤150ms per docs/04-design/design-tokens.md §5 (pulse-subtle is a decorative loop, exempt)
        'fade-in': 'fadeIn 0.15s ease-out',
        'fade-out': 'fadeOut 0.15s ease-out',
        'slide-in-right': 'slideInRight 0.15s ease-out',
        'slide-in-left': 'slideInLeft 0.15s ease-out',
        'slide-up': 'slideUp 0.15s ease-out',
        'pulse-subtle': 'pulseSubtle 2s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        fadeOut: {
          '0%': { opacity: '1' },
          '100%': { opacity: '0' },
        },
        slideInRight: {
          '0%': { transform: 'translateX(1rem)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        slideInLeft: {
          '0%': { transform: 'translateX(-1rem)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        slideUp: {
          '0%': { transform: 'translateY(0.5rem)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        pulseSubtle: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.7' },
        },
      },
      borderRadius: {
        '4xl': '2rem',
        control: 'var(--radius-control)',
        surface: 'var(--radius-surface)',
      },
      backdropBlur: {
        xs: '2px',
      },
    },
  },
  plugins: [],
};
