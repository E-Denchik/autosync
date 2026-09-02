import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import UpdateChecker from "./components/UpdateChecker.jsx";
import UpdateProgressWindow from "./pages/UpdateProgressWindow.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import PricingDashboard from "./pages/ozon/PricingDashboard.jsx";
import CardGenerator from "./pages/ozon/CardGenerator.jsx";
import Stats from "./pages/ozon/Stats.jsx";
import UploadPage from "./pages/repair-orders/UploadPage.jsx";
import ReviewMatches from "./pages/repair-orders/ReviewMatches.jsx";
import RepairOrdersList from "./pages/repair-orders/RepairOrdersList.jsx";
import LlmSettings from "./pages/admin/LlmSettings.jsx";
import VsegptStats from "./pages/admin/VsegptStats.jsx";
import History from "./pages/admin/History.jsx";
import Integrations from "./pages/admin/Integrations.jsx";
import Contragents from "./pages/admin/Contragents.jsx";
import LaborCatalog from "./pages/admin/LaborCatalog.jsx";
import NomenclatureCatalog from "./pages/admin/NomenclatureCatalog.jsx";
import BrandAliases from "./pages/admin/BrandAliases.jsx";
import DocumentTemplates from "./pages/admin/DocumentTemplates.jsx";
import CompanyProfile from "./pages/admin/CompanyProfile.jsx";
import ContractCatalogs from "./pages/admin/ContractCatalogs.jsx";
import ContractCatalogDetail from "./pages/admin/ContractCatalogDetail.jsx";
import ErrorLog from "./pages/admin/ErrorLog.jsx";
import { useErrorLog } from "./context/ErrorLogContext.jsx";
import {
  HomeIcon,
  TagIcon,
  SparklesIcon,
  ListIcon,
  UploadIcon,
  UsersIcon,
  CpuIcon,
  HistoryIcon,
  PlugIcon,
  TrendingUpIcon,
  ClockIcon,
  BoxIcon,
  FileTextIcon,
  AlertCircleIcon,
} from "./components/icons.jsx";

export default function App() {
  const location = useLocation();
  const errorLog = useErrorLog();

  // Отдельное системное окно прогресса обновления открывается на этот же
  // адрес (см. native_app.py: open_update_window) — своя, "голая" страница
  // без сайдбара/навигации остального приложения, это отдельное окно ОС,
  // а не раздел SPA.
  if (location.pathname === "/update-progress") {
    return <UpdateProgressWindow />;
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
          <NavLink to="/ozon/stats">
            <TrendingUpIcon /> Статистика
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

        <div className="module-label">Администрирование</div>
        <nav>
          <NavLink to="/admin/contragents">
            <UsersIcon /> Контрагенты
          </NavLink>
          <NavLink to="/admin/contracts">
            <FileTextIcon /> Каталоги контрактов
          </NavLink>
          <NavLink to="/admin/labor-catalog">
            <ClockIcon /> Нормо-часы
          </NavLink>
          <NavLink to="/admin/nomenclature">
            <BoxIcon /> Номенклатура
          </NavLink>
          <NavLink to="/admin/brand-aliases">
            <TagIcon /> Марки автомобилей
          </NavLink>
          <NavLink to="/admin/document-templates">
            <FileTextIcon /> Шаблоны документов
          </NavLink>
          <NavLink to="/admin/company-profile">
            <FileTextIcon /> Реквизиты компании
          </NavLink>
          <NavLink to="/admin/llm">
            <CpuIcon /> LLM-модель
          </NavLink>
          <NavLink to="/admin/vsegpt-stats">
            <TrendingUpIcon /> Статистика vsegpt
          </NavLink>
          <NavLink to="/admin/integrations">
            <PlugIcon /> Интеграции
          </NavLink>
          <NavLink to="/admin/history">
            <HistoryIcon /> История
          </NavLink>
          <NavLink to="/admin/errors">
            <AlertCircleIcon /> Журнал ошибок
            {errorLog.unreadCount > 0 && <span className="nav-badge">{errorLog.unreadCount}</span>}
          </NavLink>
        </nav>

        <div className="sidebar-footer">
          <UpdateChecker />
        </div>
      </aside>

      <div className="content">
        <div className="content-inner">
          <ErrorBoundary
            key={location.pathname}
            onError={(error) => errorLog.log(error?.message || String(error), "react-render")}
          >
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/ozon/pricing" element={<PricingDashboard />} />
            <Route path="/ozon/cards" element={<CardGenerator />} />
            <Route path="/ozon/stats" element={<Stats />} />
            <Route path="/repair-orders" element={<RepairOrdersList />} />
            <Route path="/repair-orders/upload" element={<UploadPage />} />
            <Route path="/repair-orders/:repairOrderId/review" element={<ReviewMatches />} />
            <Route path="/admin/contragents" element={<Contragents />} />
            <Route path="/admin/contracts" element={<ContractCatalogs />} />
            <Route path="/admin/contracts/:contractId" element={<ContractCatalogDetail />} />
            <Route path="/admin/labor-catalog" element={<LaborCatalog />} />
            <Route path="/admin/nomenclature" element={<NomenclatureCatalog />} />
            <Route path="/admin/brand-aliases" element={<BrandAliases />} />
            <Route path="/admin/document-templates" element={<DocumentTemplates />} />
            <Route path="/admin/company-profile" element={<CompanyProfile />} />
            <Route path="/admin/llm" element={<LlmSettings />} />
            <Route path="/admin/vsegpt-stats" element={<VsegptStats />} />
            <Route path="/admin/integrations" element={<Integrations />} />
            <Route path="/admin/history" element={<History />} />
            <Route path="/admin/errors" element={<ErrorLog />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          </ErrorBoundary>
        </div>
      </div>
    </div>
  );
}
