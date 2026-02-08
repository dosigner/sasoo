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
        // Apple-style primary blue palette
        primary: {
          50:  '#e5f1ff',
          100: '#cce3ff',
          200: '#99c7ff',
          300: '#66abff',
          400: '#0a84ff',  // Apple dark mode blue
          500: '#007aff',  // Apple system blue
          600: '#0071e3',  // Apple website CTA blue
          700: '#005bb5',
          800: '#004a93',
          900: '#003a75',
          950: '#002952',
        },
        // Apple neutral gray surface palette
        surface: {
          50:  '#f5f5f7',  // Apple light secondary
          100: '#e8e8ed',
          200: '#d1d1d6',
          300: '#aeaeb2',
          400: '#8e8e93',  // Apple system gray
          500: '#636366',
          600: '#48484a',
          700: '#3a3a3c',
          800: '#1c1c1e',  // Apple dark secondary
          900: '#000000',  // Apple pure dark
          950: '#000000',
        },
      },
      fontFamily: {
        sans: [
          '"SF Pro Display"',
          '"SF Pro Text"',
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
        '2xs': ['0.625rem', { lineHeight: '0.875rem' }],
      },
      letterSpacing: {
        'apple-tight': '-0.025em',
        'apple-body': '-0.01em',
      },
      spacing: {
        '18': '4.5rem',
        '88': '22rem',
        '112': '28rem',
        '128': '32rem',
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'fade-out': 'fadeOut 0.3s ease-out',
        'slide-in-right': 'slideInRight 0.3s ease-out',
        'slide-in-left': 'slideInLeft 0.3s ease-out',
        'slide-up': 'slideUp 0.3s ease-out',
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
      },
      backdropBlur: {
        xs: '2px',
      },
      typography: {
        DEFAULT: {
          css: {
            maxWidth: 'none',
            color: '#e8e8ed',
            a: {
              color: '#0a84ff',
              '&:hover': {
                color: '#66abff',
              },
            },
            strong: {
              color: '#f5f5f7',
            },
            code: {
              color: '#e8e8ed',
              backgroundColor: '#1c1c1e',
              borderRadius: '0.25rem',
              padding: '0.125rem 0.25rem',
            },
            'code::before': {
              content: '""',
            },
            'code::after': {
              content: '""',
            },
            h1: { color: '#f5f5f7' },
            h2: { color: '#f5f5f7' },
            h3: { color: '#f5f5f7' },
            h4: { color: '#f5f5f7' },
            blockquote: {
              color: '#8e8e93',
              borderLeftColor: '#0071e3',
            },
            hr: {
              borderColor: '#3a3a3c',
            },
            'thead th': {
              color: '#f5f5f7',
            },
            'tbody td': {
              borderBottomColor: '#3a3a3c',
            },
          },
        },
      },
    },
  },
  plugins: [],
};
