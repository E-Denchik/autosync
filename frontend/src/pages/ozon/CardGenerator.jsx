import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import {
  TagIcon,
  SparklesIcon,
  TrendingUpIcon,
  SearchIcon,
  RefreshIcon,
  EditIcon,
} from "../../components/icons.jsx";

const UNCATEGORIZED = "__uncategorized__";

export default function CardGenerator() {
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [activeCategory, setActiveCategory] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [generatingId, setGeneratingId] = useState(null);
  const [analyzingId, setAnalyzingId] = useState(null);
  const [results, setResults] = useState({});
  const [editingCostId, setEditingCostId] = useState(null);
  const [costInput, setCostInput] = useState("");
  const [savingCost, setSavingCost] = useState(false);
  const toast = useToast();
  const isFirstRender = useRef(true);

  const loadCategories = () => {
    api.listProductCategories().then(setCategories).catch((e) => toast.error(e.message));
  };

  const loadProducts = (category, q) => {
    setLoading(true);
    api
      .listProducts({ category, q })
      .then(setProducts)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  };

  const load = () => {
    loadCategories();
    loadProducts(activeCategory, search);
  };

  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Категория/поиск меняются — перезагружаем список с небольшой задержкой,
  // чтобы не дёргать backend на каждое нажатие клавиши. Пропускаем первый
  // рендер — начальная загрузка уже сделана выше, без задержки.
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    const timer = setTimeout(() => loadProducts(activeCategory, search), 300);
    return () => clearTimeout(timer);
  }, [activeCategory, search]); // eslint-disable-line react-hooks/exhaustive-deps

  const totalCount = categories.reduce((sum, c) => sum + c.count, 0);

  const handleSync = async () => {
    setSyncing(true);
    try {
      const res = await api.syncOzonCatalog();
      if (res.ok) {
        toast.success(`Синхронизировано: добавлено ${res.created}, обновлено ${res.updated}`);
        load();
      } else {
        toast.error(res.message);
      }
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSyncing(false);
    }
  };

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

  const startEditCost = (p) => {
    setEditingCostId(p.id);
    setCostInput(p.cost_price ?? "");
  };

  const cancelEditCost = () => {
    setEditingCostId(null);
    setCostInput("");
  };

  const saveCost = async (productId) => {
    setSavingCost(true);
    try {
      const updated = await api.updateCostPrice(productId, costInput === "" ? null : Number(costInput));
      setProducts((prev) => prev.map((p) => (p.id === productId ? updated : p)));
      setEditingCostId(null);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSavingCost(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Карточки и цены</h2>
          <p>
            Каталог подтягивается только из Ozon Seller API — ручного добавления товаров нет.
            LLM генерирует SEO-текст и характеристики на основе анализа конкурентов, а также может
            предложить цену. Ничего не публикуется в Ozon автоматически — проверьте результат перед
            использованием.
          </p>
        </div>
        <button className="btn btn-primary" disabled={syncing} onClick={handleSync}>
          <RefreshIcon /> {syncing ? "Синхронизация…" : "Синхронизировать с Ozon"}
        </button>
      </div>

      {categories.length > 0 && (
        <div className="category-chips">
          <button
            className={`category-chip${activeCategory === "" ? " active" : ""}`}
            onClick={() => setActiveCategory("")}
          >
            Все <span className="category-chip-count">{totalCount}</span>
          </button>
          {categories.map(({ category, count }) => {
            const value = category ?? UNCATEGORIZED;
            return (
              <button
                key={value}
                className={`category-chip${activeCategory === value ? " active" : ""}`}
                onClick={() => setActiveCategory(value)}
              >
                {category ?? "Без категории"} <span className="category-chip-count">{count}</span>
              </button>
            );
          })}
        </div>
      )}

      <div className="field" style={{ maxWidth: 360, marginBottom: 16 }}>
        <label htmlFor="product-search" style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <SearchIcon style={{ width: 13, height: 13 }} /> Поиск по названию или SKU
        </label>
        <input
          id="product-search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="например, тормозной диск или AB-1234"
        />
      </div>

      {loading ? (
        <Spinner label="Загрузка товаров…" />
      ) : products.length === 0 ? (
        <div className="table-wrap">
          <EmptyState
            icon={TagIcon}
            title={activeCategory || search ? "Ничего не найдено" : "Пока нет товаров"}
            hint={
              activeCategory || search
                ? "Попробуйте выбрать другую категорию или изменить поисковый запрос."
                : "Задайте OZON_CLIENT_ID и OZON_API_KEY (Администрирование → Интеграции) и нажмите «Синхронизировать с Ozon»."
            }
            action={
              !(activeCategory || search) && (
                <button className="btn btn-primary" disabled={syncing} onClick={handleSync}>
                  <RefreshIcon /> {syncing ? "Синхронизация…" : "Синхронизировать с Ozon"}
                </button>
              )
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
                <th>Цена на Ozon</th>
                <th>Закупочная цена</th>
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
                    {editingCostId === p.id ? (
                      <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          autoFocus
                          disabled={savingCost}
                          value={costInput}
                          onChange={(e) => setCostInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") saveCost(p.id);
                            if (e.key === "Escape") cancelEditCost();
                          }}
                          style={{ width: 88, padding: "4px 6px", fontSize: 13 }}
                        />
                        <button
                          className="btn btn-primary btn-sm"
                          disabled={savingCost}
                          onClick={() => saveCost(p.id)}
                        >
                          OK
                        </button>
                      </div>
                    ) : (
                      <span
                        onClick={() => startEditCost(p)}
                        title="Изменить закупочную цену"
                        style={{
                          cursor: "pointer",
                          borderBottom: "1px dashed var(--border-strong)",
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 4,
                        }}
                      >
                        {p.cost_price != null ? `${p.cost_price} ₽` : "—"}
                        <EditIcon style={{ width: 11, height: 11, opacity: 0.6 }} />
                      </span>
                    )}
                  </td>
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
