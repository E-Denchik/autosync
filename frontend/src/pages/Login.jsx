import { useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client.js";
import { useAuth } from "../context/AuthContext.jsx";
import Spinner from "../components/Spinner.jsx";

export default function Login() {
  const [users, setUsers] = useState([]);
  const [loadingUsers, setLoadingUsers] = useState(true);
  const [error, setError] = useState(null);
  const [submittingId, setSubmittingId] = useState(null);
  const { login, setupRequired } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    api
      .loginOptions()
      .then(setUsers)
      .catch((e) => setError(e.message))
      .finally(() => setLoadingUsers(false));
  }, []);

  if (setupRequired) {
    return <Navigate to="/setup" replace />;
  }

  const handleSelect = async (user) => {
    setError(null);
    setSubmittingId(user.id);
    try {
      await login(user.id);
      const redirectTo = location.state?.from || "/";
      navigate(redirectTo, { replace: true });
    } catch (e2) {
      setError(e2.message || "Не удалось войти");
    } finally {
      setSubmittingId(null);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--bg)",
      }}
    >
      <div className="panel" style={{ width: 360 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
          <div className="brand-mark" style={{ background: "linear-gradient(135deg, var(--accent), #8b8ff5)" }}>
            AS
          </div>
          <div style={{ fontWeight: 650, fontSize: 16 }}>AutoSync</div>
        </div>

        <p className="text-muted" style={{ fontSize: 13, marginTop: 0, marginBottom: 16 }}>
          Выберите пользователя
        </p>

        {loadingUsers ? (
          <Spinner label="Загрузка…" />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {users.map((u) => (
              <button
                key={u.id}
                type="button"
                className="btn btn-secondary"
                style={{ justifyContent: "space-between", width: "100%" }}
                disabled={submittingId !== null}
                onClick={() => handleSelect(u)}
              >
                <span>{u.email}</span>
                <span className="text-muted" style={{ fontSize: 12 }}>
                  {u.role === "admin" ? "Администратор" : "Оператор"}
                </span>
              </button>
            ))}
            {users.length === 0 && <p className="text-muted" style={{ fontSize: 13 }}>Нет доступных пользователей.</p>}
          </div>
        )}

        {error && (
          <p className="error-text" style={{ color: "var(--danger)", fontSize: 13, marginTop: 16 }}>
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
