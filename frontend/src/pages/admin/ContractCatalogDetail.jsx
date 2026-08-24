import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import StatusPill from "../../components/StatusPill.jsx";
import Pagination from "../../components/Pagination.jsx";
import HowToUse from "../../components/HowToUse.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { SearchIcon, UploadIcon, ChevronRightIcon } from "../../components/icons.jsx";

const PER_PAGE = 50;

export default function ContractCatalogDetail() {
  const { contractId } = useParams();
  const [contract, setContract] = useState(null);
  const [tab, setTab] = useState("parts");
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [hourlyRates, setHourlyRates] = useState([]);
  const [rateForm, setRateForm] = useState({ vehicle_make: "", vehicle_model: "", hourly_rate: "" });
  const [savingRate, setSavingRate] = useState(false);
  const [importingRates, setImportingRates] = useState(false);
  const rateFileInputRef = useRef(null);
  const toast = useToast();

  const loadContract = () => {
    api
      .getContract(contractId)
      .then(setContract)
      .catch((e) => toast.error(e.message));
  };

  const loadHourlyRates = () => {
    api
      .listContractHourlyRates(contractId)
      .then(setHourlyRates)
      .catch((e) => toast.error(e.message));
  };

  const loadRows = (t = tab, q = query, p = page) => {
    setLoading(true);
    const call = t === "parts" ? api.listContractParts : api.listContractLaborNorms;
    call(contractId, { q, page: p, per_page: PER_PAGE })
      .then(({ items, total: total2 }) => {
        setRows(items);
        setTotal(total2);
      })
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadContract();
    loadHourlyRates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contractId]);

  useEffect(() => {
    setPage(1);
    setQuery("");
    loadRows(tab, "", 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, contractId]);

  const handleSearch = (e) => {
    e.preventDefault();
    setPage(1);
    loadRows(tab, query, 1);
  };

  const handlePageChange = (p) => {
    setPage(p);
    loadRows(tab, query, p);
  };

  const handleAddRate = async (e) => {
    e.preventDefault();
    setSavingRate(true);
    try {
      await api.createContractHourlyRate(contractId, rateForm);
      toast.success("Ставка добавлена");
      setRateForm({ vehicle_make: "", vehicle_model: "", hourly_rate: "" });
      loadHourlyRates();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSavingRate(false);
    }
  };

  const handleRateFilePicked = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setImportingRates(true);
    try {
      const result = await api.importContractHourlyRates(contractId, file);
      toast.success(
        `Загружено: ${result.created} новых, ${result.updated} обновлено (всего строк в файле: ${result.total})`
      );
      loadHourlyRates();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setImportingRates(false);
    }
  };

  const handleDeleteRate = async (rateId) => {
    try {
      await api.deleteContractHourlyRate(contractId, rateId);
      setHourlyRates((prev) => prev.filter((r) => r.id !== rateId));
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleUpload = async (e) => {
    const selected = Array.from(e.target.files);
    e.target.value = "";
    if (selected.length === 0) return;
    setUploading(true);
    try {
      await api.importMoreIntoContract(contractId, selected);
      toast.success("Файл(ы) добавлены — идёт разбор");
      loadContract();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setUploading(false);
    }
  };

  if (!contract) return <Spinner label="Загрузка…" />;

  return (
    <div>
      <div className="page-header">
        <div>
          <Link to="/admin/contracts" className="text-muted" style={{ fontSize: 12.5 }}>
            ← Все каталоги контрактов
          </Link>
          <h2 style={{ marginTop: 4 }}>{contract.name || contract.original_filename}</h2>
          <p>
            {contract.contragent_name && <>Контрагент: {contract.contragent_name} · </>}
            Запчастей: {contract.parts_count} · Нормо-часов: {contract.labor_norms_count} · Заказ-нарядов:{" "}
            {contract.repair_orders_count} · <StatusPill status={contract.status} />
          </p>
        </div>
        <label className="btn btn-secondary" style={{ cursor: uploading ? "default" : "pointer" }}>
          <UploadIcon /> {uploading ? "Загрузка…" : "Добавить ещё файл(ы)"}
          <input
            type="file"
            multiple
            accept=".xlsx,.xlsm,.xls,.ods,.csv,.docx,.pdf,.jpg,.jpeg,.png"
            onChange={handleUpload}
            disabled={uploading}
            style={{ display: "none" }}
          />
        </label>
      </div>

      <HowToUse
        steps={[
          "Вкладки переключают между списком запчастей, нормо-часов и ставок по маркам этого контракта.",
          "«Добавить ещё файл(ы)» дозагружает данные в этот же контракт, не создавая новый.",
          "Ставка на вкладке «Ставки по маркам» перекрывает общую ставку контрагента для заказ-нарядов этой марки — задавайте её, только если нужна цена нормо-часа, отличная от обычной.",
        ]}
      />

      {contract.error_message && (
        <div className="hint-banner hint-warning" style={{ marginBottom: 16 }}>
          {contract.error_message}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <button
          className={tab === "parts" ? "btn btn-primary btn-sm" : "btn btn-secondary btn-sm"}
          onClick={() => setTab("parts")}
        >
          Запчасти ({contract.parts_count})
        </button>
        <button
          className={tab === "labor" ? "btn btn-primary btn-sm" : "btn btn-secondary btn-sm"}
          onClick={() => setTab("labor")}
        >
          Нормо-часы ({contract.labor_norms_count})
        </button>
        <button
          className={tab === "rates" ? "btn btn-primary btn-sm" : "btn btn-secondary btn-sm"}
          onClick={() => setTab("rates")}
        >
          Ставки по маркам ({hourlyRates.length})
        </button>
      </div>

      {tab === "rates" ? (
        <div className="panel" style={{ maxWidth: 600 }}>
          <p className="text-muted" style={{ marginTop: 0, fontSize: 12.5 }}>
            Цена нормо-часа для этого контракта по маркам (и, если задано, моделям) ТС — если для марки/модели
            заказ-наряда есть ставка здесь, она используется вместо общей ставки контрагента. Ставка по
            конкретной модели важнее ставки на всю марку без модели.
          </p>
          <form onSubmit={handleAddRate} style={{ display: "flex", gap: 8, alignItems: "flex-end", marginBottom: 16 }}>
            <div className="field" style={{ flex: 1 }}>
              <label htmlFor="rate-make">Марка</label>
              <input
                id="rate-make"
                required
                value={rateForm.vehicle_make}
                onChange={(e) => setRateForm((f) => ({ ...f, vehicle_make: e.target.value }))}
                placeholder="Например, HYUNDAI"
              />
            </div>
            <div className="field" style={{ flex: 1 }}>
              <label htmlFor="rate-model">Модель (необязательно)</label>
              <input
                id="rate-model"
                value={rateForm.vehicle_model}
                onChange={(e) => setRateForm((f) => ({ ...f, vehicle_model: e.target.value }))}
                placeholder="Например, IX35"
              />
            </div>
            <div className="field" style={{ width: 130 }}>
              <label htmlFor="rate-value">Ставка, ₽/ч</label>
              <input
                id="rate-value"
                type="number"
                min="0"
                step="0.01"
                required
                value={rateForm.hourly_rate}
                onChange={(e) => setRateForm((f) => ({ ...f, hourly_rate: e.target.value }))}
              />
            </div>
            <button className="btn btn-primary" disabled={savingRate} type="submit">
              {savingRate ? "…" : "Добавить"}
            </button>
          </form>

          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={importingRates}
              onClick={() => rateFileInputRef.current?.click()}
            >
              <UploadIcon style={{ width: 13, height: 13 }} /> {importingRates ? "Загрузка…" : "Загрузить файлом"}
            </button>
            <span className="text-muted" style={{ fontSize: 12 }}>
              Excel/CSV/Word/PDF со столбцами «Марка» (можно сразу с моделью, в том числе несколько через
              запятую на одну ставку) и «Цена» — названия колонок могут быть любыми. Подойдёт и фото/скан
              бумажной таблицы. Марка (и модель), которая уже есть в списке, обновится, а не задвоится.
            </span>
            <input
              ref={rateFileInputRef}
              type="file"
              accept=".xlsx,.xlsm,.xls,.ods,.csv,.docx,.pdf,.jpg,.jpeg,.png,.bmp,.tiff,.tif"
              style={{ display: "none" }}
              onChange={handleRateFilePicked}
            />
          </div>

          {hourlyRates.length === 0 ? (
            <p className="text-muted">Ставок пока нет — используется общая ставка контрагента.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Марка</th>
                  <th>Модель</th>
                  <th>Ставка, ₽/ч</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {hourlyRates.map((r) => (
                  <tr key={r.id}>
                    <td>{r.vehicle_make}</td>
                    <td className="text-muted">{r.vehicle_model || "любая"}</td>
                    <td>{r.hourly_rate}</td>
                    <td>
                      <button className="btn btn-reject btn-sm" onClick={() => handleDeleteRate(r.id)}>
                        Удалить
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : (
        <>
          <form onSubmit={handleSearch} style={{ marginBottom: 16, maxWidth: 360 }}>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={tab === "parts" ? "Поиск по артикулу/названию" : "Поиск по операции"}
              />
              <button className="btn btn-secondary" type="submit">
                <SearchIcon />
              </button>
            </div>
          </form>

          {loading ? (
            <Spinner label="Загрузка…" />
          ) : rows.length === 0 ? (
            <div className="table-wrap">
              <EmptyState title="Ничего не найдено" hint="Попробуйте другой запрос или загрузите файл выше." />
            </div>
          ) : tab === "parts" ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Артикул</th>
                    <th>Наименование</th>
                    <th>Кол-во</th>
                    <th>Цена</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((p) => (
                    <tr key={p.id}>
                      <td>{p.article || "—"}</td>
                      <td>{p.name}</td>
                      <td className="text-muted">{p.qty ?? "—"}</td>
                      <td className="text-muted">{p.price ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Pagination page={page} perPage={PER_PAGE} total={total} onPageChange={handlePageChange} />
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Операция</th>
                    <th>Марка</th>
                    <th>Модель</th>
                    <th>Норма, ч</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((n) => (
                    <tr key={n.id}>
                      <td>{n.operation_name}</td>
                      <td className="text-muted">{n.vehicle_make || "—"}</td>
                      <td className="text-muted">{n.vehicle_model || "—"}</td>
                      <td className="text-muted">{n.norm_hours}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Pagination page={page} perPage={PER_PAGE} total={total} onPageChange={handlePageChange} />
            </div>
          )}
        </>
      )}

      {contract.repair_orders_count > 0 && (
        <div className="text-muted" style={{ marginTop: 16, fontSize: 12.5, display: "flex", alignItems: "center", gap: 4 }}>
          Используется в {contract.repair_orders_count} заказ-наряде(ах) <ChevronRightIcon style={{ width: 12, height: 12 }} />
        </div>
      )}
    </div>
  );
}
