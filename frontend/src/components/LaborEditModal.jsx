import { useMemo, useState } from "react";
import { SearchIcon } from "./icons.jsx";

export default function LaborEditModal({ line, catalog, onClose, onSave, saving }) {
  const [query, setQuery] = useState("");
  const [operationName, setOperationName] = useState(line.matched_operation_name || "");
  const [normHours, setNormHours] = useState(line.norm_hours ?? "");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return catalog;
    return catalog.filter(
      (c) =>
        c.operation_name?.toLowerCase().includes(q) ||
        c.vehicle_make?.toLowerCase().includes(q) ||
        c.vehicle_model?.toLowerCase().includes(q)
    );
  }, [query, catalog]);

  const pickCandidate = (c) => {
    setOperationName(c.operation_name);
    setNormHours(c.norm_hours);
  };

  const handleSave = () => {
    if (!operationName.trim() || normHours === "") return;
    onSave({ matched_operation_name: operationName.trim(), norm_hours: Number(normHours) });
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(10, 11, 16, 0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        className="panel"
        style={{ width: 480, maxHeight: "80vh", display: "flex", flexDirection: "column" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="section-title">Изменить работу</div>
        <p className="text-muted" style={{ fontSize: 12.5, marginTop: -6, marginBottom: 14 }}>
          Заказ-наряд: <strong>{line.description}</strong>
        </p>

        <div className="field" style={{ position: "relative" }}>
          <input
            autoFocus
            placeholder="Поиск по справочнику нормо-часов (операция, марка, модель)…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ paddingLeft: 32 }}
          />
          <SearchIcon
            style={{ position: "absolute", left: 9, top: 32, width: 15, height: 15, color: "var(--text-faint)" }}
          />
        </div>

        <div
          style={{
            overflowY: "auto",
            maxHeight: 220,
            border: "1px solid var(--border)",
            borderRadius: 8,
            marginBottom: 14,
          }}
        >
          {filtered.length === 0 ? (
            <div style={{ padding: 16, fontSize: 13, color: "var(--text-muted)" }}>
              Ничего не найдено в справочнике — впишите операцию и часы вручную ниже.
            </div>
          ) : (
            filtered.map((c) => (
              <div
                key={c.id}
                onClick={() => pickCandidate(c)}
                style={{
                  padding: "10px 12px",
                  fontSize: 13,
                  cursor: "pointer",
                  borderBottom: "1px solid var(--border)",
                  background: operationName === c.operation_name ? "var(--accent-soft)" : "transparent",
                }}
              >
                <div style={{ fontWeight: 600 }}>{c.operation_name}</div>
                <div className="text-muted" style={{ fontSize: 12 }}>
                  {c.vehicle_make} {c.vehicle_model || ""} · {c.norm_hours} ч
                </div>
              </div>
            ))
          )}
        </div>

        <div className="field">
          <label htmlFor="labor-operation">Операция</label>
          <input
            id="labor-operation"
            value={operationName}
            onChange={(e) => setOperationName(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="labor-hours">Нормо-часы</label>
          <input
            id="labor-hours"
            type="number"
            min="0"
            step="0.1"
            value={normHours}
            onChange={(e) => setNormHours(e.target.value)}
          />
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
          <button
            className="btn btn-primary"
            disabled={!operationName.trim() || normHours === "" || saving}
            onClick={handleSave}
          >
            {saving ? "Сохранение…" : "Сохранить"}
          </button>
          <button className="btn btn-secondary" onClick={onClose} style={{ marginLeft: "auto" }}>
            Отмена
          </button>
        </div>
      </div>
    </div>
  );
}
