import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import { RefreshIcon, AlertCircleIcon, CheckCircleIcon } from "../../components/icons.jsx";
import { useToast } from "../../context/ToastContext.jsx";

// 0/1/2 — тот же светофор, что показан в личном кабинете vsegpt.ru (см.
// llm-service/server.py: get_vsegpt_status). Переиспользуем цвета
// status-pill, которые уже значат ровно это же во всём приложении
// (approved/pending/rejected), а не заводим отдельную палитру для одной
// страницы.
const USER_STATUS_TONE = { 0: "approved", 1: "pending", 2: "rejected" };

function formatDateTime(value) {
  if (!value) return null;
  // "2024-05-02 00:08:02" — формат vsegpt.ru, не ISO 8601 (без "T"), но
  // большинство движков (в т.ч. тот, что использует pywebview) парсят его
  // как локальное время и без замены пробела на "T" — на случай, если
  // конкретный WebView всё же не осилит, просто показываем исходную строку.
  const parsed = new Date(value.replace(" ", "T"));
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("ru-RU", { dateStyle: "medium", timeStyle: "short" });
}

export default function VsegptStats() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  const load = () => {
    setLoading(true);
    api
      .vsegptStatus()
      .then((response) => setStatus(response.status))
      .catch((error) => toast.error(error.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading && !status) return <Spinner label="Загружаем статистику vsegpt.ru…" />;
  if (!status) return null;

  const statusTone = USER_STATUS_TONE[status.user_status] ?? null;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Статистика vsegpt.ru</h2>
          <p>Те же данные аккаунта, что в личном кабинете vsegpt.ru, плюс статистика запросов через AutoSync.</p>
        </div>
        <button className="btn btn-secondary" onClick={load} disabled={loading}>
          <RefreshIcon /> {loading ? "Обновление…" : "Обновить"}
        </button>
      </div>

      {!status.configured ? (
        <div className="panel">API-ключ vsegpt.ru не настроен. Добавьте его в разделе «LLM-модель».</div>
      ) : !status.available ? (
        <div className="panel">
          <div className="hint-banner hint-warning">
            <AlertCircleIcon />
            <span>{status.error || "Не удалось получить статистику аккаунта — проверьте API-ключ и соединение с vsegpt.ru."}</span>
          </div>
        </div>
      ) : (
        <>
          <div className="panel" style={{ marginBottom: 16 }}>
            <h3 style={{ marginTop: 0 }}>Аккаунт vsegpt.ru</h3>
            <div className="llm-stats-grid">
              <div>
                <strong>Баланс</strong>
                <br />
                {status.balance != null ? `${status.balance} кредитов` : "—"}
              </div>
              <div>
                <strong>Состояние аккаунта</strong>
                <br />
                {statusTone ? (
                  <span className={`status-pill status-${statusTone}`}>
                    {statusTone === "approved" ? "в порядке" : statusTone === "pending" ? "предупреждение" : "критично"}
                  </span>
                ) : (
                  "—"
                )}
              </div>
              {status.subscription_status && (
                <div>
                  <strong>Подписка</strong>
                  <br />
                  {status.subscription_status}
                </div>
              )}
              {status.subscription_end && (
                <div>
                  <strong>Подписка действует до</strong>
                  <br />
                  {formatDateTime(status.subscription_end)}
                </div>
              )}
            </div>
            {status.user_status_text && (
              <div className={`hint-banner ${statusTone === "rejected" ? "hint-danger" : statusTone === "pending" ? "hint-warning" : ""}`} style={{ marginTop: 4, marginBottom: 0 }}>
                {statusTone === "approved" ? <CheckCircleIcon /> : <AlertCircleIcon />}
                <span>{status.user_status_text}</span>
              </div>
            )}
          </div>

          <div className="panel">
            <h3 style={{ marginTop: 0 }}>Использование через AutoSync</h3>
            <p className="text-muted" style={{ marginTop: -4, fontSize: 12 }}>
              Считается локально этим приложением (с момента последнего запуска), а не запрашивается с vsegpt.ru —
              там таких данных по API нет.
            </p>
            <div className="llm-stats-grid">
              <div><strong>Запросов</strong><br />{status.local_requests ?? 0}</div>
              <div><strong>Успешных</strong><br />{status.local_successes ?? 0}</div>
              <div><strong>Ошибок</strong><br />{status.local_errors ?? 0}</div>
            </div>
          </div>

          <p className="text-muted" style={{ marginTop: 16, marginBottom: 0 }}>
            Если баланс равен нулю или меньше, модели vsegpt.ru отображаются, но их нельзя выбрать до пополнения счёта.
          </p>
        </>
      )}
    </div>
  );
}
