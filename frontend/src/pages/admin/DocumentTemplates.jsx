import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import ConfirmDialog from "../../components/ConfirmDialog.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import FilePreviewModal from "../../components/FilePreviewModal.jsx";
import HowToUse from "../../components/HowToUse.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { PlusIcon, DownloadIcon, EyeIcon, CopyIcon } from "../../components/icons.jsx";
import { saveFile, XLSX_FILE_TYPES } from "../../utils/saveFile.js";

const TOKEN_GROUPS = [
  { hint: "номер и дата заказ-наряда", tokens: ["{{order_number}}", "{{order_date}}"] },
  { hint: "заказчик", tokens: ["{{client_name}}"] },
  { hint: "автомобиль", tokens: ["{{vehicle_make}}", "{{vehicle_model}}", "{{vehicle_vin}}", "{{vehicle_year}}"] },
  {
    hint: "реквизиты (Администрирование → Реквизиты)",
    tokens: ["{{company_name}}", "{{company_inn}}", "{{company_address}}", "{{company_phone}}"],
  },
  { hint: "итоговые суммы", tokens: ["{{parts_total}}", "{{labor_total}}", "{{grand_total}}"] },
  {
    hint: "строка запчасти — повторяется на каждую позицию",
    tokens: [
      "{{part.article}}",
      "{{part.name}}",
      "{{part.price}}",
      "{{part.cat_number}}",
      "{{part.manufacturer}}",
      "{{part.unit}}",
      "{{part.warehouse}}",
    ],
  },
  {
    hint: "строка работы — повторяется на каждую операцию",
    tokens: ["{{labor.description}}", "{{labor.norm_hours}}", "{{labor.hourly_rate}}", "{{labor.total}}"],
  },
];

function copyToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text);
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
  return Promise.resolve();
}

function TokenChip({ token, onCopied }) {
  return (
    <button
      type="button"
      className="token-chip"
      onClick={() => copyToClipboard(token).then(onCopied)}
      title="Скопировать"
    >
      {token}
      <CopyIcon />
    </button>
  );
}

export default function DocumentTemplates() {
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [downloadingStarter, setDownloadingStarter] = useState(false);
  const [previewTarget, setPreviewTarget] = useState(null);
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
    setDownloadingStarter(true);
    try {
      const blob = await api.downloadStarterTemplate();
      const result = await saveFile(blob, "autosync-starter-shablon.xlsx", XLSX_FILE_TYPES);
      if (result.ok) {
        toast.success(result.native ? `Стартовый шаблон сохранён: ${result.path}` : "Стартовый шаблон скачан");
      } else if (!result.canceled) {
        toast.error(result.error || "Не удалось сохранить файл");
      }
    } catch (e) {
      toast.error(e.message);
    } finally {
      setDownloadingStarter(false);
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

  const handlePreview = (template) => {
    setPreviewTarget({
      fileName: template.original_filename,
      loader: () => api.previewRenderedTemplate({ templateId: template.id }),
    });
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
        <button className="btn btn-secondary" disabled={downloadingStarter} onClick={handleDownloadStarter}>
          <DownloadIcon /> {downloadingStarter ? "Скачивание…" : "Скачать стартовый шаблон"}
        </button>
      </div>

      <HowToUse
        steps={[
          "Скачайте «Стартовый шаблон», отредактируйте нужные ячейки в Excel и загрузите обратно — или используйте свой готовый файл с плейсхолдерами.",
          "Нажмите на нужный плейсхолдер в списке ниже, чтобы скопировать его, и вставьте в ячейку шаблона.",
          "Перед загрузкой нажмите «Просмотреть перед загрузкой» — вы увидите, как реальные данные подставятся вместо плейсхолдеров, и сразу заметите, если что-то написано неверно.",
          "Без загруженного шаблона документ формируется во встроенном формате — свой шаблон не обязателен.",
        ]}
      />

      <div className="panel" style={{ marginBottom: 20 }}>
        <h3 style={{ marginTop: 0 }}>Доступные плейсхолдеры</h3>
        <p className="text-muted" style={{ fontSize: 12.5, marginTop: -6, marginBottom: 14 }}>
          Нажмите на плейсхолдер, чтобы скопировать его — вставьте в нужную ячейку шаблона.
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {TOKEN_GROUPS.map((group) => (
            <div key={group.hint} style={{ minWidth: 0 }}>
              <div className="text-muted" style={{ fontSize: 12.5, marginBottom: 6 }}>
                {group.hint}
              </div>
              <div className="token-chip-list">
                {group.tokens.map((token) => (
                  <TokenChip key={token} token={token} onCopied={() => toast.success(`Скопировано: ${token}`)} />
                ))}
              </div>
            </div>
          ))}
        </div>
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
          {file && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              style={{ marginTop: 8, alignSelf: "flex-start" }}
              onClick={() => setPreviewTarget({ fileName: file.name, loader: () => api.previewRenderedTemplate({ file }) })}
            >
              <EyeIcon style={{ width: 13, height: 13 }} /> Просмотреть перед загрузкой
            </button>
          )}
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
                    <div style={{ display: "flex", justifyContent: "flex-end", gap: 6 }}>
                      <button className="btn btn-secondary btn-sm" onClick={() => handlePreview(t)}>
                        <EyeIcon style={{ width: 13, height: 13 }} /> Просмотр
                      </button>
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

      {previewTarget && (
        <FilePreviewModal
          fileName={previewTarget.fileName}
          loader={previewTarget.loader}
          subtitle="Показаны реальные данные последнего заказ-наряда — не сырые {{плейсхолдеры}}."
          onClose={() => setPreviewTarget(null)}
        />
      )}
    </div>
  );
}
