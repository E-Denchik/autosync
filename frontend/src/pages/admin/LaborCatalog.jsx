import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import ConfirmDialog from "../../components/ConfirmDialog.jsx";
import HowToUse from "../../components/HowToUse.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { PlusIcon, UploadIcon } from "../../components/icons.jsx";

const EMPTY_FORM = { vehicle_make: "", vehicle_model: "", operation_name: "", norm_hours: "" };

const SOURCE_LABELS = { manual: "вручную", seed: "пример", autodata: "AutoData", import: "файлом" };

export default function LaborCatalog() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [creating, setCreating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [importing, setImporting] = useState(false);
  const fileInputRef = useRef(null);
  const toast = useToast();

  const load = () => {
    setLoading(true);
    api
      .listLaborCatalog()
      .then(setEntries)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleCreate = async (e) => {
    e.preventDefault();
    setCreating(true);
    try {
      await api.createLaborCatalogEntry(form);
      toast.success("Операция добавлена в справочник");
      setForm(EMPTY_FORM);
      setShowForm(false);
      load();
    } catch (e2) {
      toast.error(e2.message);
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await api.deleteLaborCatalogEntry(deleteTarget.id);
      setEntries((prev) => prev.filter((en) => en.id !== deleteTarget.id));
      toast.success("Запись удалена");
      setDeleteTarget(null);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setDeleting(false);
    }
  };

  const handleFilePicked = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setImporting(true);
    try {
      const result = await api.importLaborCatalog(file);
      toast.success(
        `Загружено: ${result.created} новых, ${result.updated} обновлено (всего строк в файле: ${result.total})`
      );
      load();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setImporting(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Нормо-часы</h2>
          <p>
            Справочник операций и нормо-часов по маркам/моделям — используется для автозаполнения работ в
            заказ-нарядах. Пока нет доступа к внешней базе AutoData — заполняется вручную или файлом.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className="btn btn-secondary"
            disabled={importing}
            onClick={() => fileInputRef.current?.click()}
          >
            <UploadIcon style={{ width: 13, height: 13 }} /> {importing ? "Загрузка…" : "Загрузить файлом"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xlsm,.xls,.ods,.csv,.docx,.pdf,.jpg,.jpeg,.png,.bmp,.tiff,.tif"
            style={{ display: "none" }}
            onChange={handleFilePicked}
          />
          <button className="btn btn-primary" onClick={() => setShowForm((v) => !v)}>
            <PlusIcon /> Добавить операцию
          </button>
        </div>
      </div>

      <HowToUse
        steps={[
          "Здесь справочник операций и норм времени по маркам/моделям — он используется, чтобы автоматически подставлять нормо-часы в загруженные заказ-наряды.",
          "Модель можно не указывать — тогда запись будет действовать для всех моделей этой марки.",
          "«Загрузить файлом» разом добавляет много операций — Excel/CSV/Word/PDF/фото со столбцами марка, (модель — необязательно), операция и нормо-часы, названия колонок могут быть любыми. Операция для той же марки/модели, что уже есть в списке, обновится, а не задвоится.",
        ]}
      />

      {showForm && (
        <form className="panel" style={{ marginBottom: 20, maxWidth: 480 }} onSubmit={handleCreate}>
          <div className="field">
            <label htmlFor="vehicle_make">Марка</label>
            <input
              id="vehicle_make"
              required
              value={form.vehicle_make}
              onChange={(e) => setForm((f) => ({ ...f, vehicle_make: e.target.value }))}
              placeholder="например, ВАЗ"
            />
          </div>
          <div className="field">
            <label htmlFor="vehicle_model">Модель (необязательно)</label>
            <input
              id="vehicle_model"
              value={form.vehicle_model}
              onChange={(e) => setForm((f) => ({ ...f, vehicle_model: e.target.value }))}
              placeholder="пусто — общее для всех моделей марки"
            />
          </div>
          <div className="field">
            <label htmlFor="operation_name">Операция</label>
            <input
              id="operation_name"
              required
              value={form.operation_name}
              onChange={(e) => setForm((f) => ({ ...f, operation_name: e.target.value }))}
              placeholder="например, Замена тормозных колодок передних"
            />
          </div>
          <div className="field">
            <label htmlFor="norm_hours">Нормо-часы</label>
            <input
              id="norm_hours"
              type="number"
              min="0"
              step="0.1"
              required
              value={form.norm_hours}
              onChange={(e) => setForm((f) => ({ ...f, norm_hours: e.target.value }))}
            />
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-primary" disabled={creating} type="submit">
              {creating ? "Сохранение…" : "Добавить"}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setShowForm(false)}>
              Отмена
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <Spinner label="Загрузка…" />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Марка</th>
                <th>Модель</th>
                <th>Операция</th>
                <th>Нормо-часы</th>
                <th>Источник</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {entries.map((en) => (
                <tr key={en.id}>
                  <td>{en.vehicle_make}</td>
                  <td className="text-muted">{en.vehicle_model || "все модели"}</td>
                  <td>{en.operation_name}</td>
                  <td>{en.norm_hours}</td>
                  <td className="text-muted">{SOURCE_LABELS[en.source] || en.source}</td>
                  <td>
                    <div style={{ display: "flex", justifyContent: "flex-end" }}>
                      <button className="btn btn-reject btn-sm" onClick={() => setDeleteTarget(en)}>
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
          title="Удалить запись?"
          message={
            <>
              Операция <strong>{deleteTarget.operation_name}</strong> будет удалена из справочника.
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
