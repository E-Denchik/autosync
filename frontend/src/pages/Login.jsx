import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const { login, setupRequired } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  if (setupRequired) {
    return <Navigate to="/setup" replace />;
  }

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      const redirectTo = location.state?.from || "/";
      navigate(redirectTo, { replace: true });
    } catch (e2) {
      setError("Неверный email или пароль");
    } finally {
      setSubmitting(false);
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
      <form className="panel" style={{ width: 340 }} onSubmit={handleSubmit}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
          <div className="brand-mark" style={{ background: "linear-gradient(135deg, var(--accent), #8b8ff5)" }}>
            AS
          </div>
          <div style={{ fontWeight: 650, fontSize: 16 }}>AutoSync</div>
        </div>

        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            autoFocus
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@company.ru"
          />
        </div>
        <div className="field">
          <label htmlFor="password">Пароль</label>
          <input
            id="password"
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
          />
        </div>

        {error && <p className="error-text" style={{ color: "var(--danger)", fontSize: 13 }}>{error}</p>}

        <button
          className="btn btn-primary"
          style={{ width: "100%", justifyContent: "center", marginTop: 4 }}
          disabled={submitting}
          type="submit"
        >
          {submitting ? "Вход…" : "Войти"}
        </button>

        <p className="text-muted" style={{ fontSize: 12, marginTop: 16, textAlign: "center" }}>
          Доступ выдаёт администратор платформы.
        </p>
      </form>
    </div>
  );
}
