import React, { useEffect } from "react";

export const Modal: React.FC<{
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}> = ({ open, onClose, title, children, footer }) => {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <div className="ops-scrim" onClick={onClose} aria-hidden="true" />
      <div className="ops-modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="ops-panel-header">
          <div>
            <div className="ops-kicker">Dialog</div>
            <div className="ops-title">{title}</div>
          </div>
          <button type="button" className="ops-button ops-button-ghost ops-button-sm" onClick={onClose} aria-label="Close dialog">
            ✕
          </button>
        </div>
        <div className="ops-panel-body">{children}</div>
        {footer && (
          <div className="ops-panel-header" style={{ borderTop: "1px solid var(--line)", borderBottom: "none", justifyContent: "flex-end", gap: 10 }}>
            {footer}
          </div>
        )}
      </div>
    </>
  );
};
