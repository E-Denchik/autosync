import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { TagIcon, PlusIcon, SparklesIcon, TrendingUpIcon } from "../../components/icons.jsx";

const EMPTY_FORM = { sku: "", name: "", category: "", cost_price: "", current_price: "" };

export default function CardGenerator() {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [generatingId, setGeneratingId] = useState(null);
  const [analyzingId, setAnalyzingId] = useState(null);
  const [results, setResults] = useState({});
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [creating, setCreating] = useState(false);
  const toast = useToast();

  const load = () => {
    setLoading(true);
    api
      .listProducts()
      .then(setProducts)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleGenerate = async (productId) => {
    setGeneratingId(productId);
    try {
      const content = await api.generateCard(productId);
      setResults((prev) => ({ ...prev, [productId]: content }));
      toast.success("Карточка сгенерирована");
    } catch (e) {
      toast.error(e.message);
    } finally {
      setGeneratingId(null);
    }
  };

  const handleAnalyze = async (productId) => {
    setAnalyzingId(productId);
    try {
      await api.analyzePrice(productId);
      toast.success("Снимок цены создан — проверьте раздел «Цены»");
    } catch (e) {
      toast.error(e.message);
    } finally {
      setAnalyzingId(null);
    }
  };

  const handleCreateProduct = async (e) => {
    e.preventDefault();
    if (!form.sku.trim() || !form.name.trim()) {
      toast.error("SKU и название обязательны");
      return;
    }
    setCreating(true);
    try {
      await api.createProduct({
        sku: form.sku.trim(),
        name: form.name.trim(),
        category: form.category.trim() || null,
        cost_price: form.cost_price ? Number(form.cost_price) : null,
        current_price: form.current_price ? Number(form.current_price) : null,
      });
      toast.success("Товар добавлен");
      setForm(EMPTY_FORM);
      setShowForm(false);
      load();
    } catch (e2) {
      toast.error(e2.message);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Карточки и цены</h2>
          <p>
            LLM генерирует SEO-текст и характеристики на основе анализа конкурентов, а также может
            предложить цену. Ничего не публикуется в Ozon автоматически — проверьте результат перед
            использованием.
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowForm((v) => !v)}>
          <PlusIcon /> Добавить товар
        </button>
      </div>

      {showForm && (
        <form className="panel" style={{ marginBottom: 20 }} onSubmit={handleCreateProduct}>
          <div className="section-title">Новый товар</div>
          <div className="field-row">
            <div className="field">
              <label htmlFor="sku">SKU / артикул</label>
              <input
                id="sku"
                value={form.sku}
                onChange={(e) => setForm((f) => ({ ...f, sku: e.target.value }))}
                placeholder="AB-1234"
              />
            </div>
            <div className="field">
              <label htmlFor="name">Название</label>
              <input
                id="name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="Тормозной диск передний"
              />
            </div>
          </div>
          <div className="field-row">
            <div className="field">
              <label htmlFor="category">Категория</label>
              <input
                id="category"
                value={form.category}
                onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
                placeholder="Тормозная система"
              />
            </div>
            <div className="field">
              <label htmlFor="current_price">Текущая цена, ₽</label>
              <input
                id="current_price"
                type="number"
                min="0"
                step="0.01"
                value={form.current_price}
                onChange={(e) => setForm((f) => ({ ...f, current_price: e.target.value }))}
                placeholder="1500"
              />
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-primary" disabled={creating} type="submit">
              {creating ? "Сохранение…" : "Сохранить товар"}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setShowForm(false)}>
              Отмена
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <Spinner label="Загрузка товаров…" />
      ) : products.length === 0 ? (
        <div className="table-wrap">
          <EmptyState
            icon={TagIcon}
            title="Пока нет товаров"
            hint="Товары подтягиваются из Ozon Seller API по расписанию, либо их можно добавить вручную для теста."
            action={
              <button className="btn btn-primary" onClick={() => setShowForm(true)}>
                <PlusIcon /> Добавить первый товар
              </button>
            }
          />
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>SKU</th>
                <th>Название</th>
                <th>Категория</th>
                <th>Цена</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {products.map((p) => (
                <tr key={p.id}>
                  <td>{p.sku}</td>
                  <td>{p.name}</td>
                  <td className="text-muted">{p.category || "—"}</td>
                  <td>{p.current_price != null ? `${p.current_price} ₽` : "—"}</td>
                  <td>
                    <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                      <button
                        className="btn btn-secondary btn-sm"
                        disabled={analyzingId === p.id}
                        onClick={() => handleAnalyze(p.id)}
                        title="Создать предложение по цене"
                      >
                        <TrendingUpIcon /> {analyzingId === p.id ? "Анализ…" : "Цена"}
                      </button>
                      <button
                        className="btn btn-primary btn-sm"
                        disabled={generatingId === p.id}
                        onClick={() => handleGenerate(p.id)}
                      >
                        <SparklesIcon /> {generatingId === p.id ? "Генерация…" : "Карточка"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {Object.entries(results).map(([productId, content]) => (
        <div key={productId} className="panel" style={{ marginTop: 16 }}>
          <div className="section-title">{content.title}</div>
          <ul style={{ margin: "0 0 12px", paddingLeft: 20, fontSize: 13.5 }}>
            {(content.bullets || []).map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
          <p className="text-muted" style={{ fontSize: 13.5, lineHeight: 1.6 }}>
            {content.description}
          </p>
          {content.suggested_price && (
            <p style={{ fontSize: 13.5 }}>
              Предложенная цена: <strong>{content.suggested_price} ₽</strong>
            </p>
          )}
        </div>
      ))}

      <p className="text-muted" style={{ fontSize: 12.5, marginTop: 24 }}>
        Предложения по цене нужно подтвердить на странице{" "}
        <Link to="/ozon/pricing" style={{ color: "var(--accent-text)" }}>
          «Цены»
        </Link>
        .
      </p>
    </div>
  );
}
