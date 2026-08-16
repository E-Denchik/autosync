import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import ConfirmDialog from "../../components/ConfirmDialog.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import Pagination from "../../components/Pagination.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { PlusIcon, UploadIcon, SearchIcon } from "../../components/icons.jsx";

const PER_PAGE = 50;

const EMPTY_FORM = {
  code: "",
  cat_number: "",
  manufacturer: "",
  name: "",
  unit: "",
  stock_qty: "",
  reserved_qty: "",
  warehouse: "",
};

const ACCEPTED = [".xlsx", ".xlsm", ".xls", ".ods", ".csv"];

export default function NomenclatureCatalog() {
  const [entries, setEntries] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [creating, setCreating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const toast = useToast();

  const load = (q = query, p = page) => {
    setLoading(true);
    api
      .listNomenclature(q, { page: p, per_page: PER_PAGE })
      .then(({ items, total: t }) => {
        setEntries(items);
        setTotal(t);
      })
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSearch = (e) => {
    e.preventDefault();
    setPage(1);
    load(query, 1);
  };

  const handlePageChange = (p) => {
    setPage(p);
    load(query, p);
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    setCreating(true);
    try {
      await api.createNomenclatureEntry(form);
      toast.success("Запись добавлена");
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
      await api.deleteNomenclatureEntry(deleteTarget.id);
      setEntries((prev) => prev.filter((en) => en.id !== deleteTarget.id));
      toast.success("Запись удалена");
      setDeleteTarget(null);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setDeleting(false);
    }
  };

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const ext = "." + file.name.split(".").pop().toLowerCase();
    if (!ACCEPTED.includes(ext)) {
      toast.error(`Формат ${ext} не поддерживается. Допустимые форматы: ${ACCEPTED.join(", ")}`);
      return;
    }
    setUploading(true);
    try {
      const summary = await api.uploadNomenclatureFile(file);
      toast.success(
        `Загружено: ${summary.rows_parsed} строк — новых ${summary.created}, обновлено ${summary.updated}`
      );
      load();
    } catch (e2) {
      toast.error(e2.message);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Номенклатура/остатки</h2>
          <p>
            Внутренний склад заказчика — код, № кат., производитель, остаток, резерв, склад. Используется
            для автозаполнения этих полей в заказ-нарядах (см. ReviewMatches). Источник — либо
            периодическая выгрузка файлом отсюда, либо (когда будет подтверждён) прямой API — см.
            «Интеграции».
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <label className="btn btn-secondary" style={{ cursor: uploading ? "default" : "pointer" }}>
            <UploadIcon /> {uploading ? "Загрузка…" : "Загрузить файл"}
            <input
              type="file"
              accept={ACCEPTED.join(",")}
              onChange={handleUpload}
              disabled={uploading}
              style={{ display: "none" }}
            />
          </label>
          <button className="btn btn-primary" onClick={() => setShowForm((v) => !v)}>
            <PlusIcon /> Добавить вручную
          </button>
        </div>
      </div>

      <form className="field-row" style={{ marginBottom: 16, maxWidth: 420 }} onSubmit={handleSearch}>
        <div className="field" style={{ flex: 1 }}>
          <input
            placeholder="Поиск по коду, № кат. или названию"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <button className="btn btn-secondary" type="submit">
          <SearchIcon /> Найти
        </button>
      </form>

      {showForm && (
        <form className="panel" style={{ marginBottom: 20, maxWidth: 560 }} onSubmit={handleCreate}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div className="field">
              <label htmlFor="name">Наименование</label>
              <input
                id="name"
                required
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="code">Код</label>
              <input id="code" value={form.code} onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))} />
            </div>
            <div className="field">
              <label htmlFor="cat_number">№ кат.</label>
              <input
                id="cat_number"
                value={form.cat_number}
                onChange={(e) => setForm((f) => ({ ...f, cat_number: e.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="manufacturer">Производитель</label>
              <input
                id="manufacturer"
                value={form.manufacturer}
                onChange={(e) => setForm((f) => ({ ...f, manufacturer: e.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="unit">Единица</label>
              <input id="unit" value={form.unit} onChange={(e) => setForm((f) => ({ ...f, unit: e.target.value }))} />
            </div>
            <div className="field">
              <label htmlFor="warehouse">Склад</label>
              <input
                id="warehouse"
                value={form.warehouse}
                onChange={(e) => setForm((f) => ({ ...f, warehouse: e.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="stock_qty">Остаток</label>
              <input
                id="stock_qty"
                type="number"
                step="0.01"
                value={form.stock_qty}
                onChange={(e) => setForm((f) => ({ ...f, stock_qty: e.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="reserved_qty">В резерве</label>
              <input
                id="reserved_qty"
                type="number"
                step="0.01"
                value={form.reserved_qty}
                onChange={(e) => setForm((f) => ({ ...f, reserved_qty: e.target.value }))}
              />
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
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
      ) : entries.length === 0 ? (
        <div className="table-wrap">
          <EmptyState
            title="Номенклатура пуста"
            hint="Загрузите файл выгрузки или добавьте записи вручную."
          />
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Код</th>
                <th>№ кат.</th>
                <th>Наименование</th>
                <th>Производитель</th>
                <th>Ед.</th>
                <th>Остаток</th>
                <th>В резерве</th>
                <th>Склад</th>
                <th>Источник</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {entries.map((en) => (
                <tr key={en.id}>
                  <td>{en.code || "—"}</td>
                  <td className="text-muted">{en.cat_number || "—"}</td>
                  <td>{en.name}</td>
                  <td className="text-muted">{en.manufacturer || "—"}</td>
                  <td className="text-muted">{en.unit || "—"}</td>
                  <td>{en.stock_qty ?? "—"}</td>
                  <td>{en.reserved_qty ?? "—"}</td>
                  <td className="text-muted">{en.warehouse || "—"}</td>
                  <td className="text-muted">{en.source}</td>
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
          <Pagination page={page} perPage={PER_PAGE} total={total} onPageChange={handlePageChange} />
        </div>
      )}

      {deleteTarget && (
        <ConfirmDialog
          title="Удалить запись?"
          message={
            <>
              Запись <strong>{deleteTarget.name}</strong> будет удалена из номенклатуры.
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
