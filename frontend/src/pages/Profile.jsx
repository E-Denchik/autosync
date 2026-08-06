import { useState } from "react";
import { api } from "../api/client.js";
import { useAuth } from "../context/AuthContext.jsx";
import { useToast } from "../context/ToastContext.jsx";

const EMPTY_FORM = { currentPassword: "", newPassword: "", confirmPassword: "" };

export default function Profile() {
  const { user } = useAuth();
  const toast = useToast();
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (form.newPassword !== form.confirmPassword) {
      toast.error("Новый пароль и подтверждение не совпадают");
      return;
    }
    setSaving(true);
    try {
      await api.changeOwnPassword(form.currentPassword, form.newPassword);
      toast.success("Пароль изменён");
      setForm(EMPTY_FORM);
    } catch (e2) {
      toast.error(e2.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Профиль</h2>
          <p>
            {user?.email} · {user?.role === "admin" ? "Администратор" : "Оператор"}
          </p>
        </div>
      </div>

      <form className="panel" style={{ maxWidth: 420 }} onSubmit={handleSubmit}>
        <div className="section-title">Сменить пароль</div>
        <div className="field">
          <label htmlFor="currentPassword">Текущий пароль</label>
          <input
            id="currentPassword"
            type="password"
            required
            value={form.currentPassword}
            onChange={(e) => setForm((f) => ({ ...f, currentPassword: e.target.value }))}
          />
        </div>
        <div className="field">
          <label htmlFor="newPassword">Новый пароль (мин. 8 символов)</label>
          <input
            id="newPassword"
            type="password"
            required
            minLength={8}
            value={form.newPassword}
            onChange={(e) => setForm((f) => ({ ...f, newPassword: e.target.value }))}
          />
        </div>
        <div className="field">
          <label htmlFor="confirmPassword">Повторите новый пароль</label>
          <input
            id="confirmPassword"
            type="password"
            required
            minLength={8}
            value={form.confirmPassword}
            onChange={(e) => setForm((f) => ({ ...f, confirmPassword: e.target.value }))}
          />
        </div>
        <button className="btn btn-primary" disabled={saving} type="submit">
          {saving ? "Сохранение…" : "Сменить пароль"}
        </button>
      </form>
    </div>
  );
}
