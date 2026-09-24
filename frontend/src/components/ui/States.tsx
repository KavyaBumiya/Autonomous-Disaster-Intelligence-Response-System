import React from "react";

export const LoadingState: React.FC<{ label?: string }> = ({ label = "Loading…" }) => (
  <div className="ops-loading" role="status" aria-live="polite">
    <div className="skeleton h-4 w-32" />
    <div className="skeleton h-3 w-40" />
    <span className="sr-only">{label}</span>
  </div>
);

export const EmptyState: React.FC<{
  title?: string;
  message?: string;
  action?: React.ReactNode;
}> = ({
  title = "Nothing here yet",
  message = "No records to display.",
  action,
}) => (
  <div className="ops-empty">
    <div className="ops-title-sm">{title}</div>
    <p className="max-w-sm text-xs leading-5">{message}</p>
    {action}
  </div>
);

export const ErrorState: React.FC<{ message?: string; onRetry?: () => void }> = ({
  message = "Something went wrong.",
  onRetry,
}) => (
  <div className="ops-error">
    <div className="ops-title-sm" style={{ color: "var(--red)" }}>
      Unable to load
    </div>
    <p className="max-w-sm text-xs leading-5">{message}</p>
    {onRetry && (
      <button type="button" className="ops-button ops-button-sm" onClick={onRetry}>
        Retry
      </button>
    )}
  </div>
);
