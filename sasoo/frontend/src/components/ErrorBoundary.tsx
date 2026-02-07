import { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';
import { Link } from 'react-router-dom';

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

/**
 * Error Boundary Component
 *
 * Catches rendering errors, lifecycle errors, and constructor errors
 * in child components and displays a user-friendly fallback UI.
 */
class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    // Update state so the next render will show the fallback UI
    return {
      hasError: true,
      error,
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Log error details to console with full stack trace
    console.error('ErrorBoundary caught an error:', error);
    console.error('Component stack trace:', errorInfo.componentStack);

    this.setState({
      error,
      errorInfo,
    });
  }

  handleReset = (): void => {
    // Reset error state to retry rendering
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  render(): ReactNode {
    const { hasError, error } = this.state;
    const { children, fallback } = this.props;

    if (hasError) {
      // If custom fallback is provided, use it
      if (fallback) {
        return fallback;
      }

      // Default fallback UI
      return (
        <div className="flex items-center justify-center h-full min-h-screen bg-surface-50 dark:bg-surface-900 p-4">
          <div className="bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700 rounded-xl p-8 max-w-md w-full shadow-xl">
            {/* Error Icon */}
            <div className="flex justify-center mb-6">
              <div className="w-16 h-16 rounded-full bg-red-500/10 border border-red-500/20 flex items-center justify-center">
                <AlertTriangle className="w-8 h-8 text-red-600 dark:text-red-400" />
              </div>
            </div>

            {/* Error Title */}
            <h1 className="text-xl font-bold text-surface-900 dark:text-surface-100 text-center mb-3">
              오류가 발생했습니다
            </h1>

            {/* Error Message */}
            <p className="text-sm text-surface-600 dark:text-surface-400 text-center mb-6 break-words">
              {error?.message || '알 수 없는 오류가 발생했습니다.'}
            </p>

            {/* Action Buttons */}
            <div className="flex flex-col gap-3">
              {/* Retry Button */}
              <button
                onClick={this.handleReset}
                className="w-full px-4 py-2.5 bg-primary-500 hover:bg-primary-600 active:bg-primary-700 text-white rounded-lg font-medium transition-colors duration-200 shadow-sm hover:shadow-md"
              >
                다시 시도
              </button>

              {/* Home Button */}
              <Link
                to="/"
                className="w-full px-4 py-2.5 bg-surface-100 hover:bg-surface-200 dark:bg-surface-700 dark:hover:bg-surface-600 text-surface-700 dark:text-surface-200 rounded-lg font-medium transition-colors duration-200 text-center border border-surface-300 dark:border-surface-600"
              >
                홈으로 돌아가기
              </Link>
            </div>

            {/* Developer Info (only in development) */}
            {process.env.NODE_ENV === 'development' && error && (
              <details className="mt-6 p-4 bg-surface-50 dark:bg-surface-900 border border-surface-200 dark:border-surface-700 rounded-lg">
                <summary className="text-xs font-medium text-surface-600 dark:text-surface-300 cursor-pointer hover:text-surface-700 dark:hover:text-surface-200">
                  개발자 정보 (Development Only)
                </summary>
                <pre className="mt-3 text-2xs text-red-600 dark:text-red-400 overflow-auto max-h-40">
                  {error.stack}
                </pre>
              </details>
            )}
          </div>
        </div>
      );
    }

    return children;
  }
}

export default ErrorBoundary;
