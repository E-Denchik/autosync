import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "../context/ToastContext.jsx";
import { RefreshIcon, CheckCircleIcon, AlertCircleIcon } from "./icons.jsx";

export default function UpdateChecker() {
  const [state, setState] = useState("idle");
  const [info, setInfo] = useState(null);
  const [error, setError] = useState("");
  const toast = useToast();

  useEffect(() => {
    // Один раз при старте — не осталось ли необъявленного результата
    // предыдущей попытки обновить приложение (см. update_checker.py:
    // consume_pending_update_result — раньше неудачная тихая установка
    // просто не оставляла никакого следа, кроме того что при следующей
    // проверке снова предлагалось "обновление доступно").
    api
      .getPendingUpdateResult()
      .then((result) => {
        if (!result) return;
        if (result.success) {
          toast.success("Обновление успешно установлено");
        } else {
          toast.error(result.message || "Не удалось установить обновление");
        }
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  const handleDownload = async () => {
    setState("opening");
    setError("");
    try {
      await api.startUpdateDownload();
      if (window.pywebview?.api?.open_update_window) {
        await window.pywebview.api.open_update_window();
        setState("idle");
      } else {
        // Не должно случиться в собранном приложении (кнопка видна только
        // когда info.frozen истинно), но на всякий случай не теряем прогресс
        // молча — скачивание уже идёт на бэкенде, просто некуда открыть окно.
        setError("Не удалось открыть окно обновления — попробуйте перезапустить приложение.");
        setState("error");
      }
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
              onClick={handleDownload}
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

      {state === "opening" && <div className="update-checker-status">Открываю окно обновления…</div>}

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
