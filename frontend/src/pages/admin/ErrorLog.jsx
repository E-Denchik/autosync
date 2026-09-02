import { useEffect, useState } from "react";
import { useErrorLog } from "../../context/ErrorLogContext.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import HowToUse from "../../components/HowToUse.jsx";
import ConfirmDialog from "../../components/ConfirmDialog.jsx";
import { AlertCircleIcon, CopyIcon } from "../../components/icons.jsx";

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

const SOURCE_LABELS = {
  "react-render": "Ошибка отрисовки страницы",
  "window.onerror": "Необработанная ошибка в браузере",
  unhandledrejection: "Необработанный сбой асинхронной операции",
};

function formatEntry(e) {
  const prefix = `[${new Date(e.time).toLocaleString("ru-RU")}]${e.source ? ` (${SOURCE_LABELS[e.source] || e.source})` : ""}`;
  return `${prefix} ${e.message}`;
}

export default function ErrorLog() {
  const { entries, clear, markViewed } = useErrorLog();
  const [confirmClear, setConfirmClear] = useState(false);
  const toast = useToast();

  useEffect(() => {
    markViewed();
  }, [markViewed]);

  const handleCopyAll = () => {
    copyToClipboard(entries.map(formatEntry).join("\n\n")).then(() =>
      toast.success("Журнал скопирован в буфер обмена")
    );
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Журнал ошибок</h2>
          <p>
            Всё, что пошло не так в интерфейсе: сбои запросов к серверу (в том числе при загрузке
            и сопоставлении заказ-нарядов) и необработанные сбои страниц. В отличие от всплывающего
            уведомления, запись здесь остаётся насовсем — можно спокойно прочитать целиком и
            скопировать, даже если сама ошибка давно исчезла с экрана.
          </p>
        </div>
        {entries.length > 0 && (
          <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
            <button className="btn btn-secondary" onClick={handleCopyAll}>
              <CopyIcon /> Скопировать всё
            </button>
            <button className="btn btn-secondary" onClick={() => setConfirmClear(true)}>
              Очистить журнал
            </button>
          </div>
        )}
      </div>

      <HowToUse
        steps={[
          "Журнал хранится в этом окне приложения и переживает перезапуск — записи никуда не отправляются.",
          "Если при загрузке и сопоставлении файлов (или в любом другом разделе) выскочила ошибка и сразу пропала — полный текст останется здесь.",
          "«Скопировать всё» удобно, если нужно переслать текст ошибки для разбора проблемы.",
        ]}
      />

      {entries.length === 0 ? (
        <div className="table-wrap">
          <EmptyState
            icon={AlertCircleIcon}
            title="Ошибок пока не было"
            hint="Это хорошо — здесь появится всё, что пойдёт не так."
          />
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {entries.map((e) => (
            <div className="panel" key={e.id} style={{ padding: "12px 14px" }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 10,
                  marginBottom: 6,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span className="text-muted" style={{ fontSize: 12 }}>
                    {new Date(e.time).toLocaleString("ru-RU")}
                  </span>
                  {e.source && (
                    <span className="status-pill status-rejected">{SOURCE_LABELS[e.source] || e.source}</span>
                  )}
                </div>
                <button
                  className="btn btn-secondary btn-sm"
                  title="Скопировать текст ошибки"
                  onClick={() => copyToClipboard(formatEntry(e)).then(() => toast.success("Скопировано"))}
                >
                  <CopyIcon style={{ width: 13, height: 13 }} />
                </button>
              </div>
              <div style={{ fontSize: 13, whiteSpace: "pre-wrap", wordBreak: "break-word", userSelect: "text" }}>
                {e.message}
              </div>
            </div>
          ))}
        </div>
      )}

      {confirmClear && (
        <ConfirmDialog
          title="Очистить журнал ошибок?"
          message="Все записи будут удалены без возможности восстановить."
          confirmLabel="Очистить"
          danger
          onConfirm={() => {
            clear();
            setConfirmClear(false);
          }}
          onCancel={() => setConfirmClear(false)}
        />
      )}
    </div>
  );
}
