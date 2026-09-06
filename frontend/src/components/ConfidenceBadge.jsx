const LEVEL_LABELS = {
  exact: "точное совпадение",
  cross_ref: "кросс-номер",
  llm_guess: "догадка LLM",
};

// Свёрнуто до того, что реально нужно оператору для решения "верить или
// доделать самому": "проверено" / "догадка" / "не найдено". Подробности
// (exact vs cross_ref, точный процент уверенности) — только в тултипе, для
// тех, кому это важно (см. ConfidenceBadge.test.jsx и is_verified в
// backend/app/services/confidence_display.py, откуда приходит isVerified).
export default function ConfidenceBadge({ isVerified, matchCategory, level, score }) {
  const bucket = isVerified
    ? "verified"
    : matchCategory === "no_match" || matchCategory === "llm_error"
    ? "no_match"
    : "guess";

  const label = bucket === "verified" ? "проверено" : bucket === "no_match" ? "не найдено" : "догадка";

  const detail = LEVEL_LABELS[level] || level;
  const title =
    typeof score === "number" && level === "llm_guess"
      ? `${detail} · ${Math.round(score * 100)}%`
      : detail;

  return (
    <span className={`badge badge-${bucket}`} title={title}>
      {label}
    </span>
  );
}
