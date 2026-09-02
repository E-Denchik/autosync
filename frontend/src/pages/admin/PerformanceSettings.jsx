import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { RefreshIcon } from "../../components/icons.jsx";

function formatBytes(value) {
  if (!value) return "нет данных";
  return `${(value / 1024 ** 3).toFixed(1)} ГБ`;
}

export default function PerformanceSettings() {
  const [data, setData] = useState(null);
  const [mode, setMode] = useState("auto");
  const [workers, setWorkers] = useState(2);
  const [timeout, setTimeoutValue] = useState(300);
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  const load = () => api.performance().then((value) => {
    setData(value);
    setMode(value.settings.mode);
    setWorkers(value.settings.workers);
    setTimeoutValue(value.settings.timeout_seconds);
  }).catch((error) => toast.error(error.message));

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const apply = async () => {
    setSaving(true);
    try {
      const value = await api.savePerformance({
        mode,
        workers: Number(workers),
        timeout_seconds: Number(timeout),
      });
      setData(value);
      toast.success("Параметры производительности применены");
    } catch (error) {
      toast.error(error.message);
    } finally {
      setSaving(false);
    }
  };

  if (!data) return <Spinner label="Оцениваем возможности компьютера…" />;
  const system = data.system;
  const recommendation = data.recommendation;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Производительность</h2>
          <p>AutoSync оценивает ресурсы компьютера и подбирает скорость обработки LLM-функций.</p>
        </div>
        <button className="btn btn-secondary" onClick={load} disabled={saving}><RefreshIcon /> Обновить оценку</button>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Характеристики компьютера</h3>
        <div className="llm-stats-grid">
          <div><strong>Операционная система</strong><br />{system.platform}</div>
          <div><strong>Процессоры</strong><br />{system.cpu_count}</div>
          <div><strong>Всего RAM</strong><br />{formatBytes(system.memory_total_bytes)}</div>
          <div><strong>Доступно RAM</strong><br />{formatBytes(system.memory_available_bytes)}</div>
        </div>
        {data.selected_model && (
          <p className="text-muted">Выбранная модель: <strong>{data.selected_model}</strong>{data.model_size_bytes ? ` (${formatBytes(data.model_size_bytes)})` : ""}</p>
        )}
        <p className="text-muted" style={{ marginBottom: 0 }}>{recommendation.reason}</p>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Режим обработки</h3>
        <div className="field-row">
          <div className="field">
            <label htmlFor="performance-mode">Профиль</label>
            <select id="performance-mode" value={mode} onChange={(event) => setMode(event.target.value)}>
              <option value="auto">Автоматический</option>
              <option value="manual">Ручной</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="performance-workers">Параллельных LLM-запросов</label>
            <input id="performance-workers" type="number" min="1" max="4" value={workers} disabled={mode === "auto"} onChange={(event) => setWorkers(event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="performance-timeout">Timeout запроса, секунд</label>
            <input id="performance-timeout" type="number" min="30" max="600" value={timeout} disabled={mode === "auto"} onChange={(event) => setTimeoutValue(event.target.value)} />
          </div>
          <button className="btn btn-primary" onClick={apply} disabled={saving}>{saving ? "Применение…" : "Применить"}</button>
        </div>
        {mode === "auto" && (
          <p className="text-muted" style={{ marginBottom: 0 }}>
            Сейчас автоматически выбрано: <strong>{recommendation.workers}</strong> параллельных запрос(а), timeout <strong>{recommendation.timeout_seconds} с</strong>.
          </p>
        )}
        {recommendation.warnings.map((warning) => <p className="text-muted" key={warning}>{warning}</p>)}
      </div>
    </div>
  );
}
