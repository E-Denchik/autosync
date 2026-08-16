import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api, setAuthToken, setUnauthorizedHandler } from "../api/client.js";

const AuthContext = createContext(null);
const STORAGE_KEY = "autosync_token";

// localStorage недоступен в приватном/инкогнито-режиме части webview-движков
// (задевало собственное окно AutoSync — см. native_app.py: run_window) —
// там это исправлено, но и здесь не полагаемся на голую доступность API:
// без этой защиты чтение падало необработанным исключением ДО setLoading(false),
// и приложение зависало на "Загрузка…" навсегда, без единой подсказки на экране.
function safeStorage() {
  try {
    localStorage.setItem("__autosync_probe__", "1");
    localStorage.removeItem("__autosync_probe__");
    return localStorage;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [setupRequired, setSetupRequired] = useState(false);

  const clearSession = useCallback(() => {
    safeStorage()?.removeItem(STORAGE_KEY);
    setAuthToken(null);
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(clearSession);

    (async () => {
      // Сначала проверяем, есть ли вообще администратор — актуально для
      // native-режима, где нет CLI и первого админа заводят в браузере
      // (см. Setup.jsx). Если backend недоступен — не блокируем логин
      // навечно, просто идём в обычный флоу.
      try {
        const { setup_required } = await api.setupRequired();
        if (setup_required) {
          setSetupRequired(true);
          setLoading(false);
          return;
        }
      } catch {
        // молча идём дальше — покажем обычный логин
      }

      const token = safeStorage()?.getItem(STORAGE_KEY);
      if (!token) {
        setLoading(false);
        return;
      }
      setAuthToken(token);
      try {
        setUser(await api.me());
      } catch {
        clearSession();
      } finally {
        setLoading(false);
      }
    })();
  }, [clearSession]);

  const login = async (userId) => {
    const { token, user: loggedInUser } = await api.login(userId);
    safeStorage()?.setItem(STORAGE_KEY, token);
    setAuthToken(token);
    setUser(loggedInUser);
    return loggedInUser;
  };

  const completeSetup = async (email) => {
    const { token, user: createdUser } = await api.setup(email);
    safeStorage()?.setItem(STORAGE_KEY, token);
    setAuthToken(token);
    setUser(createdUser);
    setSetupRequired(false);
    return createdUser;
  };

  const logout = () => {
    clearSession();
  };

  return (
    <AuthContext.Provider value={{ user, loading, setupRequired, login, completeSetup, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth должен вызываться внутри AuthProvider");
  return ctx;
}
