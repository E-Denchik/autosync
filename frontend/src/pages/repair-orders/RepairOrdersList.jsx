import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import StatusPill from "../../components/StatusPill.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { FileTextIcon, UploadIcon, ChevronRightIcon } from "../../components/icons.jsx";

export default function RepairOrdersList() {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  useEffect(() => {
    api
      .listRepairOrders()
      .then(setOrders)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Заказ-наряды</h2>
          <p>История загруженных договоров и заказ-нарядов вместе со статусом сопоставления позиций.</p>
        </div>
        <Link to="/repair-orders/upload" className="btn btn-primary">
          <UploadIcon /> Загрузить новый
        </Link>
      </div>

      {loading ? (
        <Spinner label="Загрузка…" />
      ) : orders.length === 0 ? (
        <div className="table-wrap">
          <EmptyState
            icon={FileTextIcon}
            title="Пока нет загруженных заказ-нарядов"
            hint="Загрузите договор и заказ-наряд, чтобы автоматически сопоставить позиции."
            action={
              <Link to="/repair-orders/upload" className="btn btn-primary">
                <UploadIcon /> Загрузить документы
              </Link>
            }
          />
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Заказ-наряд</th>
                <th>Договор</th>
                <th>Автомобиль</th>
                <th>Контрагент</th>
                <th>Статус</th>
                <th>Сопоставлено позиций</th>
                <th>Загружено</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id}>
                  <td>{o.original_filename}</td>
                  <td>{o.contract_filename || "—"}</td>
                  <td className="text-muted">
                    {[o.vehicle_make, o.vehicle_model].filter(Boolean).join(" ") || "—"}
                  </td>
                  <td className="text-muted">{o.contragent_name || "—"}</td>
                  <td>
                    <StatusPill status={o.status} />
                  </td>
                  <td>
                    {o.matches_total > 0
                      ? `${o.matches_total - o.matches_pending} / ${o.matches_total}`
                      : "—"}
                  </td>
                  <td className="text-muted">{new Date(o.created_at).toLocaleString("ru-RU")}</td>
                  <td>
                    <Link to={`/repair-orders/${o.id}/review`} className="btn btn-secondary btn-sm">
                      Открыть <ChevronRightIcon />
                    </Link>
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
