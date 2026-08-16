import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";

export default function Setup() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const { completeSetup, setupRequired, loading, user } = useAuth();
  const navigate = useNavigate();

  // Настройка уже выполнена (или мы только что её завершили) — сюда
  // возвращаться нечего.
  if (!loading && !setupRequired && !user) {
    return <Navigate to="/login" replace />;
  }
  if (user) {
    return <Navigate to="/" replace />;
  }

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);

    setSubmitting(true);
    try {
      await completeSetup(email.trim());
      navigate("/", { replace: true });
    } catch (e2) {
      setError(e2.message || "Не удалось создать администратора");
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
      <form className="panel" style={{ width: 380 }} onSubmit={handleSubmit}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <div className="brand-mark" style={{ background: "linear-gradient(135deg, var(--accent), #8b8ff5)" }}>
            AS
          </div>
          <div style={{ fontWeight: 650, fontSize: 16 }}>AutoSync</div>
        </div>
        <p className="text-muted" style={{ fontSize: 13, marginTop: 0, marginBottom: 18 }}>
          Первый запуск — создайте учётную запись администратора. Дальше можно будет
          добавлять операторов прямо из интерфейса.
        </p>

        <div className="field">
          <label htmlFor="email">Email администратора</label>
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

        {error && (
          <p className="error-text" style={{ color: "var(--danger)", fontSize: 13 }}>
            {error}
          </p>
        )}

        <button
          className="btn btn-primary"
          style={{ width: "100%", justifyContent: "center", marginTop: 4 }}
          disabled={submitting}
          type="submit"
        >
          {submitting ? "Создание…" : "Создать администратора и войти"}
        </button>
      </form>
    </div>
  );
}
