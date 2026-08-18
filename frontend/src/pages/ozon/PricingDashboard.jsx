import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import Pagination from "../../components/Pagination.jsx";
import HowToUse from "../../components/HowToUse.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { TrendingUpIcon, SparklesIcon } from "../../components/icons.jsx";

const PER_PAGE = 50;

export default function PricingDashboard() {
  const [snapshots, setSnapshots] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);
  const toast = useToast();

  const load = (p = page) => {
    setLoading(true);
    api
      .listPriceSnapshots("pending", { page: p, per_page: PER_PAGE })
      .then(({ items, total: t }) => {
        setSnapshots(items);
        setTotal(t);
      })
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handlePageChange = (p) => {
    setPage(p);
    load(p);
  };

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
      setTotal((prev) => Math.max(0, prev - 1));
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
            Автоприменение цен отключено: LLM только предлагает цену на основе своей цены, себестоимости
            и (если подключён сторонний сервис аналитики в Администрирование → Интеграции) минимальной
            цены конкурентов. Нажимая «Принять», вы сразу отправляете эту цену в Ozon — «Отклонить»
            ничего не меняет ни здесь, ни на Ozon.
          </p>
        </div>
      </div>

      <HowToUse
        steps={[
          "Предложения появляются сюда после того, как вы запустите анализ цены для товара на странице «Карточки» (кнопка «Цена»).",
          "«Принять» — сразу отправляет предложенную цену в Ozon. «Отклонить» — просто убирает строку отсюда, на Ozon ничего не меняется.",
          "Наведите на «Обоснование», чтобы увидеть, почему LLM предложила именно такую цену.",
        ]}
      />

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
                <th>Категория</th>
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
                  <td style={{ maxWidth: 220 }}>{s.product_name}</td>
                  <td className="text-muted">{s.product_category || "—"}</td>
                  <td>{s.own_price != null ? `${s.own_price} ₽` : "—"}</td>
                  <td>
                    {s.competitor_min_price != null ? (
                      `${s.competitor_min_price} ₽`
                    ) : (
                      <span className="text-muted" title="Сервис аналитики конкурентов не подключён — см. Администрирование → Интеграции">
                        нет данных
                      </span>
                    )}
                  </td>
                  <td>
                    <strong>{s.suggested_price != null ? `${s.suggested_price} ₽` : "—"}</strong>
                  </td>
                  <td className="reasoning-cell" title={s.suggestion_reasoning || ""}>
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
          <Pagination page={page} perPage={PER_PAGE} total={total} onPageChange={handlePageChange} />
        </div>
      )}
    </div>
  );
}
