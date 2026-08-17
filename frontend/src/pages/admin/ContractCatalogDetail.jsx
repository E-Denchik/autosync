import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import StatusPill from "../../components/StatusPill.jsx";
import Pagination from "../../components/Pagination.jsx";
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
  const toast = useToast();

  const loadContract = () => {
    api
      .getContract(contractId)
      .then(setContract)
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
      </div>

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

      {contract.repair_orders_count > 0 && (
        <div className="text-muted" style={{ marginTop: 16, fontSize: 12.5, display: "flex", alignItems: "center", gap: 4 }}>
          Используется в {contract.repair_orders_count} заказ-наряде(ах) <ChevronRightIcon style={{ width: 12, height: 12 }} />
        </div>
      )}
    </div>
  );
}
