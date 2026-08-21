import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "../context/ToastContext.jsx";

export default function RepairOrderEditModal({ order, onClose, onSaved }) {
  const [contragents, setContragents] = useState([]);
  const [contragentId, setContragentId] = useState(order.contragent_id ? String(order.contragent_id) : "");
  const [vehicleMake, setVehicleMake] = useState(order.vehicle_make || "");
  const [vehicleModel, setVehicleModel] = useState(order.vehicle_model || "");
  const [vehicleYear, setVehicleYear] = useState(order.vehicle_year || "");
  const [vehicleVin, setVehicleVin] = useState(order.vehicle_vin || "");
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  useEffect(() => {
    api.listContragents().then(setContragents).catch(() => {});
  }, []);

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const updated = await api.updateRepairOrder(order.id, {
        contragent_id: contragentId || null,
        vehicle_make: vehicleMake,
        vehicle_model: vehicleModel,
        vehicle_year: vehicleYear || null,
        vehicle_vin: vehicleVin,
      });
      toast.success("Заказ-наряд обновлён");
      onSaved(updated);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
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
      <form className="panel" style={{ width: 420 }} onClick={(e) => e.stopPropagation()} onSubmit={handleSave}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
          <div>
            <div style={{ fontWeight: 650, fontSize: 14.5 }}>Изменить заказ-наряд</div>
            <div className="text-muted" style={{ fontSize: 12.5, marginTop: 4 }}>
              {order.original_filename}
            </div>
          </div>
          <button type="button" className="btn btn-secondary btn-sm" onClick={onClose}>
            Закрыть
          </button>
        </div>

        <div className="field">
          <label htmlFor="re-contragent">Контрагент</label>
          <select id="re-contragent" value={contragentId} onChange={(e) => setContragentId(e.target.value)}>
            <option value="">— не выбран —</option>
            {contragents.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.hourly_rate} ₽/ч)
              </option>
            ))}
          </select>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div className="field">
            <label htmlFor="re-make">Марка</label>
            <input id="re-make" value={vehicleMake} onChange={(e) => setVehicleMake(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="re-model">Модель</label>
            <input id="re-model" value={vehicleModel} onChange={(e) => setVehicleModel(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="re-year">Год выпуска</label>
            <input id="re-year" type="number" value={vehicleYear} onChange={(e) => setVehicleYear(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="re-vin">VIN</label>
            <input id="re-vin" value={vehicleVin} onChange={(e) => setVehicleVin(e.target.value)} />
          </div>
        </div>

        <p className="text-muted" style={{ fontSize: 12, marginTop: -4 }}>
          Уже сопоставленные позиции и работы это не пересчитает — их можно поправить по отдельности
          на странице проверки.
        </p>

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={saving}>
            Отмена
          </button>
          <button className="btn btn-primary" disabled={saving} type="submit">
            {saving ? "Сохранение…" : "Сохранить"}
          </button>
        </div>
      </form>
    </div>
  );
}
