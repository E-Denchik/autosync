import { createContext, useCallback, useContext, useEffect, useState } from "react";

const ErrorLogContext = createContext(null);

// localStorage, не сервер: журнал должен работать и тогда, когда backend
// недоступен — это как раз частый случай для самих ошибок, которые сюда
// попадают. Переживает перезапуск приложения (см. native_app.py:
// private_mode=False — обычный, не приватный контекст webview).
const STORAGE_KEY = "autosync_error_log";
const LAST_VIEWED_KEY = "autosync_error_log_last_viewed";
const MAX_ENTRIES = 200;

function readStoredEntries() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeStoredEntries(entries) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // Приватный режим/квота диска и т.п. — журнал просто не переживёт
    // перезапуск в этой сессии, само приложение это не должно ронять.
  }
}

function readLastViewed() {
  try {
    return localStorage.getItem(LAST_VIEWED_KEY);
  } catch {
    return null;
  }
}

export function ErrorLogProvider({ children }) {
  const [entries, setEntries] = useState(readStoredEntries);
  const [lastViewed, setLastViewed] = useState(readLastViewed);

  const log = useCallback((message, source) => {
    setEntries((prev) => {
      const entry = {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        time: new Date().toISOString(),
        message: String(message ?? "Неизвестная ошибка"),
        source: source || null,
      };
      const next = [entry, ...prev].slice(0, MAX_ENTRIES);
      writeStoredEntries(next);
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    setEntries([]);
    writeStoredEntries([]);
  }, []);

  const markViewed = useCallback(() => {
    const now = new Date().toISOString();
    try {
      localStorage.setItem(LAST_VIEWED_KEY, now);
    } catch {
      // см. writeStoredEntries — не критично, просто счётчик непрочитанных
      // не переживёт перезапуск в этой сессии.
    }
    setLastViewed(now);
  }, []);

  // Не только ошибки, пойманные явным try/catch (toast.error, ErrorBoundary)
  // — сюда же попадают совсем необработанные сбои: исключение в обработчике
  // события без try/catch, отклонённый Promise, про который никто не
  // спросил .catch(). Пользователь именно с такой ошибкой и столкнулся —
  // она "вылезла и быстро пропала", то есть не была явно показана через
  // toast.error() ни одним местом в коде.
  useEffect(() => {
    const onError = (event) => {
      log(event.error?.message || event.message || "Неизвестная ошибка", "window.onerror");
    };
    const onRejection = (event) => {
      const reason = event.reason;
      const message = reason instanceof Error ? reason.message : String(reason);
      log(message, "unhandledrejection");
    };
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, [log]);

  const unreadCount = entries.filter((e) => !lastViewed || e.time > lastViewed).length;

  return (
    <ErrorLogContext.Provider value={{ entries, log, clear, markViewed, unreadCount }}>
      {children}
    </ErrorLogContext.Provider>
  );
}

export function useErrorLog() {
  const ctx = useContext(ErrorLogContext);
  if (!ctx) throw new Error("useErrorLog должен вызываться внутри ErrorLogProvider");
  return ctx;
}
