import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { RefreshIcon } from "../../components/icons.jsx";

export default function Integrations() {
  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(null); // id интеграции в процессе проверки
  const [results, setResults] = useState({}); // id -> {ok, message}
  const toast = useToast();

  const load = () => {
    setLoading(true);
    api
      .listIntegrations()
      .then(setIntegrations)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleTest = async (id) => {
    setTesting(id);
    setResults((r) => ({ ...r, [id]: null }));
    try {
      const res = await api.testIntegration(id);
      setResults((r) => ({ ...r, [id]: res }));
      if (!res.ok) toast.error(res.message);
    } catch (e) {
      setResults((r) => ({ ...r, [id]: { ok: false, message: e.message } }));
      toast.error(e.message);
    } finally {
      setTesting(null);
    }
  };

  if (loading) return <Spinner label="Загрузка интеграций…" />;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Интеграции</h2>
          <p>
            Внешние API, которые использует AutoSync: Ozon Seller/Performance и сторонний сервис
            аналитики цен конкурентов. Ключи задаются переменными окружения на сервере — здесь
            видно только статус подключения, сами значения не отображаются.
          </p>
        </div>
        <button className="btn btn-secondary" onClick={load}>
          <RefreshIcon /> Обновить
        </button>
      </div>

      {integrations.map((it) => {
        const result = results[it.id];
        return (
          <div className="panel" key={it.id} style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                  <h3 style={{ margin: 0 }}>{it.name}</h3>
                  {it.configured ? (
                    <span className="status-pill status-approved">настроено</span>
                  ) : (
                    <span className="status-pill status-pending">не настроено</span>
                  )}
                </div>
                <p className="text-muted" style={{ margin: 0 }}>
                  {it.description}
                </p>
              </div>
              <button
                className="btn btn-secondary btn-sm"
                disabled={testing === it.id}
                onClick={() => handleTest(it.id)}
              >
                {testing === it.id ? "Проверяем…" : "Проверить подключение"}
              </button>
            </div>

            {result && (
              <div
                style={{
                  marginTop: 12,
                  fontSize: 13,
                  color: result.ok ? "var(--success-text)" : "var(--danger-text)",
                }}
              >
                {result.message}
              </div>
            )}

            {!it.configured && (
              <p className="text-muted" style={{ marginTop: 12, marginBottom: 0, fontSize: 12 }}>
                Задайте соответствующие переменные окружения на сервере (см. .env.example) и
                перезапустите приложение.
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
