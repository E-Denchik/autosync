import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { TrendingUpIcon, SparklesIcon } from "../../components/icons.jsx";

export default function PricingDashboard() {
  const [snapshots, setSnapshots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);
  const toast = useToast();

  const load = () => {
    setLoading(true);
    api
      .listPriceSnapshots("pending")
      .then(setSnapshots)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDecision = async (id, decision) => {
    setBusyId(id);
    try {
      if (decision === "approve") {
        await api.approvePriceSnapshot(id);
        toast.success("Цена принята и отправлена в Ozon");
      } else {
        await api.rejectPriceSnapshot(id);
        toast.info("Предложение отклонено");
      }
      setSnapshots((prev) => prev.filter((s) => s.id !== id));
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Предложения по цене</h2>
          <p>
            Автоприменение цен отключено — каждое предложение требует ручного подтверждения, пока не
            накоплена статистика точности модели.
          </p>
        </div>
      </div>

      {loading ? (
        <Spinner label="Загрузка предложений…" />
      ) : snapshots.length === 0 ? (
        <div className="table-wrap">
          <EmptyState
            icon={TrendingUpIcon}
            title="Нет предложений, ожидающих проверки"
            hint="Запустите анализ цены для товара на странице «Карточки», и предложение появится здесь."
            action={
              <Link to="/ozon/cards" className="btn btn-primary">
                <SparklesIcon /> Перейти к товарам
              </Link>
            }
          />
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Товар</th>
                <th>Своя цена</th>
                <th>Мин. у конкурентов</th>
                <th>Предложение</th>
                <th>Обоснование</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {snapshots.map((s) => (
                <tr key={s.id}>
                  <td>{s.product_name}</td>
                  <td>{s.own_price ?? "—"}</td>
                  <td>{s.competitor_min_price ?? "—"}</td>
                  <td>
                    <strong>{s.suggested_price ?? "—"}</strong>
                  </td>
                  <td style={{ maxWidth: 320, color: "var(--text-muted)" }}>
                    {s.suggestion_reasoning || "—"}
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                      <button
                        className="btn btn-approve btn-sm"
                        disabled={busyId === s.id}
                        onClick={() => handleDecision(s.id, "approve")}
                      >
                        Принять
                      </button>
                      <button
                        className="btn btn-reject btn-sm"
                        disabled={busyId === s.id}
                        onClick={() => handleDecision(s.id, "reject")}
                      >
                        Отклонить
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
