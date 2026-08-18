import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import Spinner from "../../components/Spinner.jsx";
import HowToUse from "../../components/HowToUse.jsx";
import { useToast } from "../../context/ToastContext.jsx";

const EMPTY = { COMPANY_NAME: "", COMPANY_INN: "", COMPANY_ADDRESS: "", COMPANY_PHONE: "" };

export default function CompanyProfile() {
  const [form, setForm] = useState(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  useEffect(() => {
    api
      .getCompanyProfile()
      .then(setForm)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const updated = await api.updateCompanyProfile(form);
      setForm(updated);
      toast.success("Реквизиты сохранены");
    } catch (e2) {
      toast.error(e2.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Spinner label="Загрузка…" />;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Реквизиты компании</h2>
          <p>Попадают в шапку сформированных документов (заказ-наряд/акт) — как встроенного формата, так и загруженных шаблонов (токены {"{{company_name}}"}, {"{{company_inn}}"}, {"{{company_address}}"}, {"{{company_phone}}"}).</p>
        </div>
      </div>

      <HowToUse
        steps={[
          "Заполните данные один раз — они автоматически подставляются в шапку каждого сформированного документа (заказ-наряда/акта).",
          "Если используете свой шаблон (Администрирование → Шаблоны документов), добавьте в него плейсхолдеры {{company_name}}, {{company_inn}} и т.д. — значения возьмутся отсюда.",
        ]}
      />

      <form className="panel" style={{ maxWidth: 520 }} onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="COMPANY_NAME">Название организации</label>
          <input
            id="COMPANY_NAME"
            value={form.COMPANY_NAME}
            onChange={(e) => setForm((f) => ({ ...f, COMPANY_NAME: e.target.value }))}
            placeholder="ИП Иванов Иван Иванович"
          />
        </div>
        <div className="field">
          <label htmlFor="COMPANY_INN">ИНН</label>
          <input
            id="COMPANY_INN"
            value={form.COMPANY_INN}
            onChange={(e) => setForm((f) => ({ ...f, COMPANY_INN: e.target.value }))}
          />
        </div>
        <div className="field">
          <label htmlFor="COMPANY_ADDRESS">Адрес</label>
          <input
            id="COMPANY_ADDRESS"
            value={form.COMPANY_ADDRESS}
            onChange={(e) => setForm((f) => ({ ...f, COMPANY_ADDRESS: e.target.value }))}
          />
        </div>
        <div className="field">
          <label htmlFor="COMPANY_PHONE">Телефон</label>
          <input
            id="COMPANY_PHONE"
            value={form.COMPANY_PHONE}
            onChange={(e) => setForm((f) => ({ ...f, COMPANY_PHONE: e.target.value }))}
          />
        </div>
        <button className="btn btn-primary" disabled={saving} type="submit">
          {saving ? "Сохранение…" : "Сохранить"}
        </button>
      </form>
    </div>
  );
}
