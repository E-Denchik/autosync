import { AlertCircleIcon } from "./icons.jsx";

export default function ConfirmDialog({
  title,
  message,
  confirmLabel = "Подтвердить",
  cancelLabel = "Отмена",
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}) {
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(10, 11, 16, 0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 200,
      }}
      onClick={onCancel}
    >
      <div className="panel" style={{ width: 380 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", gap: 10, alignItems: "flex-start", marginBottom: 14 }}>
          <AlertCircleIcon
            style={{ width: 20, height: 20, color: danger ? "var(--danger)" : "var(--accent)", flexShrink: 0 }}
          />
          <div>
            <div style={{ fontWeight: 650, fontSize: 14.5, marginBottom: 4 }}>{title}</div>
            <div className="text-muted" style={{ fontSize: 13, lineHeight: 1.5 }}>
              {message}
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button className="btn btn-secondary" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </button>
          <button className={danger ? "btn btn-reject" : "btn btn-primary"} onClick={onConfirm} disabled={busy}>
            {busy ? "…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
