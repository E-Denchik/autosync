import { useMemo, useState } from "react";
import { SearchIcon } from "./icons.jsx";

export default function MatchEditModal({ match, candidates, onClose, onSave, saving }) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return candidates;
    return candidates.filter(
      (c) => c.name?.toLowerCase().includes(q) || c.article?.toLowerCase().includes(q)
    );
  }, [query, candidates]);

  const handleSave = () => {
    if (!selected) return;
    onSave({
      matched_article: selected.article ?? null,
      matched_name: selected.name,
      matched_price: selected.price ?? null,
    });
  };

  const handleNoMatch = () => {
    onSave({ matched_article: null, matched_name: "Нет подходящей позиции", matched_price: null });
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
        <div className="section-title">Изменить сопоставление</div>
        <p className="text-muted" style={{ fontSize: 12.5, marginTop: -6, marginBottom: 14 }}>
          Договор: <strong>{match.contract_article || "—"}</strong> / {match.contract_name}
        </p>

        <div className="field" style={{ position: "relative" }}>
          <input
            autoFocus
            placeholder="Поиск по названию или артикулу…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ paddingLeft: 32 }}
          />
          <SearchIcon
            style={{ position: "absolute", left: 9, top: 32, width: 15, height: 15, color: "var(--text-faint)" }}
          />
        </div>

        <div style={{ overflowY: "auto", flex: 1, border: "1px solid var(--border)", borderRadius: 8 }}>
          {filtered.length === 0 ? (
            <div style={{ padding: 16, fontSize: 13, color: "var(--text-muted)" }}>Ничего не найдено</div>
          ) : (
            filtered.map((c, i) => (
              <div
                key={i}
                onClick={() => setSelected(c)}
                style={{
                  padding: "10px 12px",
                  fontSize: 13,
                  cursor: "pointer",
                  borderBottom: "1px solid var(--border)",
                  background: selected === c ? "var(--accent-soft)" : "transparent",
                }}
              >
                <div style={{ fontWeight: 600 }}>{c.name}</div>
                <div className="text-muted" style={{ fontSize: 12 }}>
                  {c.article || "без артикула"} {c.price != null ? `· ${c.price} ₽` : ""}
                </div>
              </div>
            ))
          )}
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <button className="btn btn-primary" disabled={!selected || saving} onClick={handleSave}>
            {saving ? "Сохранение…" : "Выбрать"}
          </button>
          <button className="btn btn-reject" disabled={saving} onClick={handleNoMatch}>
            Нет подходящей позиции
          </button>
          <button className="btn btn-secondary" onClick={onClose} style={{ marginLeft: "auto" }}>
            Отмена
          </button>
        </div>
      </div>
    </div>
  );
}
