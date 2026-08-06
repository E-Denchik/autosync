import { createContext, useCallback, useContext, useRef, useState } from "react";
import { AlertCircleIcon, CheckCircleIcon, InfoIcon } from "../components/icons.jsx";

const ToastContext = createContext(null);

const ICONS = {
  success: CheckCircleIcon,
  error: AlertCircleIcon,
  info: InfoIcon,
};

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const idRef = useRef(0);

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (message, type = "info", duration = 5000) => {
      const id = ++idRef.current;
      setToasts((prev) => [...prev, { id, message, type }]);
      if (duration) {
        setTimeout(() => dismiss(id), duration);
      }
      return id;
    },
    [dismiss]
  );

  const toast = {
    success: (msg) => push(msg, "success"),
    error: (msg) => push(msg, "error", 8000),
    info: (msg) => push(msg, "info"),
  };

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="toast-viewport">
        {toasts.map((t) => {
          const Icon = ICONS[t.type] || InfoIcon;
          return (
            <div key={t.id} className={`toast toast-${t.type}`}>
              <Icon className="toast-icon" />
              <span>{t.message}</span>
              <button className="toast-close" onClick={() => dismiss(t.id)} aria-label="Закрыть">
                ×
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast должен вызываться внутри ToastProvider");
  return ctx;
}
