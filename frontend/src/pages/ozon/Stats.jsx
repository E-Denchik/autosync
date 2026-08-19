import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import StatCard from "../../components/StatCard.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import HowToUse from "../../components/HowToUse.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { TrendingUpIcon, TagIcon, AlertCircleIcon, SparklesIcon } from "../../components/icons.jsx";

const CHART_WIDTH = 720;
const CHART_HEIGHT = 240;
const PADDING = { top: 16, right: 16, bottom: 28, left: 48 };

function LineChart({ history }) {
  const series = [
    { key: "own_price", label: "Наша цена", color: "var(--accent)" },
    { key: "competitor_min_price", label: "Мин. у конкурентов", color: "var(--danger)" },
    { key: "competitor_avg_price", label: "Средняя у конкурентов", color: "var(--warning)" },
  ];

  const values = history.flatMap((row) => series.map((s) => row[s.key]).filter((v) => v != null));
  if (values.length === 0) return null;

  const minY = Math.min(...values) * 0.95;
  const maxY = Math.max(...values) * 1.05;
  const innerWidth = CHART_WIDTH - PADDING.left - PADDING.right;
  const innerHeight = CHART_HEIGHT - PADDING.top - PADDING.bottom;

  const x = (i) =>
    PADDING.left + (history.length <= 1 ? innerWidth / 2 : (i / (history.length - 1)) * innerWidth);
  const y = (v) => PADDING.top + innerHeight - ((v - minY) / (maxY - minY || 1)) * innerHeight;

  const gridLines = 4;

  return (
    <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} width="100%" style={{ maxWidth: CHART_WIDTH }}>
      {Array.from({ length: gridLines + 1 }).map((_, i) => {
        const value = minY + ((maxY - minY) * i) / gridLines;
        const yPos = y(value);
        return (
          <g key={i}>
            <line
              x1={PADDING.left}
              x2={CHART_WIDTH - PADDING.right}
              y1={yPos}
              y2={yPos}
              stroke="var(--border)"
              strokeWidth="1"
            />
            <text x={4} y={yPos + 4} fontSize="10.5" fill="var(--text-faint)">
              {Math.round(value)}
            </text>
          </g>
        );
      })}

      {series.map((s) => {
        const pointList = history
          .map((row, i) => (row[s.key] != null ? { x: x(i), y: y(row[s.key]), value: row[s.key] } : null))
          .filter(Boolean);
        if (pointList.length === 0) return null;
        return (
          <g key={s.key}>
            {pointList.length > 1 && (
              <polyline
                points={pointList.map((p) => `${p.x},${p.y}`).join(" ")}
                fill="none"
                stroke={s.color}
                strokeWidth="2.5"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            )}
            {pointList.map((p, i) => (
              <g key={i}>
                <circle cx={p.x} cy={p.y} r="4" fill={s.color} />
                {history.length <= 5 && (
                  <text x={p.x} y={p.y - 10} fontSize="10.5" textAnchor="middle" fill={s.color}>
                    {Math.round(p.value)}
                  </text>
                )}
              </g>
            ))}
          </g>
        );
      })}

      {history.map((row, i) => (
        <text
          key={row.date}
          x={x(i)}
          y={CHART_HEIGHT - 6}
          fontSize="10"
          textAnchor="middle"
          fill="var(--text-faint)"
        >
          {i === 0 || i === history.length - 1 || history.length <= 6 ? row.date.slice(5) : ""}
        </text>
      ))}

      <g transform={`translate(${PADDING.left}, ${CHART_HEIGHT - 2})`}>
        {series.map((s, i) => (
          <g key={s.key} transform={`translate(${i * 170}, 0)`}>
            <rect y={-96} width="10" height="10" rx="2" fill={s.color} />
            <text x={14} y={-88} fontSize="11" fill="var(--text-muted)">
              {s.label}
            </text>
          </g>
        ))}
      </g>
    </svg>
  );
}

