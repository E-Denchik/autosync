const STATUS_CONFIG = {
  comfortable: { bucket: "verified", label: "хорошо подойдёт" },
  tight: { bucket: "guess", label: "впритык" },
  too_big: { bucket: "no_match", label: "скорее всего не поместится" },
};

// Совместимость конкретной модели с этим компьютером по памяти (см.
// backend/app/services/performance_settings.py::fit_for_model) — те же
// три бейджа, что уже используются для уверенности сопоставления
// (ConfidenceBadge.jsx), чтобы не вводить отдельный визуальный язык.
export default function ModelFitBadge({ fit, capabilityNote }) {
  const status = fit?.status;
  const config = STATUS_CONFIG[status];
  const title = [capabilityNote, fit?.note].filter(Boolean).join(" ") || undefined;

  if (!config) {
    return (
      <span className="status-pill" title={title || "Размер модели не определён"}>
        размер неизвестен
      </span>
    );
  }

  return (
    <span className={`badge badge-${config.bucket}`} title={title}>
      {config.label}
    </span>
  );
}
