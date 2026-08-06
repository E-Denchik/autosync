const LABELS = {
  pending: "ожидает",
  approved: "принято",
  rejected: "отклонено",
  uploaded: "загружено",
  parsing: "парсинг",
  matching: "сопоставление",
  needs_review: "нужна проверка",
  reviewed: "готово",
  failed: "ошибка",
};

export default function StatusPill({ status }) {
  return <span className={`status-pill status-${status}`}>{LABELS[status] || status}</span>;
}
