import { useState } from "react";

// Быстрый путь для строк с бейджем "догадка"/"не найдено": вписать
// правильное значение прямо в таблице, без открытия модалки поиска по
// каталогу (см. MatchEditModal/LaborEditModal — они остаются рядом для
// тех, кто хочет искать, а не печатать). Всегда видим, без своего
// скрытого/развёрнутого состояния — как только сохранение проходит,
// строка перестаёт быть "догадкой" и родитель сам перестаёт это рендерить.
export default function InlineCorrection({ fields, onSave, saving }) {
  const [values, setValues] = useState(() => Object.fromEntries(fields.map((f) => [f.key, ""])));

  const canSave = fields.every((f) => !f.required || String(values[f.key] ?? "").trim() !== "");

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canSave || saving) return;
    await onSave(
      Object.fromEntries(
        fields.map((f) => [f.key, f.type === "number" ? Number(values[f.key]) : values[f.key].trim()])
      )
    );
  };

  return (
    <form
      onSubmit={handleSubmit}
      style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}
      onClick={(e) => e.stopPropagation()}
    >
      {fields.map((f) => (
        <input
          key={f.key}
          type={f.type || "text"}
          placeholder={f.placeholder}
          value={values[f.key]}
          disabled={saving}
          onChange={(e) => setValues((prev) => ({ ...prev, [f.key]: e.target.value }))}
          style={{ fontSize: 12, padding: "3px 6px", width: f.type === "number" ? 70 : 200 }}
        />
      ))}
      <button type="submit" className="btn btn-secondary btn-sm" disabled={!canSave || saving}>
        {saving ? "Сохранение…" : "Сохранить"}
      </button>
    </form>
  );
}
