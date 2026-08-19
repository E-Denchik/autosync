import { useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "../context/ToastContext.jsx";
import { SearchIcon, AlertCircleIcon, InfoIcon, CheckCircleIcon } from "./icons.jsx";

export default function SupplierSearchModal({ title = "Поиск у поставщиков", selectLabel = "Добавить", onSelect, onClose }) {
  const [article, setArticle] = useState("");
  const [brand, setBrand] = useState("");
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [results, setResults] = useState([]);
  const [errors, setErrors] = useState([]);
  const [notConfigured, setNotConfigured] = useState([]);
  const [addingKey, setAddingKey] = useState(null);
  const [addedKeys, setAddedKeys] = useState(new Set());
  const toast = useToast();

  const rowKey = (item, i) => `${item.supplier}-${item.article}-${i}`;

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!article.trim()) {
      toast.error("Введите артикул");
      return;
    }
    setLoading(true);
    setSearched(true);
    setAddedKeys(new Set());
    try {
      const res = await api.searchSuppliers(article.trim(), brand.trim() || undefined);
      setResults(res.results || []);
      setErrors(res.errors || []);
      setNotConfigured(res.not_configured || []);
    } catch (e2) {
      toast.error(e2.message);
    } finally {
      setLoading(false);
    }
  };

  const handleAdd = async (item, key) => {
    setAddingKey(key);
    try {
      await onSelect(item);
      setAddedKeys((prev) => new Set(prev).add(key));
    } catch (e) {
      toast.error(e.message);
    } finally {
      setAddingKey(null);
    }
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
        padding: 24,
      }}
      onClick={onClose}
    >
      <div
        className="panel"
        style={{ width: "min(960px, 100%)", maxHeight: "85vh", display: "flex", flexDirection: "column" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
          <div className="section-title" style={{ marginBottom: 0 }}>
            {title}
          </div>
          <button className="btn btn-secondary btn-sm" onClick={onClose}>
            Закрыть
          </button>
        </div>
        <p className="text-muted" style={{ fontSize: 12.5, marginTop: 0, marginBottom: 14 }}>
          Ищет разом по всем подключённым поставщикам (Rossco, АвтоЕвро, Москворечье) — артикул обязателен,
          марка помогает найти точнее.
        </p>

        <form onSubmit={handleSearch} style={{ display: "flex", gap: 8, marginBottom: 14 }}>
          <div className="field" style={{ flex: 1, position: "relative" }}>
            <input
              autoFocus
              placeholder="Артикул…"
              value={article}
              onChange={(e) => setArticle(e.target.value)}
              style={{ paddingLeft: 32 }}
            />
            <SearchIcon
              style={{ position: "absolute", left: 9, top: 11, width: 15, height: 15, color: "var(--text-faint)" }}
            />
          </div>
          <div className="field" style={{ width: 180 }}>
            <input placeholder="Марка (необязательно)" value={brand} onChange={(e) => setBrand(e.target.value)} />
          </div>
          <button className="btn btn-primary" disabled={loading} type="submit">
            {loading ? "Ищем…" : "Найти"}
          </button>
        </form>

        <div style={{ overflowY: "auto", flex: 1, minHeight: 0 }}>
          {notConfigured.map((item) => (
            <div key={item.supplier} className="hint-banner" style={{ marginBottom: 8 }}>
              <InfoIcon />
              <span>
                <strong>{item.supplier_name}</strong> не подключён. {item.hint}
              </span>
            </div>
          ))}
          {errors.map((item) => (
            <div key={item.supplier} className="hint-banner hint-warning" style={{ marginBottom: 8 }}>
              <AlertCircleIcon />
              <span>
                <strong>{item.supplier_name}</strong>: {item.message}
              </span>
            </div>
          ))}

          {searched && !loading && results.length === 0 && errors.length === 0 && notConfigured.length === 0 && (
            <div style={{ padding: 16, fontSize: 13, color: "var(--text-muted)" }}>Ничего не найдено</div>
          )}

          {results.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Поставщик</th>
                  <th>Марка</th>
                  <th>Артикул</th>
                  <th>Наименование</th>
                  <th>Цена</th>
                  <th>Наличие</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {results.map((item, i) => {
                  const key = rowKey(item, i);
                  const added = addedKeys.has(key);
                  return (
                    <tr key={key}>
                      <td className="text-muted">{item.supplier_name}</td>
                      <td>{item.brand || "—"}</td>
                      <td>{item.article || "—"}</td>
                      <td
                        title={item.name || ""}
                        style={{
                          maxWidth: 260,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {item.name || "—"}
                      </td>
                      <td>{item.price != null ? `${item.price} ₽` : "—"}</td>
                      <td className="text-muted">{item.amount ?? "—"}</td>
                      <td>
                        <div style={{ display: "flex", justifyContent: "flex-end" }}>
                          {added ? (
                            <span
                              className="text-muted"
                              style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12.5 }}
                            >
                              <CheckCircleIcon style={{ width: 14, height: 14 }} /> Добавлено
                            </span>
                          ) : (
                            <button
                              className="btn btn-secondary btn-sm"
                              disabled={addingKey === key}
                              onClick={() => handleAdd(item, key)}
                            >
                              {addingKey === key ? "…" : selectLabel}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
