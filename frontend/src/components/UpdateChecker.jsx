import { useState } from "react";
import { api } from "../api/client.js";
import { RefreshIcon, CheckCircleIcon, AlertCircleIcon } from "./icons.jsx";

export default function UpdateChecker() {
  const [state, setState] = useState("idle");
  const [info, setInfo] = useState(null);
  const [error, setError] = useState("");

  const handleCheck = async () => {
    setState("checking");
    setError("");
    try {
      const res = await api.checkForUpdate();
      setInfo(res);
      setState(res.update_available ? "available" : "upToDate");
    } catch (e) {
      setError(e.message);
      setState("error");
    }
  };

  const handleInstall = async () => {
    setState("installing");
    setError("");
    try {
      await api.installUpdate();
    } catch (e) {
      setError(e.message);
      setState("error");
    }
  };

  return (
    <div className="update-checker">
      {state === "idle" && (
        <button type="button" className="update-checker-trigger" onClick={handleCheck}>
          <RefreshIcon style={{ width: 13, height: 13 }} /> Проверить обновление
        </button>
      )}

      {state === "checking" && <div className="update-checker-status">Проверка…</div>}

      {state === "upToDate" && (
        <div className="update-checker-status">
          <CheckCircleIcon style={{ width: 13, height: 13 }} /> Установлена последняя версия
        </div>
      )}

      {state === "available" && info && (
        <div className="update-checker-panel">
          <div className="update-checker-status" style={{ color: "var(--accent-text)" }}>
            <RefreshIcon style={{ width: 13, height: 13 }} /> Доступно обновление
            {info.changes.length > 0 ? ` — ${info.changes.length} измен.` : ""}
          </div>
          {info.changes.length > 0 && (
            <ul className="update-checker-changes">
              {info.changes.slice(0, 12).map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          )}
          {info.frozen ? (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={handleInstall}
              style={{ width: "100%", justifyContent: "center", marginTop: 8 }}
            >
              Скачать и установить
            </button>
          ) : (
            <div className="text-muted" style={{ fontSize: 11.5, marginTop: 6 }}>
              Установка доступна только в собранном приложении.
            </div>
          )}
        </div>
      )}

      {state === "installing" && (
        <div className="update-checker-status">
          Скачивание и установка… приложение перезапустится само.
        </div>
      )}

      {state === "error" && (
        <div className="update-checker-panel">
          <div className="update-checker-status" style={{ color: "var(--danger-text)" }}>
            <AlertCircleIcon style={{ width: 13, height: 13 }} /> {error}
          </div>
          <button type="button" className="btn btn-secondary btn-sm" onClick={handleCheck} style={{ marginTop: 6 }}>
            Повторить
          </button>
        </div>
      )}
    </div>
  );
}
