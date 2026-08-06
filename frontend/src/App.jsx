import { NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import PricingDashboard from "./pages/ozon/PricingDashboard.jsx";
import CardGenerator from "./pages/ozon/CardGenerator.jsx";
import UploadPage from "./pages/repair-orders/UploadPage.jsx";
import ReviewMatches from "./pages/repair-orders/ReviewMatches.jsx";
import RepairOrdersList from "./pages/repair-orders/RepairOrdersList.jsx";
import { HomeIcon, TagIcon, SparklesIcon, ListIcon, UploadIcon } from "./components/icons.jsx";

export default function App() {
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

        <div className="sidebar-footer">
          Внутренняя платформа автосервиса.
          <br />
          Человек в контуре на ценах и сопоставлениях.
        </div>
      </aside>

      <div className="content">
        <div className="content-inner">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/ozon/pricing" element={<PricingDashboard />} />
            <Route path="/ozon/cards" element={<CardGenerator />} />
            <Route path="/repair-orders" element={<RepairOrdersList />} />
            <Route path="/repair-orders/upload" element={<UploadPage />} />
            <Route path="/repair-orders/:repairOrderId/review" element={<ReviewMatches />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}
