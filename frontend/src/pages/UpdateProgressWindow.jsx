import { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { DownloadIcon, CheckCircleIcon, AlertCircleIcon, CloseIcon } from "../components/icons.jsx";

const POLL_MS = 300;

function formatMb(bytes) {
  return (bytes / (1024 * 1024)).toFixed(1);
}

function formatSpeed(bytesPerSec) {
  if (!bytesPerSec) return "";
  return `${formatMb(bytesPerSec)} МБ/с`;
}

function closeNativeWindow() {
  if (window.pywebview?.api?.close_window) {
    window.pywebview.api.close_window();
  }
}

// Отдельное СИСТЕМНОЕ окно (не панель внутри главного) — открывается через
// window.pywebview.api.open_update_window() из UpdateChecker.jsx в главном
// окне. Существует независимо: можно свернуть/закрыть, а фоновая закачка на
// бэкенде при этом не прерывается — окно только отображает её состояние.
export default function UpdateProgressWindow() {
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef(null);

  useEffect(() => {
    const poll = () => {
      api
        .getUpdateProgress()
        .then(setState)
        .catch(() => {});
    };
    poll();
    pollRef.current = setInterval(poll, POLL_MS);
    return () => clearInterval(pollRef.current);
  }, []);

  const phase = state?.phase ?? "idle";

  const handleStart = async () => {
    setBusy(true);
    try {
      await api.startUpdateDownload();
    } catch (e) {
      setState((s) => ({ ...(s || {}), phase: "error", error: e.message }));
    } finally {
      setBusy(false);
    }
  };

  const handleCancel = async () => {
    setBusy(true);
    try {
      await api.cancelUpdateDownload();
    } finally {
      setBusy(false);
    }
  };

  const handleApply = async () => {
    setBusy(true);
    try {
      await api.applyUpdate();
    } catch (e) {
      setState((s) => ({ ...(s || {}), phase: "error", error: e.message }));
      setBusy(false);
    }
    // при успехе процесс скоро сам завершится — окно закроется вместе с ним
  };

  const percent =
    state?.total_bytes > 0 ? Math.min(100, Math.round((state.downloaded_bytes / state.total_bytes) * 100)) : null;

  return (
    <div className="update-window">
      <div className="update-window-header">
        <DownloadIcon style={{ width: 18, height: 18 }} />
        <span>Обновление AutoSync</span>
      </div>

      {phase === "idle" && (
        <div className="update-window-body">
          <p className="text-muted">Обновление ещё не начато.</p>
          <button className="btn btn-primary" disabled={busy} onClick={handleStart}>
            Скачать обновление
          </button>
        </div>
      )}

      {phase === "downloading" && (
        <div className="update-window-body">
          <p>Скачивание обновления…</p>
          <div className="update-progress-track">
            <div className="update-progress-fill" style={{ width: `${percent ?? 0}%` }} />
          </div>
          <div className="update-progress-meta">
            <span>
              {formatMb(state.downloaded_bytes)} МБ
              {state.total_bytes ? ` из ${formatMb(state.total_bytes)} МБ` : ""}
              {percent !== null ? ` (${percent}%)` : ""}
            </span>
            {state.speed_bytes_per_sec > 0 && <span>{formatSpeed(state.speed_bytes_per_sec)}</span>}
          </div>
          <button className="btn btn-secondary" disabled={busy} onClick={handleCancel} style={{ marginTop: 12 }}>
            Отменить
          </button>
        </div>
      )}

      {phase === "downloaded" && (
        <div className="update-window-body">
          <div className="update-window-status" style={{ color: "var(--accent-text)" }}>
            <CheckCircleIcon style={{ width: 16, height: 16 }} /> Обновление скачано
          </div>
          <p className="text-muted" style={{ fontSize: 12.5 }}>
            Приложение закроется и перезапустится само после установки — сохраните текущую работу
            перед тем, как продолжить.
          </p>
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button className="btn btn-primary" disabled={busy} onClick={handleApply}>
              Установить обновление
            </button>
            <button className="btn btn-secondary" disabled={busy} onClick={handleCancel}>
              Отменить
            </button>
          </div>
        </div>
      )}

      {phase === "applying" && (
        <div className="update-window-body">
          <p>Устанавливаем обновление…</p>
          <p className="text-muted" style={{ fontSize: 12.5 }}>
            Приложение сейчас закроется и запустится заново — это нормально, окно можно не закрывать
            вручную.
          </p>
        </div>
      )}

      {phase === "canceled" && (
        <div className="update-window-body">
          <p className="text-muted">Скачивание отменено.</p>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-primary" disabled={busy} onClick={handleStart}>
              Скачать заново
            </button>
            <button className="btn btn-secondary" onClick={closeNativeWindow}>
              <CloseIcon style={{ width: 13, height: 13 }} /> Закрыть
            </button>
          </div>
        </div>
      )}

      {phase === "error" && (
        <div className="update-window-body">
          <div className="update-window-status" style={{ color: "var(--danger-text)" }}>
            <AlertCircleIcon style={{ width: 16, height: 16 }} /> {state?.error || "Не удалось обновить"}
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button className="btn btn-primary" disabled={busy} onClick={handleStart}>
              Повторить
            </button>
            <button className="btn btn-secondary" onClick={closeNativeWindow}>
              <CloseIcon style={{ width: 13, height: 13 }} /> Закрыть
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
