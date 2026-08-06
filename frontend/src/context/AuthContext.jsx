import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api, setAuthToken, setUnauthorizedHandler } from "../api/client.js";

const AuthContext = createContext(null);
const STORAGE_KEY = "autosync_token";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [setupRequired, setSetupRequired] = useState(false);

  const clearSession = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
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

      const token = localStorage.getItem(STORAGE_KEY);
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

  const login = async (email, password) => {
    const { token, user: loggedInUser } = await api.login(email, password);
    localStorage.setItem(STORAGE_KEY, token);
    setAuthToken(token);
    setUser(loggedInUser);
    return loggedInUser;
  };

  const completeSetup = async (email, password) => {
    const { token, user: createdUser } = await api.setup(email, password);
    localStorage.setItem(STORAGE_KEY, token);
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
