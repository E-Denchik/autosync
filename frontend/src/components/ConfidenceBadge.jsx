const LABELS = {
  exact: "точное совпадение",
  cross_ref: "кросс-номер",
  llm_guess: "догадка LLM",
};

// Визуально различает статусы сопоставления: LLM-догадка никогда не должна
// выглядеть так же надёжно, как точное совпадение (см. ARCHITECTURE.md).
export default function ConfidenceBadge({ level, score }) {
  const label = LABELS[level] || level;
  return (
    <span className={`badge badge-${level}`}>
      {label}
      {level === "llm_guess" && typeof score === "number" ? ` · ${Math.round(score * 100)}%` : ""}
    </span>
  );
}
