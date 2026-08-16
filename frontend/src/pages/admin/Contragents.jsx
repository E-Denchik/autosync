import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import ConfirmDialog from "../../components/ConfirmDialog.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { PlusIcon, EditIcon } from "../../components/icons.jsx";

const EMPTY_FORM = { name: "", hourly_rate: "", notes: "" };

export default function Contragents() {
  const [contragents, setContragents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [creating, setCreating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [editingRateId, setEditingRateId] = useState(null);
  const [rateInput, setRateInput] = useState("");
  const [savingRate, setSavingRate] = useState(false);
  const toast = useToast();

  const load = () => {
    setLoading(true);
    api
      .listContragents()
      .then(setContragents)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleCreate = async (e) => {
    e.preventDefault();
    setCreating(true);
    try {
      await api.createContragent(form);
      toast.success("Контрагент добавлен");
      setForm(EMPTY_FORM);
      setShowForm(false);
      load();
    } catch (e2) {
      toast.error(e2.message);
    } finally {
      setCreating(false);
    }
  };

  const startEditRate = (c) => {
    setEditingRateId(c.id);
    setRateInput(c.hourly_rate);
  };

  const saveRate = async (id) => {
    setSavingRate(true);
    try {
      const updated = await api.updateContragent(id, { hourly_rate: Number(rateInput) });
      setContragents((prev) => prev.map((c) => (c.id === id ? updated : c)));
      setEditingRateId(null);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSavingRate(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await api.deleteContragent(deleteTarget.id);
      setContragents((prev) => prev.filter((c) => c.id !== deleteTarget.id));
      toast.success(`Контрагент «${deleteTarget.name}» удалён`);
      setDeleteTarget(null);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Контрагенты</h2>
          <p>Договорная ставка за нормо-час — используется при расчёте стоимости работ в заказ-нарядах.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowForm((v) => !v)}>
          <PlusIcon /> Добавить контрагента
        </button>
      </div>

      {showForm && (
        <form className="panel" style={{ marginBottom: 20, maxWidth: 420 }} onSubmit={handleCreate}>
          <div className="field">
            <label htmlFor="name">Название</label>
            <input
              id="name"
              required
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="hourly_rate">Ставка за нормо-час, ₽</label>
            <input
              id="hourly_rate"
              type="number"
              min="0"
              step="0.01"
              required
              value={form.hourly_rate}
              onChange={(e) => setForm((f) => ({ ...f, hourly_rate: e.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="notes">Заметки</label>
            <input
              id="notes"
              value={form.notes}
              onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
            />
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-primary" disabled={creating} type="submit">
              {creating ? "Сохранение…" : "Создать"}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setShowForm(false)}>
              Отмена
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <Spinner label="Загрузка…" />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Название</th>
                <th>Ставка, ₽/ч</th>
                <th>Заметки</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {contragents.map((c) => (
                <tr key={c.id}>
                  <td>{c.name}</td>
                  <td>
                    {editingRateId === c.id ? (
                      <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          autoFocus
                          disabled={savingRate}
                          value={rateInput}
                          onChange={(e) => setRateInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") saveRate(c.id);
                            if (e.key === "Escape") setEditingRateId(null);
                          }}
                          style={{ width: 88, padding: "4px 6px", fontSize: 13 }}
                        />
                        <button
                          className="btn btn-primary btn-sm"
                          disabled={savingRate}
                          onClick={() => saveRate(c.id)}
                        >
                          OK
                        </button>
                      </div>
                    ) : (
                      <span
                        onClick={() => startEditRate(c)}
                        title="Изменить ставку"
                        style={{
                          cursor: "pointer",
                          borderBottom: "1px dashed var(--border-strong)",
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 4,
                        }}
                      >
                        {c.hourly_rate}
                        <EditIcon style={{ width: 11, height: 11, opacity: 0.6 }} />
                      </span>
                    )}
                  </td>
                  <td className="text-muted">{c.notes || "—"}</td>
                  <td>
                    <div style={{ display: "flex", justifyContent: "flex-end" }}>
                      <button className="btn btn-reject btn-sm" onClick={() => setDeleteTarget(c)}>
                        Удалить
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deleteTarget && (
        <ConfirmDialog
          title="Удалить контрагента?"
          message={
            <>
              Контрагент <strong>{deleteTarget.name}</strong> будет удалён безвозвратно.
            </>
          }
          confirmLabel="Удалить"
          danger
          busy={deleting}
          onConfirm={handleDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}
