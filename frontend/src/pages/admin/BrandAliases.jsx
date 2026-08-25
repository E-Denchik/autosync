import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import ConfirmDialog from "../../components/ConfirmDialog.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import Pagination from "../../components/Pagination.jsx";
import HowToUse from "../../components/HowToUse.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { PlusIcon, UploadIcon, SearchIcon, SparklesIcon } from "../../components/icons.jsx";

const PER_PAGE = 50;
const EMPTY_FORM = { alias: "", canonical_make: "" };
const ACCEPTED = [".xlsx", ".xlsm", ".xls", ".ods", ".csv"];

const SOURCE_LABELS = {
  builtin: "встроенный",
  manual: "вручную",
  upload: "файлом",
  llm: "ИИ",
};

export default function BrandAliases() {
  const [entries, setEntries] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [onlyUnresolved, setOnlyUnresolved] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [normalizing, setNormalizing] = useState(false);
  const toast = useToast();

  const load = (q = query, p = page, unresolved = onlyUnresolved) => {
    setLoading(true);
    api
      .listBrandAliases(q, { page: p, per_page: PER_PAGE, ...(unresolved ? { unresolved: 1 } : {}) })
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

  const toggleUnresolved = () => {
    const next = !onlyUnresolved;
    setOnlyUnresolved(next);
    setPage(1);
    load(query, 1, next);
  };

  const handlePageChange = (p) => {
    setPage(p);
    load(query, p);
  };

  const startEdit = (entry) => {
    setEditingId(entry.id);
    setForm({ alias: entry.alias, canonical_make: entry.canonical_make || "" });
    setShowForm(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (editingId) {
        await api.updateBrandAlias(editingId, form);
        toast.success("Запись обновлена");
      } else {
        await api.createBrandAlias(form);
        toast.success("Марка добавлена");
      }
      setForm(EMPTY_FORM);
      setShowForm(false);
      setEditingId(null);
      load();
    } catch (e2) {
      toast.error(e2.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await api.deleteBrandAlias(deleteTarget.id);
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
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    if (files.length === 0) return;

    const valid = [];
    for (const file of files) {
      const ext = "." + file.name.split(".").pop().toLowerCase();
      if (!ACCEPTED.includes(ext)) {
        toast.error(`Формат ${ext} не поддерживается. Допустимые форматы: ${ACCEPTED.join(", ")}`);
        continue;
      }
      valid.push(file);
    }
    if (valid.length === 0) return;

    setUploading(true);
    try {
      const summary = await api.uploadBrandAliasesFile(valid);
      toast.success(`Загружено: новых ${summary.created}, обновлено ${summary.updated}`);
      if (summary.errors?.length) summary.errors.forEach((msg) => toast.error(msg));
      load();
    } catch (e2) {
      toast.error(e2.message);
    } finally {
      setUploading(false);
    }
  };

  const handleNormalize = async () => {
    setNormalizing(true);
    try {
      const result = await api.normalizeBrandAliases();
      if (result.total === 0) {
        toast.success("Нечего проверять — все марки уже распознаны");
      } else {
        toast.success(`ИИ распознала ${result.normalized} из ${result.total}`);
      }
      load();
    } catch (e2) {
      toast.error(e2.message);
    } finally {
      setNormalizing(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Марки автомобилей</h2>
          <p>
            Справочник "как марка написана у поставщика → как она называется в заказ-наряде"
            (кириллица/опечатки/сокращения → латиница). Используется при сопоставлении запчастей по
            каталогу — без этого «Шевроле» и «CHEVROLET» никогда не совпали бы как одна марка.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <label className="btn btn-secondary" style={{ cursor: uploading ? "default" : "pointer" }}>
            <UploadIcon /> {uploading ? "Загрузка…" : "Загрузить файлом"}
            <input
              type="file"
              multiple
              accept={ACCEPTED.join(",")}
              onChange={handleUpload}
              disabled={uploading}
              style={{ display: "none" }}
            />
          </label>
          <button className="btn btn-secondary" disabled={normalizing} onClick={handleNormalize}>
            <SparklesIcon /> {normalizing ? "Проверка…" : "Проверить через ИИ"}
          </button>
          <button
            className="btn btn-primary"
            onClick={() => {
              setEditingId(null);
              setForm(EMPTY_FORM);
              setShowForm((v) => !v);
            }}
          >
            <PlusIcon /> Добавить вручную
          </button>
        </div>
      </div>

      <HowToUse
        steps={[
          "Каждая запись — соответствие одного написания марки (как оно встречается у поставщика) каноничному названию латиницей (как в заказ-наряде).",
          "Загрузите файл с двумя колонками (марка / каноничное название) — вторую колонку можно оставить пустой.",
          "«Проверить через ИИ» дозаполнит каноничное название для записей без него — тем же способом, каким это уже делается автоматически при загрузке договора с нераспознанными марками.",
          "Справочник пополняется и сам — при импорте договора нераспознанные марки, которые смогла определить ИИ, сохраняются сюда автоматически.",
        ]}
      />

      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
        <form className="field-row" style={{ maxWidth: 420 }} onSubmit={handleSearch}>
          <div className="field" style={{ flex: 1 }}>
            <input
              placeholder="Поиск по марке"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <button className="btn btn-secondary" type="submit">
            <SearchIcon /> Найти
          </button>
        </form>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
          <input type="checkbox" checked={onlyUnresolved} onChange={toggleUnresolved} />
          Только без каноничного названия
        </label>
      </div>

      {showForm && (
        <form className="panel" style={{ marginBottom: 20, maxWidth: 560 }} onSubmit={handleSubmit}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div className="field">
              <label htmlFor="alias">Марка как у поставщика</label>
              <input
                id="alias"
                required
                placeholder="например, Шевроле"
                value={form.alias}
                onChange={(e) => setForm((f) => ({ ...f, alias: e.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="canonical_make">Каноничное название</label>
              <input
                id="canonical_make"
                placeholder="например, CHEVROLET (можно оставить пустым)"
                value={form.canonical_make}
                onChange={(e) => setForm((f) => ({ ...f, canonical_make: e.target.value }))}
              />
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
            <button className="btn btn-primary" disabled={saving} type="submit">
              {saving ? "Сохранение…" : editingId ? "Сохранить" : "Добавить"}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                setShowForm(false);
                setEditingId(null);
                setForm(EMPTY_FORM);
              }}
            >
              Отмена
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <Spinner label="Загружаем справочник…" />
      ) : entries.length === 0 ? (
        <div className="table-wrap">
          <EmptyState
            title="Справочник пуст"
            hint="Загрузите файл или добавьте марку вручную."
          />
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Марка у поставщика</th>
                <th>Каноничное название</th>
                <th>Источник</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {entries.map((en) => (
                <tr key={en.id}>
                  <td>{en.alias}</td>
                  <td>
                    {en.canonical_make || (
                      <span className="text-muted" title="Ещё не определено — «Проверить через ИИ» или впишите вручную">
                        не определено
                      </span>
                    )}
                  </td>
                  <td className="text-muted">{SOURCE_LABELS[en.source] || en.source}</td>
                  <td>
                    <div style={{ display: "flex", justifyContent: "flex-end", gap: 6 }}>
                      <button className="btn btn-secondary btn-sm" onClick={() => startEdit(en)}>
                        Изменить
                      </button>
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
              Марка <strong>{deleteTarget.alias}</strong> будет удалена из справочника.
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
