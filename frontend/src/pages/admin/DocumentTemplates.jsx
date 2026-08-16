import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import ConfirmDialog from "../../components/ConfirmDialog.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { PlusIcon, DownloadIcon } from "../../components/icons.jsx";

const TOKENS = [
  ["{{order_number}}, {{order_date}}", "номер и дата заказ-наряда"],
  ["{{client_name}}", "заказчик"],
  ["{{vehicle_make}}, {{vehicle_model}}, {{vehicle_vin}}, {{vehicle_year}}", "автомобиль"],
  ["{{company_name}}, {{company_inn}}, {{company_address}}, {{company_phone}}", "реквизиты (Администрирование → Реквизиты)"],
  ["{{parts_total}}, {{labor_total}}, {{grand_total}}", "итоговые суммы"],
  ["{{part.article}}, {{part.name}}, {{part.price}}, {{part.cat_number}}, {{part.manufacturer}}, {{part.unit}}, {{part.warehouse}}", "строка запчасти — повторяется на каждую позицию"],
  ["{{labor.description}}, {{labor.norm_hours}}, {{labor.hourly_rate}}, {{labor.total}}", "строка работы — повторяется на каждую операцию"],
];

export default function DocumentTemplates() {
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const toast = useToast();

  const load = () => {
    setLoading(true);
    api
      .listDocumentTemplates()
      .then(setTemplates)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDownloadStarter = async () => {
    try {
      const blob = await api.downloadStarterTemplate();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "autosync-starter-shablon.xlsx";
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(e.message);
    }
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!file) {
      toast.error("Выберите файл .xlsx");
      return;
    }
    setUploading(true);
    try {
      await api.uploadDocumentTemplate(name, file);
      toast.success("Шаблон загружен");
      setName("");
      setFile(null);
      e.target.reset();
      load();
    } catch (e2) {
      toast.error(e2.message);
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await api.deleteDocumentTemplate(deleteTarget.id);
      setTemplates((prev) => prev.filter((t) => t.id !== deleteTarget.id));
      toast.success("Шаблон удалён");
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
          <h2>Шаблоны документов</h2>
          <p>
            Excel-файлы с плейсхолдерами вида {"{{order_number}}"}, которые AutoSync заполняет реальными
            данными заказ-наряда при генерации документа для клиента. Без загруженного шаблона используется
            встроенный формат (как у 1С).
          </p>
        </div>
        <button className="btn btn-secondary" onClick={handleDownloadStarter}>
          <DownloadIcon /> Скачать стартовый шаблон
        </button>
      </div>

      <div className="panel" style={{ marginBottom: 20 }}>
        <h3 style={{ marginTop: 0 }}>Доступные плейсхолдеры</h3>
        <table>
          <tbody>
            {TOKENS.map(([tokens, hint]) => (
              <tr key={tokens}>
                <td style={{ fontFamily: "monospace", fontSize: 12.5, whiteSpace: "nowrap" }}>{tokens}</td>
                <td className="text-muted">{hint}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <form className="panel" style={{ marginBottom: 20, maxWidth: 520 }} onSubmit={handleUpload}>
        <h3 style={{ marginTop: 0 }}>Загрузить шаблон</h3>
        <div className="field">
          <label htmlFor="tpl-name">Название</label>
          <input
            id="tpl-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Например, Акт выполненных работ"
          />
        </div>
        <div className="field">
          <label htmlFor="tpl-file">Файл (.xlsx)</label>
          <input id="tpl-file" type="file" accept=".xlsx,.xlsm" onChange={(e) => setFile(e.target.files[0])} />
        </div>
        <button className="btn btn-primary" disabled={uploading} type="submit">
          <PlusIcon /> {uploading ? "Загрузка…" : "Загрузить"}
        </button>
      </form>

      {loading ? (
        <Spinner label="Загрузка…" />
      ) : templates.length === 0 ? (
        <div className="table-wrap">
          <EmptyState title="Шаблонов пока нет" hint="Загрузите свой или скачайте стартовый шаблон выше." />
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Название</th>
                <th>Файл</th>
                <th>Добавлен</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {templates.map((t) => (
                <tr key={t.id}>
                  <td>{t.name}</td>
                  <td className="text-muted">{t.original_filename}</td>
                  <td className="text-muted">{new Date(t.created_at).toLocaleDateString("ru-RU")}</td>
                  <td>
                    <div style={{ display: "flex", justifyContent: "flex-end" }}>
                      <button className="btn btn-reject btn-sm" onClick={() => setDeleteTarget(t)}>
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
          title="Удалить шаблон?"
          message={
            <>
              Шаблон <strong>{deleteTarget.name}</strong> будет удалён безвозвратно.
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
