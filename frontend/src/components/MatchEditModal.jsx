import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { SearchIcon } from "./icons.jsx";

export default function MatchEditModal({ match, repairOrderId, onClose, onSave, saving }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [showCustomForm, setShowCustomForm] = useState(false);
  const [customName, setCustomName] = useState("");
  const [customArticle, setCustomArticle] = useState("");
  const [customPrice, setCustomPrice] = useState("");

  // Поиск идёт по каталогу ДОГОВОРА (ContractPart), а не по строкам самого
  // заказ-наряда — это позиции с проверенными артикулами/ценами, которые и
  // нужно сопоставлять, а не черновик мехника. Каталог может быть большим
  // (50 000+ позиций), поэтому ищем на бэкенде с задержкой по вводу, а не
  // держим всё в памяти на фронте.
  useEffect(() => {
    setLoading(true);
    const timer = setTimeout(() => {
      api
        .listCandidates(repairOrderId, query)
        .then(setResults)
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [query, repairOrderId]);

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

  const handleSaveCustom = (e) => {
    e.preventDefault();
    if (!customName.trim()) return;
    onSave({
      matched_article: customArticle.trim() || null,
      matched_name: customName.trim(),
      matched_price: customPrice !== "" ? Number(customPrice) : null,
    });
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
          {" · Кол-во: "}
          <strong>{match.contract_qty ?? 1}</strong>
        </p>

        {!showCustomForm ? (
          <>
            <div className="field" style={{ position: "relative" }}>
              <input
                autoFocus
                placeholder="Поиск по названию или артикулу в каталоге договора…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                style={{ paddingLeft: 32 }}
              />
              <SearchIcon
                style={{ position: "absolute", left: 9, top: 32, width: 15, height: 15, color: "var(--text-faint)" }}
              />
            </div>

            <div style={{ overflowY: "auto", flex: 1, border: "1px solid var(--border)", borderRadius: 8 }}>
              {loading ? (
                <div style={{ padding: 16, fontSize: 13, color: "var(--text-muted)" }}>Ищем…</div>
              ) : results.length === 0 ? (
                <div style={{ padding: 16, fontSize: 13, color: "var(--text-muted)" }}>
                  {query ? "Ничего не найдено в каталоге договора" : "Каталог договора пуст"}
                </div>
              ) : (
                results.map((c, i) => (
                  <div
                    key={`${c.article || ""}-${i}`}
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

            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 14 }}>
              <button className="btn btn-primary" disabled={!selected || saving} onClick={handleSave}>
                {saving ? "Сохранение…" : "Выбрать"}
              </button>
              <button type="button" className="btn btn-secondary" disabled={saving} onClick={() => setShowCustomForm(true)}>
                Не нашли — ввести вручную
              </button>
              <button className="btn btn-reject" disabled={saving} onClick={handleNoMatch}>
                Нет подходящей позиции
              </button>
              <button className="btn btn-secondary" onClick={onClose} style={{ marginLeft: "auto" }}>
                Отмена
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={handleSaveCustom}>
            <p className="text-muted" style={{ fontSize: 12.5, marginTop: 0 }}>
              Позиции нет в каталоге договора — впишите вручную, она сохранится как сопоставление.
            </p>
            <div className="field">
              <label htmlFor="custom-name">Наименование</label>
              <input
                id="custom-name"
                required
                autoFocus
                value={customName}
                onChange={(e) => setCustomName(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="custom-article">Артикул</label>
              <input id="custom-article" value={customArticle} onChange={(e) => setCustomArticle(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="custom-price">Цена, ₽</label>
              <input
                id="custom-price"
                type="number"
                min="0"
                step="0.01"
                value={customPrice}
                onChange={(e) => setCustomPrice(e.target.value)}
              />
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn btn-primary" disabled={saving} type="submit">
                {saving ? "Сохранение…" : "Сохранить"}
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={saving}
                onClick={() => setShowCustomForm(false)}
              >
                Назад к поиску
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
