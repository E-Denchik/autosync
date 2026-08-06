import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client.js";
import StatCard from "../components/StatCard.jsx";
import Spinner from "../components/Spinner.jsx";
import { useToast } from "../context/ToastContext.jsx";
import { TagIcon, FileTextIcon, ListIcon, TrendingUpIcon, UploadIcon, SparklesIcon } from "../components/icons.jsx";

export default function Dashboard() {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  useEffect(() => {
    api
      .dashboardSummary()
      .then(setSummary)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Обзор</h2>
          <p>Что происходит в AutoSync прямо сейчас — цены, ожидающие решения, и заказ-наряды в обработке.</p>
        </div>
      </div>

      {loading ? (
        <Spinner label="Загрузка сводки…" />
      ) : (
        <div className="stat-grid">
          <StatCard
            icon={TrendingUpIcon}
            label="Предложений по цене ждут решения"
            value={summary.pending_price_suggestions}
            to="/ozon/pricing"
          />
          <StatCard icon={TagIcon} label="Товаров в каталоге" value={summary.products_total} to="/ozon/cards" />
          <StatCard
            icon={FileTextIcon}
            label="Заказ-нарядов нужно проверить"
            value={summary.repair_orders_needs_review}
            to="/repair-orders"
          />
          <StatCard
            icon={ListIcon}
            label="Позиций сопоставления ждут решения"
            value={summary.pending_part_matches}
            to="/repair-orders"
          />
        </div>
      )}

      <div className="section-title">Быстрые действия</div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <Link to="/repair-orders/upload" className="btn btn-primary">
          <UploadIcon /> Загрузить договор и заказ-наряд
        </Link>
        <Link to="/ozon/cards" className="btn btn-secondary">
          <SparklesIcon /> Сгенерировать карточку товара
        </Link>
      </div>
    </div>
  );
}