function PositionBar({ position, total }) {
  const segments = [
    { key: "below_competitor_min", label: "Дешевле всех конкурентов", color: "var(--success)" },
    { key: "between_min_and_avg", label: "В рыночном диапазоне", color: "var(--accent)" },
    { key: "above_competitor_avg", label: "Дороже среднего по рынку", color: "var(--danger)" },
    { key: "no_competitor_data", label: "Нет данных по рынку", color: "var(--text-faint)" },
  ];

  if (!total) return null;

  return (
    <div>
      <div
        style={{
          display: "flex",
          height: 16,
          borderRadius: 8,
          overflow: "hidden",
          marginBottom: 14,
        }}
      >
        {segments.map((seg) => {
          const count = position[seg.key] || 0;
          const pct = (count / total) * 100;
          if (pct === 0) return null;
          return <div key={seg.key} style={{ width: `${pct}%`, background: seg.color }} title={seg.label} />;
        })}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
        {segments.map((seg) => (
          <div key={seg.key} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5 }}>
            <span
              style={{ width: 10, height: 10, borderRadius: 2, background: seg.color, display: "inline-block" }}
            />
            <span className="text-muted">
              {seg.label}: <strong style={{ color: "var(--text)" }}>{position[seg.key] || 0}</strong>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

const SORTABLE_COLUMNS = [
  { key: "name", label: "Товар" },
  { key: "current_price", label: "Цена на Ozon" },
  { key: "units_sold_7d", label: "Продажи, 7дн" },
  { key: "revenue_7d", label: "Выручка, 7дн" },
  { key: "competitor_min_price", label: "Мин. у конкурентов" },
  { key: "competitor_avg_price", label: "Средняя у конкурентов" },
];

const POSITION_META = {
  below_min: { label: "Дешевле всех конкурентов", color: "var(--success)", soft: "var(--success-soft)", text: "var(--success-text)" },
  between: { label: "В рыночном диапазоне", color: "var(--accent)", soft: "var(--accent-soft)", text: "var(--accent-text)" },
  above_avg: { label: "Дороже среднего по рынку", color: "var(--danger)", soft: "var(--danger-soft)", text: "var(--danger-text)" },
  no_data: { label: "Нет данных по рынку", color: "var(--text-faint)", soft: "var(--bg-sunken)", text: "var(--text-muted)" },
};

function ProductsCompareTable() {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState("current_price");
  const [sortOrder, setSortOrder] = useState("desc");
  const [expandedId, setExpandedId] = useState(null);
  const [historyCache, setHistoryCache] = useState({});
  const [historyLoading, setHistoryLoading] = useState(null);
  const toast = useToast();

  useEffect(() => {
    setLoading(true);
    api
      .ozonStatsProducts(sortKey, sortOrder)
      .then(setProducts)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sortKey, sortOrder]);

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortOrder((o) => (o === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortOrder("desc");
    }
  };

  const toggleHistory = async (id) => {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    if (!historyCache[id]) {
      setHistoryLoading(id);
      try {
        const data = await api.ozonProductPriceHistory(id);
        setHistoryCache((prev) => ({ ...prev, [id]: data }));
      } catch (e) {
        toast.error(e.message);
      } finally {
        setHistoryLoading(null);
      }
    }
  };

  if (loading && products.length === 0) return <Spinner label="Загружаем товары…" />;

  if (products.length === 0) {
    return (
      <EmptyState
        icon={TagIcon}
        title="Пока нет товаров"
        hint="Синхронизируйте каталог с Ozon на странице «Карточки»."
        action={
          <Link to="/ozon/cards" className="btn btn-primary">
            <SparklesIcon /> Перейти к товарам
          </Link>
        }
      />
    );
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {SORTABLE_COLUMNS.map((col) => (
              <th key={col.key} onClick={() => handleSort(col.key)} style={{ cursor: "pointer", whiteSpace: "nowrap" }}>
                {col.label} {sortKey === col.key ? (sortOrder === "asc" ? "↑" : "↓") : ""}
              </th>
            ))}
            <th>Позиция</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {products.map((p) => {
            const pos = POSITION_META[p.price_position] || POSITION_META.no_data;
            return (
              <Fragment key={p.id}>
                <tr>
                  <td style={{ maxWidth: 280 }}>
                    <div
                      title={p.name}
                      style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                    >
                      {p.name}
                    </div>
                    <div
                      className="text-muted"
                      style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                    >
                      {p.sku}
                      {p.category ? ` · ${p.category}` : ""}
                    </div>
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>{p.current_price != null ? `${p.current_price} ₽` : "—"}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{p.units_sold_7d ?? "—"}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{p.revenue_7d != null ? `${p.revenue_7d} ₽` : "—"}</td>
                  <td className="text-muted" style={{ whiteSpace: "nowrap" }}>
                    {p.competitor_min_price != null ? `${p.competitor_min_price} ₽` : "—"}
                  </td>
                  <td className="text-muted" style={{ whiteSpace: "nowrap" }}>
                    {p.competitor_avg_price != null ? `${p.competitor_avg_price} ₽` : "—"}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <span
                      style={{
                        display: "inline-block",
                        padding: "2px 8px",
                        borderRadius: 999,
                        fontSize: 12,
                        background: pos.soft,
                        color: pos.text,
                      }}
                    >
                      {pos.label}
                    </span>
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="btn btn-secondary btn-sm" onClick={() => toggleHistory(p.id)}>
                      {expandedId === p.id ? "Скрыть" : "История"}
                    </button>
                  </td>
                </tr>
                {expandedId === p.id && (
                  <tr>
                    <td colSpan={SORTABLE_COLUMNS.length + 2} style={{ background: "var(--bg-sunken)", padding: 16 }}>
                      {historyLoading === p.id ? (
                        <Spinner label="Загружаем историю…" />
                      ) : historyCache[p.id]?.length > 0 ? (
                        <LineChart history={historyCache[p.id]} />
                      ) : (
                        <div className="text-muted" style={{ fontSize: 12.5 }}>
                          История цены пока не накопилась — запустите анализ цены для этого товара на странице «Карточки».
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function Stats() {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  useEffect(() => {
    api
      .ozonStatsSummary()
      .then(setSummary)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) return <Spinner label="Считаем статистику…" />;
  if (!summary) return null;

  const totalTracked = Object.values(summary.price_position).reduce((a, b) => a + b, 0);

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Статистика по ценам</h2>
          <p>Цена на Ozon рядом со статистикой продаж по каждому товару, динамика относительно конкурентов и распределение позиций по рынку.</p>
        </div>
      </div>

      <HowToUse
        steps={[
          "Таблица «Цена и статистика по товарам» — по каждому товару цена на Ozon рядом с продажами и выручкой за 7 дней. Нажмите на заголовок столбца, чтобы отсортировать (например, дорогие товары с низкими продажами — по цене по убыванию).",
          "Кнопка «История» в строке товара показывает, как менялась его цена относительно конкурентов во времени.",
          "Данные по конкурентам и позиции появляются, только когда для товаров запущен анализ цены на странице «Карточки» (кнопка «Цена») — чем чаще анализ, тем точнее данные.",
          "Нижняя полоса — сколько товаров сейчас дешевле всех конкурентов, в рыночном диапазоне или дороже среднего.",
        ]}
      />

      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-header">
          <h3>Цена и статистика по товарам</h3>
        </div>
        <ProductsCompareTable />
      </div>

      <div className="stat-grid" style={{ marginBottom: 20 }}>
        <StatCard icon={TagIcon} label="Товаров с историей цен" value={summary.products_tracked} />
        <StatCard
          icon={AlertCircleIcon}
          label="Дороже среднего по рынку"
          value={summary.price_position.above_competitor_avg}
        />
        <StatCard
          icon={TrendingUpIcon}
          label="Дешевле всех конкурентов"
          value={summary.price_position.below_competitor_min}
        />
      </div>

      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-header">
          <h3>Позиция по цене относительно рынка</h3>
        </div>
        {totalTracked > 0 ? (
          <PositionBar position={summary.price_position} total={totalTracked} />
        ) : (
          <EmptyState
            icon={TrendingUpIcon}
            title="Пока нет данных"
            hint="Запустите анализ цены хотя бы для одного товара на странице «Карточки»."
            action={
              <Link to="/ozon/cards" className="btn btn-primary">
                <SparklesIcon /> Перейти к товарам
              </Link>
            }
          />
        )}
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Динамика цены (среднее по всем товарам в день)</h3>
        </div>
        {summary.price_history.length > 0 ? (
          <LineChart history={summary.price_history} />
        ) : (
          <EmptyState
            icon={TrendingUpIcon}
            title="Недостаточно данных для графика"
            hint="История строится по снимкам цены — накопится по мере анализа товаров во времени."
            action={
              <Link to="/ozon/cards" className="btn btn-primary">
                <SparklesIcon /> Перейти к товарам
              </Link>
            }
          />
        )}
      </div>
    </div>
  );
}
