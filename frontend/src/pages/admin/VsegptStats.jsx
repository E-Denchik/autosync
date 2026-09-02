import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import { RefreshIcon } from "../../components/icons.jsx";
import { useToast } from "../../context/ToastContext.jsx";

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

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Статистика vsegpt.ru</h2>
          <p>Баланс аккаунта, лимиты и статистика запросов через AutoSync.</p>
        </div>
        <button className="btn btn-secondary" onClick={load} disabled={loading}>
          <RefreshIcon /> {loading ? "Обновление…" : "Обновить"}
        </button>
      </div>

      {!status.configured ? (
        <div className="panel">API-ключ vsegpt.ru не настроен. Добавьте его в разделе «LLM-модель».</div>
      ) : !status.available ? (
        <div className="panel">
          <strong>Статистика временно недоступна</strong>
          <p className="text-muted">{status.error || "Проверьте API-ключ и соединение с vsegpt.ru."}</p>
        </div>
      ) : (
        <div className="panel">
          <div className="llm-stats-grid">
            <div><strong>Баланс</strong><br />{status.balance ?? "—"} {status.currency || ""}</div>
            <div><strong>Потрачено</strong><br />{status.spent ?? "—"} {status.currency || ""}</div>
            <div><strong>Запросов через AutoSync</strong><br />{status.local_requests ?? 0}</div>
            <div><strong>Успешных запросов</strong><br />{status.local_successes ?? 0}</div>
            <div><strong>Ошибок запросов</strong><br />{status.local_errors ?? 0}</div>
            <div><strong>Запросов по данным vsegpt</strong><br />{status.requests_made ?? "—"}</div>
            <div><strong>Осталось запросов</strong><br />{status.requests_remaining ?? "—"}</div>
          </div>
          <p className="text-muted" style={{ marginBottom: 0 }}>
            Если баланс равен или меньше нуля, модели vsegpt.ru отображаются, но их нельзя выбрать до пополнения счёта.
          </p>
        </div>
      )}
    </div>
  );
}
