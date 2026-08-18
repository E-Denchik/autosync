import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import HowToUse from "../../components/HowToUse.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { RefreshIcon, AlertCircleIcon } from "../../components/icons.jsx";

const KEY_FIELDS = {
  ozon_seller: [
    { key: "OZON_CLIENT_ID", label: "Client-Id", type: "text", placeholder: "12345" },
    { key: "OZON_API_KEY", label: "Api-Key", type: "password", placeholder: "" },
  ],
  ozon_performance: [
    { key: "OZON_PERFORMANCE_CLIENT_ID", label: "Client-Id (Performance)", type: "text", placeholder: "" },
    { key: "OZON_PERFORMANCE_CLIENT_SECRET", label: "Client Secret", type: "password", placeholder: "" },
  ],
  analytics: [
    { key: "ANALYTICS_PROVIDER_BASE_URL", label: "Base URL", type: "text", placeholder: "https://api.provider.ru" },
    { key: "ANALYTICS_PROVIDER_API_KEY", label: "API Key", type: "password", placeholder: "" },
  ],
  alfaauto: [
    {
      key: "ALFAAUTO_BASE_URL",
      label: "Адрес OData",
      type: "text",
      placeholder: "http://server/base/odata/standard.odata",
    },
    { key: "ALFAAUTO_LOGIN", label: "Логин пользователя 1С", type: "text", placeholder: "" },
    { key: "ALFAAUTO_PASSWORD", label: "Пароль", type: "password", placeholder: "" },
  ],
};

export default function Integrations() {
  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(null); // id интеграции в процессе проверки
  const [results, setResults] = useState({}); // id -> {ok, message}
  const [editingId, setEditingId] = useState(null); // какая карточка сейчас с открытой формой ключей
  const [formValues, setFormValues] = useState({}); // key -> значение поля формы
  const [saving, setSaving] = useState(false);
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

  const openEdit = (id) => {
    setEditingId(id);
    setFormValues({});
  };

  const handleSaveKeys = async (id) => {
    const fields = KEY_FIELDS[id];
    const payload = {};
    fields.forEach(({ key }) => {
      if (formValues[key]) payload[key] = formValues[key];
    });
    if (Object.keys(payload).length === 0) {
      toast.error("Заполните хотя бы одно поле");
      return;
    }
    setSaving(true);
    try {
      await api.saveIntegrationKeys(payload);
      toast.success("Ключи сохранены — применены сразу, перезапуск не нужен");
      setEditingId(null);
      setFormValues({});
      load();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Spinner label="Загрузка интеграций…" />;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Интеграции</h2>
          <p>
            Внешние API, которые использует AutoSync: Ozon Seller/Performance, сторонний сервис
            аналитики цен конкурентов и 1С:Альфа-Авто (номенклатура/остатки и нормо-часы).
            Ключи вводятся здесь и сохраняются в базе данных — переживают перезапуск, значения
            обратно не показываются.
          </p>
        </div>
        <button className="btn btn-secondary" onClick={load}>
          <RefreshIcon /> Обновить
        </button>
      </div>

      <HowToUse
        steps={[
          "Нажмите «Задать ключи» у нужного сервиса (Ozon, аналитика цен конкурентов, 1С:Альфа-Авто), впишите значения и сохраните.",
          "«Проверить подключение» сразу скажет, работают ли введённые ключи, не дожидаясь реального использования в других разделах.",
          "Ключи сохраняются в базе и применяются сразу — перезапуск приложения не требуется; после сохранения значения обратно не показываются.",
        ]}
      />

      {integrations.map((it) => {
        const result = results[it.id];
        const isEditing = editingId === it.id;
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
              <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => (isEditing ? setEditingId(null) : openEdit(it.id))}
                >
                  {isEditing ? "Отмена" : it.configured ? "Изменить ключи" : "Задать ключи"}
                </button>
                <button
                  className="btn btn-secondary btn-sm"
                  disabled={testing === it.id}
                  onClick={() => handleTest(it.id)}
                >
                  {testing === it.id ? "Проверяем…" : "Проверить подключение"}
                </button>
              </div>
            </div>

            {it.api_base_override && (
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 8,
                  marginTop: 12,
                  padding: "8px 12px",
                  borderRadius: "var(--radius-sm)",
                  background: "var(--warning-soft)",
                  color: "var(--warning)",
                  fontSize: 12.5,
                }}
              >
                <AlertCircleIcon style={{ width: 15, height: 15, flexShrink: 0, marginTop: 1 }} />
                <span>
                  Адрес API переопределён на <code>{it.api_base_override}</code> (переменная окружения на
                  сервере) — реальные ключи работать не будут, пока она задана. Уберите её (unset) и
                  перезапустите приложение, чтобы использовать настоящий Ozon.
                </span>
              </div>
            )}

            {isEditing && (
              <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
                <div className="field-row">
                  {KEY_FIELDS[it.id].map((f) => (
                    <div className="field" key={f.key}>
                      <label htmlFor={f.key}>{f.label}</label>
                      <input
                        id={f.key}
                        type={f.type}
                        autoComplete="off"
                        value={formValues[f.key] || ""}
                        onChange={(e) => setFormValues((v) => ({ ...v, [f.key]: e.target.value }))}
                        placeholder={f.placeholder}
                      />
                    </div>
                  ))}
                </div>
                <button
                  className="btn btn-primary btn-sm"
                  disabled={saving}
                  onClick={() => handleSaveKeys(it.id)}
                >
                  {saving ? "Сохранение…" : "Сохранить"}
                </button>
              </div>
            )}

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
          </div>
        );
      })}
    </div>
  );
}
