import { Link, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import Profile from "./pages/Profile.jsx";
import PricingDashboard from "./pages/ozon/PricingDashboard.jsx";
import CardGenerator from "./pages/ozon/CardGenerator.jsx";
import UploadPage from "./pages/repair-orders/UploadPage.jsx";
import ReviewMatches from "./pages/repair-orders/ReviewMatches.jsx";
import RepairOrdersList from "./pages/repair-orders/RepairOrdersList.jsx";
import Login from "./pages/Login.jsx";
import Setup from "./pages/Setup.jsx";
import Users from "./pages/admin/Users.jsx";
import LlmSettings from "./pages/admin/LlmSettings.jsx";
import { useAuth } from "./context/AuthContext.jsx";
import Spinner from "./components/Spinner.jsx";
import { HomeIcon, TagIcon, SparklesIcon, ListIcon, UploadIcon, UsersIcon, CpuIcon } from "./components/icons.jsx";

function ProtectedShell() {
  const { user, loading, setupRequired, logout } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Spinner label="Загрузка…" />
      </div>
    );
  }

  if (setupRequired) {
    return <Navigate to="/setup" replace />;
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">AS</div>
          <div className="brand-name">AutoSync</div>
        </div>

        <nav>
          <NavLink to="/" end>
            <HomeIcon /> Обзор
          </NavLink>
        </nav>

        <div className="module-label">Ozon</div>
        <nav>
          <NavLink to="/ozon/pricing">
            <TagIcon /> Цены
          </NavLink>
          <NavLink to="/ozon/cards">
            <SparklesIcon /> Карточки
          </NavLink>
        </nav>

        <div className="module-label">Заказ-наряды</div>
        <nav>
          <NavLink to="/repair-orders">
            <ListIcon /> Все заказ-наряды
          </NavLink>
          <NavLink to="/repair-orders/upload">
            <UploadIcon /> Загрузка
          </NavLink>
        </nav>

        {user.role === "admin" && (
          <>
            <div className="module-label">Администрирование</div>
            <nav>
              <NavLink to="/admin/users">
                <UsersIcon /> Пользователи
              </NavLink>
              <NavLink to="/admin/llm">
                <CpuIcon /> LLM-модель
              </NavLink>
            </nav>
          </>
        )}

        <div className="sidebar-footer">
          <Link
            to="/profile"
            style={{ color: "#fff", fontWeight: 600, marginBottom: 2, textDecoration: "none", display: "block" }}
          >
            {user.email}
          </Link>
          <div style={{ marginBottom: 10 }}>{user.role === "admin" ? "Администратор" : "Оператор"}</div>
          <button
            onClick={logout}
            style={{
              background: "none",
              border: "1px solid var(--sidebar-border)",
              color: "inherit",
              borderRadius: 6,
              padding: "5px 10px",
              fontSize: 12,
              cursor: "pointer",
              width: "100%",
            }}
          >
            Выйти
          </button>
        </div>
      </aside>

      <div className="content">
        <div className="content-inner">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/profile" element={<Profile />} />
            <Route path="/ozon/pricing" element={<PricingDashboard />} />
            <Route path="/ozon/cards" element={<CardGenerator />} />
            <Route path="/repair-orders" element={<RepairOrdersList />} />
            <Route path="/repair-orders/upload" element={<UploadPage />} />
            <Route path="/repair-orders/:repairOrderId/review" element={<ReviewMatches />} />
            {user.role === "admin" && <Route path="/admin/users" element={<Users />} />}
            {user.role === "admin" && <Route path="/admin/llm" element={<LlmSettings />} />}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/setup" element={<Setup />} />
      <Route path="/login" element={<Login />} />
      <Route path="/*" element={<ProtectedShell />} />
    </Routes>
  );
}
