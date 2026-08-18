import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import StatusPill from "../../components/StatusPill.jsx";
import ConfirmDialog from "../../components/ConfirmDialog.jsx";
import FilePreviewModal from "../../components/FilePreviewModal.jsx";
import HowToUse from "../../components/HowToUse.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { PlusIcon, ChevronRightIcon, EyeIcon, FileTextIcon } from "../../components/icons.jsx";

const EMPTY_FORM = { name: "", contragent_id: "", vehicle_make: "" };

export default function ContractCatalogs() {
  const [contracts, setContracts] = useState([]);
  const [contragents, setContragents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [files, setFiles] = useState([]);
  const [creating, setCreating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [previewTarget, setPreviewTarget] = useState(null);
  const [archivingId, setArchivingId] = useState(null);
  const toast = useToast();

  const load = () => {
    setLoading(true);
    api
      .listContracts()
      .then(setContracts)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    api.listContragents().then(setContragents).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const anyPending = contracts.some((c) => c.status === "uploaded" || c.status === "parsing");
    if (!anyPending) return undefined;
    const timer = setInterval(load, 2500);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contracts]);

  const handlePreview = (file) => {
    setPreviewTarget(file);
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    if (files.length === 0) {
      toast.error("Выберите хотя бы один файл");
      return;
    }
    setCreating(true);
    try {
      await api.createContract(files, form);
      toast.success("Договор загружен — идёт разбор файла(ов)");
      setForm(EMPTY_FORM);
      setFiles([]);
      setShowForm(false);
      load();
    } catch (e2) {
      toast.error(e2.message);
    } finally {
      setCreating(false);
    }
  };

  const handleArchiveToggle = async (contract) => {
    setArchivingId(contract.id);
    try {
      const updated = contract.active
        ? await api.archiveContract(contract.id)
        : await api.unarchiveContract(contract.id);
      setContracts((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
      toast.success(contract.active ? "Договор архивирован" : "Договор снова активен");
    } catch (e) {
      toast.error(e.message);
    } finally {
      setArchivingId(null);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await api.deleteContract(deleteTarget.id);
      setContracts((prev) => prev.filter((c) => c.id !== deleteTarget.id));
      toast.success("Договор удалён");
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
          <h2>Каталоги контрактов</h2>
          <p>
            Фиксированный список запчастей и нормо-часов по гос. контракту/тендеру — загружается один раз и
            переиспользуется для всех заказ-нарядов по этому контракту, без повторной загрузки того же файла и
            без засорения общей номенклатуры 1С. При сопоставлении заказ-наряда с таким контрактом подставляются
            только позиции из его списка.
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowForm((v) => !v)}>
          <PlusIcon /> Загрузить новый контракт
        </button>
      </div>

      <HowToUse
        steps={[
          "Загружайте сюда только фиксированные списки запчастей/нормо-часов по гос. контракту или тендеру — обычный склад заказчика ведётся в разделе «Номенклатура», это разные вещи.",
          "Контракт загружается один раз и переиспользуется для всех заказ-нарядов по нему — повторно загружать тот же файл не нужно.",
          "Откройте контракт («Открыть»), чтобы посмотреть его состав, дозагрузить файлы или задать отдельные ставки нормо-часа по маркам.",
        ]}
      />

      {showForm && (
        <form className="panel" style={{ marginBottom: 20, maxWidth: 520 }} onSubmit={handleCreate}>
          <div className="field">
            <label htmlFor="c-name">Название</label>
            <input
              id="c-name"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="Например, Гос. контракт №123 / 2026"
            />
          </div>
          <div className="field">
            <label htmlFor="c-contragent">Контрагент</label>
            <select
              id="c-contragent"
              value={form.contragent_id}
              onChange={(e) => setForm((f) => ({ ...f, contragent_id: e.target.value }))}
            >
              <option value="">Не выбран</option>
              {contragents.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="c-make">Марка (для файлов-каталогов по маркам)</label>
            <input
              id="c-make"
              value={form.vehicle_make}
              onChange={(e) => setForm((f) => ({ ...f, vehicle_make: e.target.value }))}
              placeholder="Необязательно"
            />
          </div>
          <div className="field">
            <label htmlFor="c-file">Файл(ы) договора</label>
            <input
              id="c-file"
              type="file"
              multiple
              accept=".xlsx,.xlsm,.xls,.ods,.csv,.docx,.pdf,.jpg,.jpeg,.png"
              onChange={(e) => setFiles(Array.from(e.target.files))}
            />
            {files.length > 0 && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                style={{ marginTop: 8, alignSelf: "flex-start" }}
                onClick={() => handlePreview(files[0])}
              >
                <EyeIcon style={{ width: 13, height: 13 }} /> Просмотреть {files[0].name}
              </button>
            )}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-primary" disabled={creating} type="submit">
              {creating ? "Загрузка…" : "Загрузить"}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setShowForm(false)}>
              Отмена
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <Spinner label="Загрузка…" />
      ) : contracts.length === 0 ? (
        <div className="table-wrap">
          <EmptyState
            icon={FileTextIcon}
            title="Пока нет каталогов контрактов"
            hint="Загрузите файл с фиксированным списком запчастей/работ по контракту."
          />
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Название</th>
                <th>Контрагент</th>
                <th>Запчасти</th>
                <th>Нормо-часы</th>
                <th>Заказ-нарядов</th>
                <th>Статус</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {contracts.map((c) => (
                <tr key={c.id} style={{ opacity: c.active ? 1 : 0.6 }}>
                  <td>
                    {c.name || c.original_filename}
                    {!c.active && (
                      <span className="status-pill" style={{ marginLeft: 6 }}>
                        архив
                      </span>
                    )}
                  </td>
                  <td className="text-muted">{c.contragent_name || "—"}</td>
                  <td>{c.parts_count}</td>
                  <td>{c.labor_norms_count}</td>
                  <td className="text-muted">{c.repair_orders_count}</td>
                  <td>
                    <StatusPill status={c.status} />
                    {c.error_message && (
                      <div className="text-muted" style={{ fontSize: 11.5, marginTop: 2, maxWidth: 220 }}>
                        {c.error_message}
                      </div>
                    )}
                  </td>
                  <td>
                    <div style={{ display: "flex", justifyContent: "flex-end", gap: 6 }}>
                      <Link to={`/admin/contracts/${c.id}`} className="btn btn-secondary btn-sm">
                        Открыть <ChevronRightIcon />
                      </Link>
                      <button
                        className="btn btn-secondary btn-sm"
                        disabled={archivingId === c.id}
                        onClick={() => handleArchiveToggle(c)}
                      >
                        {c.active ? "Архивировать" : "Активировать"}
                      </button>
                      <button
                        className="btn btn-reject btn-sm"
                        disabled={c.repair_orders_count > 0}
                        title={c.repair_orders_count > 0 ? "Используется в заказ-нарядах — архивируйте вместо удаления" : ""}
                        onClick={() => setDeleteTarget(c)}
                      >
                        Удалить
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deleteTarget && (
        <ConfirmDialog
          title="Удалить договор?"
          message={
            <>
              Договор <strong>{deleteTarget.name || deleteTarget.original_filename}</strong> и весь его каталог
              запчастей/нормо-часов будут удалены безвозвратно.
            </>
          }
          confirmLabel="Удалить"
          danger
          busy={deleting}
          onConfirm={handleDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {previewTarget && (
        <FilePreviewModal
          blob={previewTarget}
          fileName={previewTarget.name}
          onClose={() => setPreviewTarget(null)}
        />
      )}
    </div>
  );
}
