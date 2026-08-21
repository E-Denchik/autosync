import { useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "../context/ToastContext.jsx";

export default function ContragentEditModal({ contragent, onClose, onSaved }) {
  const [name, setName] = useState(contragent.name);
  const [hourlyRate, setHourlyRate] = useState(contragent.hourly_rate);
  const [notes, setNotes] = useState(contragent.notes || "");
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const updated = await api.updateContragent(contragent.id, {
        name,
        hourly_rate: Number(hourlyRate),
        notes,
      });
      toast.success("Контрагент обновлён");
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
      <form className="panel" style={{ width: 400 }} onClick={(e) => e.stopPropagation()} onSubmit={handleSave}>
        <div style={{ fontWeight: 650, fontSize: 14.5, marginBottom: 14 }}>Изменить контрагента</div>

        <div className="field">
          <label htmlFor="ce-name">Название</label>
          <input id="ce-name" required value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="ce-rate">Ставка за нормо-час, ₽</label>
          <input
            id="ce-rate"
            type="number"
            min="0"
            step="0.01"
            required
            value={hourlyRate}
            onChange={(e) => setHourlyRate(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="ce-notes">Заметки</label>
          <input id="ce-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>

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
