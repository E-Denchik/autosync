import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import StatusPill from "../../components/StatusPill.jsx";
import Pagination from "../../components/Pagination.jsx";
import FilePreviewModal from "../../components/FilePreviewModal.jsx";
import ConfirmDialog from "../../components/ConfirmDialog.jsx";
import RepairOrderEditModal from "../../components/RepairOrderEditModal.jsx";
import HowToUse from "../../components/HowToUse.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { FileTextIcon, UploadIcon, ChevronRightIcon, EyeIcon, EditIcon } from "../../components/icons.jsx";

const PER_PAGE = 50;

export default function RepairOrdersList() {
  const [orders, setOrders] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [previewTarget, setPreviewTarget] = useState(null);
  const [editTarget, setEditTarget] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const toast = useToast();

  const handlePreview = async (orderId, source, fileName) => {
    try {
      const blob = await api.getRepairOrderSourceFile(orderId, source);
      setPreviewTarget({ blob, fileName });
    } catch (e) {
      toast.error(e.message);
    }
  };

  const load = (p) => {
    setLoading(true);
    api
      .listRepairOrders({ page: p, per_page: PER_PAGE })
      .then(({ items, total: t }) => {
        setOrders(items);
        setTotal(t);
      })
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handlePageChange = (p) => {
    setPage(p);
    load(p);
  };

  const handleSaved = (updated) => {
    setOrders((prev) =>
      prev.map((o) =>
        o.id === editTarget.id
          ? {
              ...o,
              contragent_name: updated.contragent_name,
              vehicle_make: updated.vehicle_make,
              vehicle_model: updated.vehicle_model,
              order_number: updated.order_number,
              order_date: updated.order_date,
            }
          : o
      )
    );
    setEditTarget(null);
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await api.deleteRepairOrder(deleteTarget.id);
      setOrders((prev) => prev.filter((o) => o.id !== deleteTarget.id));
      setTotal((t) => t - 1);
      toast.success(`Заказ-наряд «${deleteTarget.original_filename}» удалён`);
      setDeleteTarget(null);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setDeleting(false);
    }
  };

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

      <HowToUse
        steps={[
          "Здесь все загруженные заказ-наряды и статус их обработки/проверки.",
          "Нажмите «Открыть» у нужной строки, чтобы проверить сопоставленные позиции и работы.",
          "Значок с глазом рядом с именем файла открывает быстрый просмотр исходного документа без скачивания.",
        ]}
      />

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
                <th>№ наряда</th>
                <th>Заказ-наряд</th>
                <th>Договор</th>
                <th>Автомобиль</th>
                <th>Контрагент</th>
                <th>Статус</th>
                <th>Проверено позиций и работ</th>
                <th>Загружено</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id}>
                  <td className="text-muted">
                    {o.order_number ? (
                      <>
                        № {o.order_number}
                        {o.order_date && <div style={{ fontSize: 11.5 }}>от {o.order_date}</div>}
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn-link"
                      onClick={() => handlePreview(o.id, "order", o.original_filename)}
                      title="Просмотреть файл"
                    >
                      <EyeIcon style={{ width: 12, height: 12 }} /> {o.original_filename}
                    </button>
                    {o.extra_file_count > 0 && (
                      <span className="text-muted" style={{ fontSize: 11.5, marginLeft: 6 }}>
                        +{o.extra_file_count}
                      </span>
                    )}
                  </td>
                  <td>
                    {o.contract_filename ? (
                      <button
                        type="button"
                        className="btn-link"
                        onClick={() => handlePreview(o.id, "contract", o.contract_filename)}
                        title="Просмотреть файл"
                      >
                        <EyeIcon style={{ width: 12, height: 12 }} /> {o.contract_filename}
                      </button>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="text-muted">
                    {[o.vehicle_make, o.vehicle_model].filter(Boolean).join(" ") || "—"}
                  </td>
                  <td className="text-muted">{o.contragent_name || "—"}</td>
                  <td>
                    <StatusPill status={o.status} />
                  </td>
                  <td>
                    {o.matches_total + o.labor_total > 0
                      ? `${
                          o.matches_total + o.labor_total - o.matches_pending - o.labor_pending
                        } / ${o.matches_total + o.labor_total}`
                      : "—"}
                  </td>
                  <td className="text-muted">{new Date(o.created_at).toLocaleString("ru-RU")}</td>
                  <td>
                    <div style={{ display: "flex", justifyContent: "flex-end", gap: 6 }}>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        title="Изменить контрагента/машину"
                        onClick={() => setEditTarget(o)}
                      >
                        <EditIcon style={{ width: 13, height: 13 }} />
                      </button>
                      <button
                        type="button"
                        className="btn btn-reject btn-sm"
                        title="Удалить заказ-наряд"
                        onClick={() => setDeleteTarget(o)}
                      >
                        Удалить
                      </button>
                      <Link to={`/repair-orders/${o.id}/review`} className="btn btn-secondary btn-sm">
                        Открыть <ChevronRightIcon />
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination page={page} perPage={PER_PAGE} total={total} onPageChange={handlePageChange} />
        </div>
      )}

      {previewTarget && (
        <FilePreviewModal
          blob={previewTarget.blob}
          fileName={previewTarget.fileName}
          onClose={() => setPreviewTarget(null)}
        />
      )}

      {editTarget && (
        <RepairOrderEditModal order={editTarget} onClose={() => setEditTarget(null)} onSaved={handleSaved} />
      )}

      {deleteTarget && (
        <ConfirmDialog
          title="Удалить заказ-наряд?"
          message={
            <>
              Заказ-наряд <strong>{deleteTarget.original_filename}</strong> вместе со всеми сопоставленными
              позициями и работами будет удалён безвозвратно.
            </>
          }
          confirmLabel="Удалить"
          danger
          busy={deleting}
          onConfirm={handleDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}
