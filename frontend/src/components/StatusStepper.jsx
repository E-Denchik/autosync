const STEPS = [
  { key: "uploaded", label: "Загружено" },
  { key: "parsing", label: "Парсинг" },
  { key: "matching", label: "Сопоставление" },
  { key: "needs_review", label: "Проверка" },
  { key: "reviewed", label: "Готово" },
];

export default function StatusStepper({ status }) {
  const activeIndex = STEPS.findIndex((s) => s.key === status);

  return (
    <div className="stepper">
      {STEPS.map((step, i) => {
        const done = activeIndex > i || status === "reviewed";
        const active = i === activeIndex && status !== "reviewed";
        return (
          <div key={step.key} style={{ display: "flex", alignItems: "center" }}>
            <div className={`step ${done ? "done" : ""} ${active ? "active" : ""}`}>
              <span className="step-dot">{done ? "✓" : i + 1}</span>
              <span>{step.label}</span>
            </div>
            {i < STEPS.length - 1 && <div className="step-connector" />}
          </div>
        );
      })}
    </div>
  );
}
