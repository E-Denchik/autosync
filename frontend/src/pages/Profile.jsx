import { useAuth } from "../context/AuthContext.jsx";

export default function Profile() {
  const { user } = useAuth();

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

      <div className="panel" style={{ maxWidth: 420 }}>
        <p className="text-muted" style={{ fontSize: 13 }}>
          Чтобы войти под другим пользователем, нажмите «Выйти» и выберите его на экране входа.
        </p>
      </div>
    </div>
  );
}
