import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import HowToUse from "../../components/HowToUse.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { RefreshIcon } from "../../components/icons.jsx";

const PROVIDER_LABELS = {
  ollama: "Ollama",
  lmstudio: "LM Studio",
};

export default function LlmSettings() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selecting, setSelecting] = useState(null); // "provider:model" в процессе выбора
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
            `Ранее выбранная модель «${model}» (${PROVIDER_LABELS[provider] || provider}) больше не найдена на диске — выбор сброшен, выберите другую.`
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

  if (loading) return <Spinner label="Ищем модели на этой машине…" />;
  if (!data) return null;

  const isSelected = (provider, modelName) =>
    data.selected && data.selected.provider === provider && data.selected.model === modelName;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>LLM-модель</h2>
          <p>
            AutoSync сам находит модели, скачанные на этой машине через Ollama и LM Studio, и
            использует ту, что вы выберете, — для предложений по цене, генерации карточек и
            LLM-фоллбэка сопоставления запчастей. Выбор сохраняется между сессиями, пока модель не
            будет удалена с диска.
          </p>
        </div>
        <button className="btn btn-secondary" onClick={load}>
          <RefreshIcon /> Обновить список
        </button>
      </div>

      <HowToUse
        steps={[
          "Выберите одну модель из найденных на этой машине (Ollama или LM Studio) — она будет использоваться для предложений по цене, генерации карточек и сопоставления запчастей по названию.",
          "Если списки пустые — убедитесь, что запущена Ollama (ollama serve) или включён Local Server в LM Studio, затем нажмите «Обновить список».",
          "Без выбранной модели эти LLM-функции просто недоступны — остальная часть приложения продолжает работать как обычно.",
        ]}
      />

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

      {Object.entries(data.providers).map(([provider, info]) => (
        <div className="panel" key={provider} style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
            <h3 style={{ margin: 0 }}>{PROVIDER_LABELS[provider] || provider}</h3>
            {provider === "lmstudio" && info.server_running === false && info.models.length > 0 && (
              <span className="status-pill status-pending">Local Server выключен</span>
            )}
            {!info.available && <span className="status-pill status-rejected">не найден</span>}
          </div>

          {!info.available && (
            <p className="text-muted">
              {provider === "ollama"
                ? "Ollama не отвечает — проверьте, что демон запущен (ollama serve)."
                : "Ни одной модели не найдено ни на диске, ни через Local Server LM Studio."}
            </p>
          )}

          {info.available && info.models.length === 0 && (
            <p className="text-muted">Модели не найдены.</p>
          )}

          {info.models.length > 0 && (
            <div className="table-wrap">
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
                    const unavailable = provider === "lmstudio" && info.server_running === false;
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
                              title={unavailable ? "Включите Local Server в приложении LM Studio" : undefined}
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
