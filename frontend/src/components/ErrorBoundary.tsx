import React from "react";

interface ErrorBoundaryProps {
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Root error boundary — a thrown error (failed map/WebGL init, rejected
 * lazy chunk, render crash) shows a recoverable panel instead of blanking
 * the whole app.
 */
export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    console.error("AegisUI: unhandled render error", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="ops-shell flex min-h-screen items-center justify-center p-6 text-white">
          <div className="ops-panel max-w-xl px-6 py-5 text-center">
            <div className="ops-kicker mb-2">System</div>
            <div className="ops-title mb-2">The view crashed — recoverable</div>
            <p className="mb-4 text-sm leading-6 text-slate-400">
              An unexpected error stopped this screen. Reloading re-initialises the
              operational view; no data was lost.
            </p>
            <p className="ops-mono mb-4 break-all text-xs text-slate-500">
              {this.state.error.message}
            </p>
            <button
              type="button"
              className="rounded-lg bg-[#38d9c4] px-4 py-2 text-sm font-semibold text-[#04121f] transition hover:bg-[#4ee6d2]"
              onClick={() => window.location.reload()}
            >
              Reload application
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
