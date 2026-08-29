import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "../context/ToastContext.jsx";
import Spinner from "./Spinner.jsx";
import { AlertCircleIcon, CheckCircleIcon } from "./icons.jsx";

const PROVIDER_LABELS = {
  ollama: "Ollama",
  lmstudio: "LM Studio",
};

// Заказчик жаловался, что смена модели в настройках "как будто не
// применяется" — на деле причина была в другом (см. llm_client.py:
// без выбора приложение тихо уходило на жёстко прошитый гигантский
// запасной вариант), но доверия это не добавляло: до сих пор единственный
// способ узнать, реально ли работает ИИ, — дождаться ошибки посреди
// разбора файла. Эта модалка перед загрузкой явно показывает: выбрана ли
// модель, даёт выбрать/сменить её прямо здесь и по кнопке "Проверить"
// реально дожидается ответа модели — не "она есть в списке", а "она
// действительно отвечает" (см. LLMClient.test_connection).
export default function LlmPreflightModal({ onClose, onContinue }) {
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selecting, setSelecting] = useState(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const toast = useToast();

  const load = () => {
    setLoading(true);
    setLoadError(null);
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
      .catch((e) => setLoadError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSelect = async (provider, modelName) => {
    setSelecting(`${provider}:${modelName}`);
    setTestResult(null);
    try {
      await api.selectLlmModel(provider, modelName);
      toast.success(`Выбрана модель «${modelName}»`);
      load();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSelecting(null);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await api.testLlmConnection();
      setTestResult(res);
    } catch (e) {
      setTestResult({ ok: false, error: e.message });
    } finally {
      setTesting(false);
    }
  };

  const isSelected = (provider, modelName) =>
    data?.selected && data.selected.provider === provider && data.selected.model === modelName;
  const allModels = data ? Object.entries(data.providers).flatMap(([p, info]) => info.models.map((m) => ({ p, m }))) : [];

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(10, 11, 16, 0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        className="panel"
        style={{ width: 560, maxHeight: "85vh", overflowY: "auto", display: "flex", flexDirection: "column" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="section-title">Проверка ИИ перед сопоставлением</div>
        <p className="text-muted" style={{ fontSize: 12.5, marginTop: -6, marginBottom: 14 }}>
          Точное совпадение по артикулу и поиск по кросс-номерам поставщика работают без ИИ. Локальная
          модель нужна только для последнего шага — подбора по названию, когда точнее ничего не нашлось.
          Без рабочей модели такие позиции просто уйдут на ручную проверку — само сопоставление всё равно
          пройдёт до конца.
        </p>

        {loading && <Spinner label="Проверяем, что видно на этой машине…" />}

        {!loading && loadError && (
          <div className="hint-banner hint-warning">
            <AlertCircleIcon />
            <span>ИИ-сервис недоступен: {loadError}. Точное совпадение и кросс-номера будут работать как обычно.</span>
          </div>
        )}

        {!loading && data && (
          <>
            {data.selected ? (
              <div className="hint-banner" style={{ marginBottom: 12 }}>
                Сейчас выбрана: <strong style={{ marginLeft: 4 }}>{data.selected.model}</strong>
                <span className="status-pill status-approved" style={{ marginLeft: 8 }}>
                  {PROVIDER_LABELS[data.selected.provider]}
                </span>
              </div>
            ) : (
              <div className="hint-banner hint-warning" style={{ marginBottom: 12 }}>
                <AlertCircleIcon />
                <span>Модель не выбрана — выберите одну из списка ниже, либо продолжите без ИИ.</span>
              </div>
            )}

            {allModels.length === 0 ? (
              <p className="text-muted" style={{ fontSize: 12.5 }}>
                На этой машине не нашлось ни одной модели (Ollama/LM Studio). Установите модель и нажмите
                «Обновить», либо продолжите без ИИ.
              </p>
            ) : (
              <div className="table-wrap" style={{ marginBottom: 14 }}>
                <table>
                  <thead>
                    <tr>
                      <th>Модель</th>
                      <th>Раннер</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {allModels.map(({ p, m }) => {
                      const key = `${p}:${m.name}`;
                      return (
                        <tr key={key}>
                          <td>{m.name}</td>
                          <td className="text-muted">{PROVIDER_LABELS[p] || p}</td>
                          <td style={{ textAlign: "right" }}>
                            {isSelected(p, m.name) ? (
                              <span className="status-pill status-approved">выбрана</span>
                            ) : (
                              <button
                                className="btn btn-secondary btn-sm"
                                disabled={selecting === key}
                                onClick={() => handleSelect(p, m.name)}
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

            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={!data.selected || testing}
                onClick={handleTest}
              >
                {testing ? "Проверяем модель…" : "Проверить, что модель реально отвечает"}
              </button>
              <button type="button" className="btn btn-secondary btn-sm" onClick={load}>
                Обновить список
              </button>
            </div>
            <p className="text-muted" style={{ fontSize: 11.5, marginTop: 0 }}>
              Модель может числиться на диске, но не поместиться в доступную память при реальной загрузке
              — эта проверка ждёт настоящего ответа, а не просто смотрит на список.
            </p>

            {testResult && (
              <div className={`hint-banner ${testResult.ok ? "hint-success" : "hint-danger"}`}>
                {testResult.ok ? <CheckCircleIcon /> : <AlertCircleIcon />}
                <span>{testResult.ok ? testResult.message : testResult.error}</span>
              </div>
            )}
          </>
        )}

        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          <button className="btn btn-secondary" onClick={onClose}>
            Отмена
          </button>
          <button className="btn btn-primary" style={{ marginLeft: "auto" }} onClick={onContinue}>
            {data?.selected && testResult?.ok
              ? "Загрузить и сопоставить"
              : "Всё равно загрузить и сопоставить"}
          </button>
        </div>
      </div>
    </div>
  );
}
