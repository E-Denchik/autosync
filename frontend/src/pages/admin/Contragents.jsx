import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import ConfirmDialog from "../../components/ConfirmDialog.jsx";
import ContragentRatesModal from "../../components/ContragentRatesModal.jsx";
import ContragentEditModal from "../../components/ContragentEditModal.jsx";
import HowToUse from "../../components/HowToUse.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { PlusIcon, EditIcon, ClockIcon, UploadIcon } from "../../components/icons.jsx";

const EMPTY_FORM = { name: "", hourly_rate: "", notes: "" };

export default function Contragents() {
  const [contragents, setContragents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [ratesFile, setRatesFile] = useState(null);
  const [creating, setCreating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [ratesTarget, setRatesTarget] = useState(null);
  const [editTarget, setEditTarget] = useState(null);
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
      const created = await api.createContragent(form);
      // Ставки по маркам файлом можно приложить сразу при создании — раньше
      // это было доступно только отдельным действием после ("Ставки по
      // маркам" у уже существующего контрагента), и с файлом ставок без
      // отдельного контрагента было не очевидно, куда его вообще грузить.
      if (ratesFile) {
        try {
          const result = await api.importContragentHourlyRates(created.id, ratesFile);
          toast.success(
            `Контрагент добавлен, ставки загружены: ${result.created} новых, ${result.updated} обновлено`
          );
        } catch (importErr) {
          toast.error(`Контрагент добавлен, но файл со ставками не загрузился: ${importErr.message}`);
        }
      } else {
        toast.success("Контрагент добавлен");
      }
      setForm(EMPTY_FORM);
      setRatesFile(null);
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
          <p>
            Договорная ставка за нормо-час — используется при расчёте стоимости работ в заказ-нарядах. Можно
            задать общую ставку и отдельные ставки по маркам ТС (кнопка «Ставки по маркам»).
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowForm((v) => !v)}>
          <PlusIcon /> Добавить контрагента
        </button>
      </div>

      <HowToUse
        steps={[
          "Добавьте контрагента (заказчика/организацию) с его общей ставкой за нормо-час — она подставится при загрузке заказ-наряда для расчёта стоимости работ.",
          "Ставку можно изменить в любой момент — кликните по значению в столбце «Ставка, ₽/ч».",
          "Если у контрагента разные ставки по маркам (например, Volkswagen — 800 ₽/ч, Toyota — 1200 ₽/ч), задайте их через «Ставки по маркам» — при загрузке заказ-наряда система сама подставит ставку по марке автомобиля, а не общую.",
        ]}
      />

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
          <div className="field">
            <label htmlFor="rates-file">
              <UploadIcon style={{ width: 12, height: 12 }} /> Ставки по маркам (файл, необязательно)
            </label>
            <input
              id="rates-file"
              type="file"
              accept=".xlsx,.xlsm,.xls,.ods,.csv,.docx,.pdf,.jpg,.jpeg,.png,.bmp,.tiff,.tif"
              onChange={(e) => setRatesFile(e.target.files?.[0] || null)}
            />
            <span className="text-muted" style={{ fontSize: 12 }}>
              Если для этого контрагента уже есть прайс-лист/таблица с ценами по маркам — приложите его сразу,
              не нужно потом искать «Ставки по маркам» отдельно. Excel/CSV/Word/PDF/фото — подойдёт любой формат
              со столбцами «Марка» и «Цена».
            </span>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-primary" disabled={creating} type="submit">
              {creating ? "Сохранение…" : "Создать"}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                setShowForm(false);
                setRatesFile(null);
              }}
            >
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
                    <div style={{ display: "flex", justifyContent: "flex-end", gap: 6 }}>
                      <button className="btn btn-secondary btn-sm" onClick={() => setRatesTarget(c)}>
                        <ClockIcon style={{ width: 13, height: 13 }} /> Ставки по маркам
                      </button>
                      <button
                        className="btn btn-secondary btn-sm"
                        title="Изменить название/ставку/заметки"
                        onClick={() => setEditTarget(c)}
                      >
                        <EditIcon style={{ width: 13, height: 13 }} />
                      </button>
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

      {ratesTarget && <ContragentRatesModal contragent={ratesTarget} onClose={() => setRatesTarget(null)} />}

      {editTarget && (
        <ContragentEditModal
          contragent={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={(updated) => {
            setContragents((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
            setEditTarget(null);
          }}
        />
      )}
    </div>
  );
}
