import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client.js";
import StatCard from "../components/StatCard.jsx";
import Spinner from "../components/Spinner.jsx";
import EmptyState from "../components/EmptyState.jsx";
import StatusPill from "../components/StatusPill.jsx";
import { useToast } from "../context/ToastContext.jsx";
import { useAuth } from "../context/AuthContext.jsx";
import {
  TagIcon,
  FileTextIcon,
  ListIcon,
  TrendingUpIcon,
  UploadIcon,
  SparklesIcon,
  UsersIcon,
  CpuIcon,
  ChevronRightIcon,
  AlertCircleIcon,
  InboxIcon,
} from "../components/icons.jsx";

const PROVIDER_LABELS = { ollama: "Ollama", lmstudio: "LM Studio" };

export default function Dashboard() {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const toast = useToast();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  useEffect(() => {
    api
      .dashboardSummary()
      .then(setSummary)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Обзор</h2>
          <p>Что происходит в AutoSync прямо сейчас — цены, ожидающие решения, и заказ-наряды в обработке.</p>
        </div>
      </div>

      {loading ? (
        <Spinner label="Загрузка сводки…" />
      ) : !summary ? (
        <p className="text-muted" style={{ fontSize: 13.5 }}>
          Не удалось загрузить сводку. Попробуйте обновить страницу.
        </p>
      ) : (
        <>
          {isAdmin && !summary.llm_model && (
            <div className="hint-banner hint-warning">
              <AlertCircleIcon />
              <span>
                LLM-модель ещё не выбрана — предложения по цене, генерация карточек и фоллбэк
                сопоставления запчастей недоступны. <Link to="/admin/llm">Выбрать модель →</Link>
              </span>
            </div>
          )}

          <div className="stat-grid">
            <StatCard
              icon={TrendingUpIcon}
              label="Предложений по цене ждут решения"
              value={summary.pending_price_suggestions}
              to="/ozon/pricing"
            />
            <StatCard icon={TagIcon} label="Товаров в каталоге" value={summary.products_total} to="/ozon/cards" />
            <StatCard
              icon={FileTextIcon}
              label="Заказ-нарядов нужно проверить"
              value={summary.repair_orders_needs_review}
              to="/repair-orders"
            />
            <StatCard
              icon={ListIcon}
              label="Позиций сопоставления ждут решения"
              value={summary.pending_part_matches}
              to="/repair-orders"
            />
          </div>

          <div className="two-col-grid">
            <div className="panel">
              <div className="panel-header">
                <h3>Последние заказ-наряды</h3>
                <Link to="/repair-orders">
                  Все заказ-наряды <ChevronRightIcon />
                </Link>
              </div>

              {summary.recent_repair_orders.length === 0 ? (
                <EmptyState
                  icon={FileTextIcon}
                  title="Пока нет загруженных заказ-нарядов"
                  hint="Загрузите договор и заказ-наряд, чтобы автоматически сопоставить позиции."
                />
              ) : (
                <div className="activity-list">
                  {summary.recent_repair_orders.map((o) => (
                    <Link key={o.id} to={`/repair-orders/${o.id}/review`} className="activity-row">
                      <div className="activity-main">
                        <div className="activity-title">{o.original_filename}</div>
                        <div className="activity-sub">
                          {o.matches_total > 0
                            ? `сопоставлено ${o.matches_total - o.matches_pending} из ${o.matches_total}`
                            : "ещё обрабатывается"}
                          {" · "}
                          {new Date(o.created_at).toLocaleDateString("ru-RU")}
                        </div>
                      </div>
                      <div className="activity-meta">
                        <StatusPill status={o.status} />
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </div>

            <div className="panel">
              <div className="panel-header">
                <h3>Предложения по цене</h3>
                <Link to="/ozon/pricing">
                  Все предложения <ChevronRightIcon />
                </Link>
              </div>

              {summary.recent_price_suggestions.length === 0 ? (
                <EmptyState icon={InboxIcon} title="Нет предложений, ожидающих решения" />
              ) : (
                <div className="activity-list">
                  {summary.recent_price_suggestions.map((s) => (
                    <Link key={s.id} to="/ozon/pricing" className="activity-row">
                      <div className="activity-main">
                        <div className="activity-title">{s.product_name || s.product_sku || "Товар"}</div>
                        <div className="activity-sub">
                          {s.own_price != null ? `сейчас ${s.own_price} ₽` : "цена не указана"}
                        </div>
                      </div>
                      <div className="activity-meta">
                        {s.suggested_price != null && (
                          <strong style={{ fontSize: 13.5 }}>{s.suggested_price} ₽</strong>
                        )}
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      <div className="section-title">Быстрые действия</div>
      <div className="action-grid">
        <Link to="/repair-orders/upload" className="action-card">
          <div className="action-icon">
            <UploadIcon />
          </div>
          <div>
            <div className="action-title">Загрузить документы</div>
            <div className="action-desc">Договор и заказ-наряд — позиции сопоставятся автоматически.</div>
          </div>
        </Link>

        <Link to="/ozon/cards" className="action-card">
          <div className="action-icon">
            <SparklesIcon />
          </div>
          <div>
            <div className="action-title">Сгенерировать карточку</div>
            <div className="action-desc">SEO-текст и характеристики на основе конкурентов.</div>
          </div>
        </Link>

        {isAdmin && (
          <Link to="/admin/llm" className="action-card">
            <div className="action-icon">
              <CpuIcon />
            </div>
            <div>
              <div className="action-title">LLM-модель</div>
              <div className="action-desc">
                {summary?.llm_model
                  ? `Сейчас: ${summary.llm_model.model} (${PROVIDER_LABELS[summary.llm_model.provider] || summary.llm_model.provider})`
                  : "Выбрать модель из скачанных на этой машине."}
              </div>
            </div>
          </Link>
        )}

        {isAdmin && (
          <Link to="/admin/users" className="action-card">
            <div className="action-icon">
              <UsersIcon />
            </div>
            <div>
              <div className="action-title">Пользователи</div>
              <div className="action-desc">Выдать или отозвать доступ к AutoSync.</div>
            </div>
          </Link>
        )}
      </div>
    </div>
  );
}
