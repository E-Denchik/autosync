import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import HowToUse from "../../components/HowToUse.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { RefreshIcon } from "../../components/icons.jsx";

const PROVIDER_LABELS = {
  ollama: "Ollama",
  lmstudio: "LM Studio",
  vsegpt: "vsegpt.ru",
};

export default function LlmSettings() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selecting, setSelecting] = useState(null); // "provider:model" в процессе выбора
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [savingKey, setSavingKey] = useState(false);
  const toast = useToast();

  const load = () => {
    setLoading(true);
    api
      .listLlmModels()
      .then((res) => {
        setData(res);
        if (res.previous_selection) {
          const { provider, model } = res.previous_selection;
          toast.error(
            `Ранее выбранная модель «${model}» (${PROVIDER_LABELS[provider] || provider}) больше не найдена — выбор сброшен, выберите другую.`
          );
        }
      })
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSelect = async (provider, modelName) => {
    setSelecting(`${provider}:${modelName}`);
    try {
      await api.selectLlmModel(provider, modelName);
      toast.success(`Выбрана модель «${modelName}» (${PROVIDER_LABELS[provider] || provider})`);
      load();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSelecting(null);
    }
  };

  const handleSaveApiKey = async () => {
    if (!apiKeyInput.trim()) {
      toast.error("Введите ключ");
      return;
    }
    setSavingKey(true);
    try {
      await api.saveIntegrationKeys({ VSEGPT_API_KEY: apiKeyInput.trim() });
      toast.success("Ключ vsegpt.ru сохранён — загружаем список моделей…");
      setApiKeyInput("");
      load();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSavingKey(false);
    }
  };

  if (loading) return <Spinner label="Ищем доступные модели…" />;
  if (!data) return null;

  const isSelected = (provider, modelName) =>
    data.selected && data.selected.provider === provider && data.selected.model === modelName;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>LLM-модель</h2>
          <p>
            AutoSync находит модели, скачанные на этой машине через Ollama и LM Studio, либо
            облачные модели vsegpt.ru (по вашему API-ключу), и использует ту, что вы выберете, —
            для предложений по цене, генерации карточек и LLM-фоллбэка сопоставления запчастей.
            Выбор сохраняется между сессиями, пока модель не станет недоступна.
          </p>
        </div>
        <button className="btn btn-secondary" onClick={load}>
          <RefreshIcon /> Обновить список
        </button>
      </div>

      <HowToUse
        steps={[
          "Локальные модели: убедитесь, что запущена Ollama (ollama serve) или включён Local Server в LM Studio, затем нажмите «Обновить список».",
          "Облачные модели vsegpt.ru: вставьте API-ключ в поле ниже и сохраните — появится список моделей, доступных этому ключу.",
          "Выберите одну модель из списка — она будет использоваться для предложений по цене, генерации карточек и сопоставления запчастей по названию.",
          "Без выбранной модели эти LLM-функции просто недоступны — остальная часть приложения продолжает работать как обычно.",
        ]}
      />

      <div className="panel" style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
          <h3 style={{ margin: 0 }}>vsegpt.ru — API-ключ</h3>
          {data.vsegpt_configured ? (
            <span className="status-pill status-approved">настроен</span>
          ) : (
            <span className="status-pill status-pending">не настроен</span>
          )}
        </div>
        <p className="text-muted" style={{ marginTop: 0 }}>
          Ключ сохраняется в базе данных и применяется сразу — перезапуск не нужен. Значение
          обратно не показывается, только факт "настроен".
        </p>
        <div className="field-row">
          <div className="field">
            <label htmlFor="vsegpt-api-key">API-ключ vsegpt.ru</label>
            <input
              id="vsegpt-api-key"
              type="password"
              autoComplete="off"
              value={apiKeyInput}
              onChange={(e) => setApiKeyInput(e.target.value)}
              placeholder={data.vsegpt_configured ? "••••••••••••" : "sk-or-..."}
            />
          </div>
          <button className="btn btn-primary btn-sm" disabled={savingKey} onClick={handleSaveApiKey}>
            {savingKey ? "Сохранение…" : data.vsegpt_configured ? "Заменить ключ" : "Сохранить ключ"}
          </button>
        </div>
      </div>

      {data.selected ? (
        <div className="panel" style={{ marginBottom: 20 }}>
          Сейчас используется: <strong>{data.selected.model}</strong>{" "}
          <span className="status-pill status-approved">{PROVIDER_LABELS[data.selected.provider]}</span>
        </div>
      ) : (
        <div className="panel" style={{ marginBottom: 20 }}>
          <span className="status-pill status-pending">не выбрана</span> — LLM-функции (предложения по
          цене, генерация карточек, фоллбэк сопоставления) недоступны, пока модель не выбрана.
        </div>
      )}

      {data.providers.vsegpt?.status && (
        <div className="panel" style={{ marginBottom: 20 }}>
          <h3 style={{ marginTop: 0 }}>Состояние аккаунта vsegpt.ru</h3>
          {!data.providers.vsegpt.status.available ? (
            <p className="text-muted">
              {data.providers.vsegpt.status.error || "Не удалось получить статистику аккаунта."}
            </p>
          ) : (
            <div className="llm-stats-grid">
              <div><strong>Баланс</strong><br />{data.providers.vsegpt.status.balance ?? "—"} {data.providers.vsegpt.status.currency || ""}</div>
              <div><strong>Запросов через AutoSync</strong><br />{data.providers.vsegpt.status.local_requests ?? 0}</div>
              <div><strong>Успешно</strong><br />{data.providers.vsegpt.status.local_successes ?? 0}</div>
              <div><strong>Ошибок</strong><br />{data.providers.vsegpt.status.local_errors ?? 0}</div>
              {data.providers.vsegpt.status.spent != null && <div><strong>Потрачено</strong><br />{data.providers.vsegpt.status.spent} {data.providers.vsegpt.status.currency || ""}</div>}
              {data.providers.vsegpt.status.requests_remaining != null && <div><strong>Осталось запросов</strong><br />{data.providers.vsegpt.status.requests_remaining}</div>}
            </div>
          )}
          <p className="text-muted" style={{ marginBottom: 0, fontSize: 12 }}>
            Баланс и доступные лимиты получены из v1/balance. Счётчики AutoSync относятся к текущему процессу сервиса.
          </p>
        </div>
      )}

      {Object.entries(data.providers).map(([provider, info]) => (
        <div className="panel" key={provider} style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
            <h3 style={{ margin: 0 }}>{PROVIDER_LABELS[provider] || provider}</h3>
            {provider === "lmstudio" && info.server_running === false && info.models.length > 0 && (
              <span className="status-pill status-pending">Local Server выключен</span>
            )}
            {!info.available && provider !== "vsegpt" && (
              <span className="status-pill status-rejected">не найден</span>
            )}
            {!info.available && provider === "vsegpt" && data.vsegpt_configured && (
              <span className="status-pill status-rejected">ошибка</span>
            )}
          </div>

          {!info.available && provider === "ollama" && (
            <p className="text-muted">Ollama не отвечает — проверьте, что демон запущен (ollama serve).</p>
          )}
          {!info.available && provider === "lmstudio" && (
            <p className="text-muted">Ни одной модели не найдено ни на диске, ни через Local Server LM Studio.</p>
          )}
          {!info.available && provider === "vsegpt" && !data.vsegpt_configured && (
            <p className="text-muted">Добавьте API-ключ выше, чтобы увидеть доступные модели.</p>
          )}
          {!info.available && provider === "vsegpt" && data.vsegpt_configured && (
            <p className="text-muted">
              {info.reason === "non_positive_balance"
                ? "Модели отображаются, но временно заблокированы: баланс vsegpt.ru равен нулю или меньше нуля. Пополните счёт и нажмите «Обновить список»."
                : info.reason === "balance_unknown"
                ? "Модели отображаются, но временно заблокированы: баланс vsegpt.ru не удалось подтвердить. Проверьте ключ и нажмите «Обновить список»."
                : `Не удалось получить список моделей${info.error ? `: ${info.error}` : ""} — проверьте ключ.`}
            </p>
          )}

          {info.available && info.models.length === 0 && (
            <p className="text-muted">Модели не найдены.</p>
          )}

          {info.models.length > 0 && (
            <div className="table-wrap llm-model-list">
              <table>
                <thead>
                  <tr>
                    <th>Модель</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {info.models.map((m) => {
                    const key = `${provider}:${m.name}`;
                    const unavailable =
                      (provider === "lmstudio" && info.server_running === false) ||
                      (provider === "vsegpt" && info.temporarily_unavailable);
                    return (
                      <tr key={key}>
                        <td>{m.name}</td>
                        <td style={{ textAlign: "right" }}>
                          {isSelected(provider, m.name) ? (
                            <span className="status-pill status-approved">выбрана</span>
                          ) : (
                            <button
                              className="btn btn-secondary btn-sm"
                              disabled={selecting === key || unavailable}
                              title={
                                unavailable
                                  ? provider === "vsegpt"
                                    ? "Баланс vsegpt.ru не подтверждён или не положительный"
                                    : "Включите Local Server в приложении LM Studio"
                                  : undefined
                              }
                              onClick={() => handleSelect(provider, m.name)}
                            >
                              {selecting === key ? "Выбираем…" : "Использовать"}
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
