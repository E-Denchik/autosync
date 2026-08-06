import { InboxIcon } from "./icons.jsx";

export default function EmptyState({ icon: Icon = InboxIcon, title, hint, action }) {
  return (
    <div className="empty-state">
      <Icon className="empty-icon" />
      <div className="empty-title">{title}</div>
      {hint && <div className="empty-hint">{hint}</div>}
      {action && <div style={{ marginTop: 16 }}>{action}</div>}
    </div>
  );
}
