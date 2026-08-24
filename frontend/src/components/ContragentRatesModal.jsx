import { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "../context/ToastContext.jsx";
import { UploadIcon } from "./icons.jsx";

export default function ContragentRatesModal({ contragent, onClose }) {
  const [rates, setRates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ vehicle_make: "", hourly_rate: "" });
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const fileInputRef = useRef(null);
  const toast = useToast();

  const load = () => {
    setLoading(true);
    api
      .listContragentHourlyRates(contragent.id)
      .then(setRates)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleAdd = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.createContragentHourlyRate(contragent.id, form);
      setForm({ vehicle_make: "", hourly_rate: "" });
      load();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (rateId) => {
    try {
      await api.deleteContragentHourlyRate(contragent.id, rateId);
      setRates((prev) => prev.filter((r) => r.id !== rateId));
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleFilePicked = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setImporting(true);
    try {
      const result = await api.importContragentHourlyRates(contragent.id, file);
      toast.success(
        `Загружено: ${result.created} новых, ${result.updated} обновлено (всего строк в файле: ${result.total})`
      );
      load();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setImporting(false);
    }
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(10, 11, 16, 0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 200,
      }}
      onClick={onClose}
    >
      <div className="panel" style={{ width: 480 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
          <div>
            <div style={{ fontWeight: 650, fontSize: 14.5 }}>Ставки по маркам — {contragent.name}</div>
            <div className="text-muted" style={{ fontSize: 12.5, marginTop: 4 }}>
              Если для марки заказ-наряда задана ставка здесь, она используется вместо общей ставки контрагента
              ({contragent.hourly_rate} ₽/ч).
            </div>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={onClose}>
            Закрыть
          </button>
        </div>

        <form onSubmit={handleAdd} style={{ display: "flex", gap: 8, alignItems: "flex-end", marginBottom: 16 }}>
          <div className="field" style={{ flex: 1 }}>
            <label htmlFor="cr-make">Марка</label>
            <input
              id="cr-make"
              required
              value={form.vehicle_make}
              onChange={(e) => setForm((f) => ({ ...f, vehicle_make: e.target.value }))}
              placeholder="Например, VOLKSWAGEN"
            />
          </div>
          <div className="field" style={{ width: 140 }}>
            <label htmlFor="cr-value">Ставка, ₽/ч</label>
            <input
              id="cr-value"
              type="number"
              min="0"
              step="0.01"
              required
              value={form.hourly_rate}
              onChange={(e) => setForm((f) => ({ ...f, hourly_rate: e.target.value }))}
            />
          </div>
          <button className="btn btn-primary" disabled={saving} type="submit">
            {saving ? "…" : "Добавить"}
          </button>
        </form>

        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            disabled={importing}
            onClick={() => fileInputRef.current?.click()}
          >
            <UploadIcon style={{ width: 13, height: 13 }} /> {importing ? "Загрузка…" : "Загрузить файлом"}
          </button>
          <span className="text-muted" style={{ fontSize: 12 }}>
            Excel/CSV со столбцами «Марка» и «Ставка» — названия колонок могут быть любыми, система сама
            их распознаёт. Марка, которая уже есть в списке, обновится, а не задвоится.
          </span>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xlsm,.xls,.ods,.csv"
            style={{ display: "none" }}
            onChange={handleFilePicked}
          />
        </div>

        {loading ? (
          <div className="text-muted" style={{ fontSize: 13 }}>
            Загрузка…
          </div>
        ) : rates.length === 0 ? (
          <p className="text-muted" style={{ margin: 0 }}>
            Ставок по маркам пока нет — используется общая ставка контрагента.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Марка</th>
                <th>Ставка, ₽/ч</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rates.map((r) => (
                <tr key={r.id}>
                  <td>{r.vehicle_make}</td>
                  <td>{r.hourly_rate}</td>
                  <td>
                    <div style={{ display: "flex", justifyContent: "flex-end" }}>
                      <button className="btn btn-reject btn-sm" onClick={() => handleDelete(r.id)}>
                        Удалить
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
