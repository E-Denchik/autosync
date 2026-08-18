import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import Pagination from "../../components/Pagination.jsx";
import HowToUse from "../../components/HowToUse.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { ListIcon, SearchIcon } from "../../components/icons.jsx";

const PER_PAGE = 50;

const ENTITY_LABELS = {
  part_match: "Сопоставление запчасти",
  labor_line: "Работа (нормо-часы)",
  repair_order: "Заказ-наряд",
  nomenclature_entry: "Номенклатура",
  nomenclature_import: "Импорт номенклатуры",
  price_snapshot: "Предложение по цене",
  product: "Товар",
  llm_model_selection: "LLM-модель",
  integration_keys: "Ключи интеграций",
};

const ACTION_LABELS = {
  created: "создано",
  edited: "изменено",
  updated: "обновлено",
  imported: "импортировано",
  approved: "одобрено",
  rejected: "отклонено",
  deleted: "удалено",
  failed: "ошибка",
  needs_review: "нужна проверка",
  selected: "выбрана",
  labor_matching_failed: "ошибка сопоставления работ",
  nomenclature_enrichment_failed: "ошибка обогащения номенклатурой",
};

const EMPTY_FILTERS = {
  entity_type: "",
  action: "",
  start_from: "",
  start_to: "",
  only_current: false,
};

export default function History() {
  const [entries, setEntries] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [entityTypes, setEntityTypes] = useState([]);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  useEffect(() => {
    api.listHistoryEntityTypes().then(setEntityTypes).catch(() => {});
  }, []);

  const load = (activeFilters, p = 1) => {
    setLoading(true);
    api
      .listHistory({
        ...activeFilters,
        only_current: activeFilters.only_current ? "true" : undefined,
        page: p,
        per_page: PER_PAGE,
      })
      .then(({ items, total: t }) => {
        setEntries(items);
        setTotal(t);
      })
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => load(EMPTY_FILTERS, 1), []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSearch = (e) => {
    e.preventDefault();
    setPage(1);
    load(filters, 1);
  };

  const handleReset = () => {
    setFilters(EMPTY_FILTERS);
    setPage(1);
    load(EMPTY_FILTERS, 1);
  };

  const handlePageChange = (p) => {
    setPage(p);
    load(filters, p);
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>История</h2>
          <p>
            Журнал действий и изменений состояния — когда и что сделано. Каждое изменение
            закрывает предыдущую запись и открывает новую, ничего не перезаписывается.
          </p>
        </div>
      </div>

      <HowToUse
        steps={[
          "Здесь журнал изменений состояния по всем разделам сразу — что изменилось и когда.",
          "Отфильтруйте по типу записи, действию или периоду дат, чтобы найти конкретное изменение.",
          "«Только текущее состояние» скрывает историю и показывает только последнее действие по каждой записи.",
        ]}
      />

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
          <Pagination page={page} perPage={PER_PAGE} total={total} onPageChange={handlePageChange} />
        </div>
      )}
    </div>
  );
}
