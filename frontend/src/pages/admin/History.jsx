import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { ListIcon, SearchIcon } from "../../components/icons.jsx";

const ENTITY_LABELS = {
  part_match: "Сопоставление",
  repair_order: "Заказ-наряд",
  price_snapshot: "Предложение по цене",
  user: "Пользователь",
  llm_model_selection: "LLM-модель",
};

const ACTION_LABELS = {
  created: "создано",
  edited: "изменено",
  approved: "одобрено",
  rejected: "отклонено",
  deleted: "удалено",
  failed: "ошибка",
  needs_review: "нужна проверка",
  password_changed: "смена пароля",
  password_reset_by_admin: "сброс пароля админом",
  selected: "выбрана",
};

const EMPTY_FILTERS = {
  entity_type: "",
  action: "",
  actor_id: "",
  start_from: "",
  start_to: "",
  only_current: false,
};

export default function History() {
  const [entries, setEntries] = useState([]);
  const [entityTypes, setEntityTypes] = useState([]);
  const [users, setUsers] = useState([]);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  useEffect(() => {
    api.listHistoryEntityTypes().then(setEntityTypes).catch(() => {});
    api.listUsers().then(setUsers).catch(() => {});
  }, []);

  const load = (activeFilters) => {
    setLoading(true);
    api
      .listHistory({
        ...activeFilters,
        only_current: activeFilters.only_current ? "true" : undefined,
      })
      .then(setEntries)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => load(EMPTY_FILTERS), []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSearch = (e) => {
    e.preventDefault();
    load(filters);
  };

  const handleReset = () => {
    setFilters(EMPTY_FILTERS);
    load(EMPTY_FILTERS);
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>История</h2>
          <p>
            Журнал действий и изменений состояния — кто, когда и что сделал. Каждое изменение
            закрывает предыдущую запись и открывает новую, ничего не перезаписывается.
          </p>
        </div>
      </div>

      <form className="panel" style={{ marginBottom: 20 }} onSubmit={handleSearch}>
        <div className="filter-row">
          <div className="field">
            <label htmlFor="entity_type">Тип записи</label>
            <select
              id="entity_type"
              value={filters.entity_type}
              onChange={(e) => setFilters((f) => ({ ...f, entity_type: e.target.value }))}
            >
              <option value="">Все</option>
              {entityTypes.map((t) => (
                <option key={t} value={t}>
                  {ENTITY_LABELS[t] || t}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="action">Действие</label>
            <input
              id="action"
              placeholder="например, approved"
              value={filters.action}
              onChange={(e) => setFilters((f) => ({ ...f, action: e.target.value }))}
            />
          </div>

          <div className="field">
            <label htmlFor="actor_id">Кто сделал</label>
            <select
              id="actor_id"
              value={filters.actor_id}
              onChange={(e) => setFilters((f) => ({ ...f, actor_id: e.target.value }))}
            >
              <option value="">Все</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.email}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="start_from">С даты</label>
            <input
              id="start_from"
              type="date"
              value={filters.start_from}
              onChange={(e) => setFilters((f) => ({ ...f, start_from: e.target.value }))}
            />
          </div>

          <div className="field">
            <label htmlFor="start_to">По дату</label>
            <input
              id="start_to"
              type="date"
              value={filters.start_to}
              onChange={(e) => setFilters((f) => ({ ...f, start_to: e.target.value }))}
            />
          </div>
        </div>

        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, marginTop: 4 }}>
          <input
            type="checkbox"
            checked={filters.only_current}
            onChange={(e) => setFilters((f) => ({ ...f, only_current: e.target.checked }))}
          />
          Только текущее состояние (без истории изменений)
        </label>

        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <button className="btn btn-primary" type="submit">
            <SearchIcon /> Найти
          </button>
          <button type="button" className="btn btn-secondary" onClick={handleReset}>
            Сбросить
          </button>
        </div>
      </form>

      {loading ? (
        <Spinner label="Загрузка…" />
      ) : entries.length === 0 ? (
        <div className="table-wrap">
          <EmptyState icon={ListIcon} title="Ничего не найдено" hint="Попробуйте изменить фильтры." />
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Когда</th>
                <th>Кто</th>
                <th>Тип</th>
                <th>ID</th>
                <th>Действие</th>
                <th>Детали</th>
                <th>Действует по</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id}>
                  <td className="text-muted">{new Date(e.start_day).toLocaleString("ru-RU")}</td>
                  <td>{e.actor_email || "система"}</td>
                  <td>{ENTITY_LABELS[e.entity_type] || e.entity_type}</td>
                  <td className="text-muted">#{e.entity_id}</td>
                  <td>
                    <span className="status-pill">{ACTION_LABELS[e.action] || e.action}</span>
                  </td>
                  <td style={{ maxWidth: 320, color: "var(--text-muted)", fontSize: 12 }}>
                    {e.details ? JSON.stringify(e.details) : "—"}
                  </td>
                  <td className="text-muted">
                    {e.end_day ? new Date(e.end_day).toLocaleString("ru-RU") : "сейчас"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
