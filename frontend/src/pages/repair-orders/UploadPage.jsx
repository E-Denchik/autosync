import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { api } from "../../api/client.js";
import { useToast } from "../../context/ToastContext.jsx";
import { useAuth } from "../../context/AuthContext.jsx";
import { UploadIcon, FileTextIcon, AlertCircleIcon } from "../../components/icons.jsx";

const ACCEPTED = [".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".docx", ".pdf"];
const MAX_SIZE_BYTES = 25 * 1024 * 1024; // см. backend/app/config.py: MAX_CONTENT_LENGTH

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

function Dropzone({ id, label, file, onChange }) {
  const [dragOver, setDragOver] = useState(false);
  const toast = useToast();

  const handleFiles = (files) => {
    const f = files?.[0];
    if (!f) return;
    const ext = "." + f.name.split(".").pop().toLowerCase();
    if (!ACCEPTED.includes(ext)) {
      toast.error(`Формат ${ext} не поддерживается. Допустимые форматы: ${ACCEPTED.join(", ")}`);
      return;
    }
    if (f.size > MAX_SIZE_BYTES) {
      toast.error(`Файл слишком большой (${formatSize(f.size)}) — максимум ${formatSize(MAX_SIZE_BYTES)}`);
      return;
    }
    onChange(f);
  };

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div
        className={`dropzone ${dragOver ? "dragover" : ""} ${file ? "has-file" : ""}`}
        onClick={() => document.getElementById(id).click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          handleFiles(e.dataTransfer.files);
        }}
      >
        <FileTextIcon className="dz-icon" />
        {file ? (
          <>
            <div className="dz-file">{file.name}</div>
            <div className="dz-meta">{formatSize(file.size)}</div>
            <button
              type="button"
              className="dz-remove"
              onClick={(e) => {
                e.stopPropagation();
                onChange(null);
              }}
            >
              Убрать файл
            </button>
          </>
        ) : (
          <>
            <div className="dz-title">Перетащите файл сюда или нажмите для выбора</div>
            <div className="dz-hint">до {formatSize(MAX_SIZE_BYTES)}</div>
          </>
        )}
        <input
          id={id}
          type="file"
          accept={ACCEPTED.join(",")}
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>
    </div>
  );
}

export default function UploadPage() {
  const [contractFile, setContractFile] = useState(null);
  const [orderFile, setOrderFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [llmConfigured, setLlmConfigured] = useState(true); // оптимистично, пока не пришёл ответ
  const [contragents, setContragents] = useState([]);
  const [contragentId, setContragentId] = useState("");
  const [vehicleMake, setVehicleMake] = useState("");
  const [vehicleModel, setVehicleModel] = useState("");
  const [vehicleYear, setVehicleYear] = useState("");
  const [vehicleVin, setVehicleVin] = useState("");
  const navigate = useNavigate();
  const toast = useToast();
  const { user } = useAuth();

  useEffect(() => {
    api
      .dashboardSummary()
      .then((s) => setLlmConfigured(Boolean(s.llm_model)))
      .catch(() => {});
    api.listContragents().then(setContragents).catch(() => {});
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!contractFile || !orderFile) {
      toast.error("Нужно выбрать оба файла: договор и заказ-наряд");
      return;
    }
    setSubmitting(true);
    try {
      const { repair_order_id } = await api.uploadDocuments(contractFile, orderFile, {
        contragent_id: contragentId,
        vehicle_make: vehicleMake,
        vehicle_model: vehicleModel,
        vehicle_year: vehicleYear,
        vehicle_vin: vehicleVin,
      });
      toast.success("Файлы загружены, сопоставление запущено");
      navigate(`/repair-orders/${repair_order_id}/review`);
    } catch (e2) {
      toast.error(e2.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Загрузка договора и заказ-наряда</h2>
          <p>
            После загрузки позиции будут сопоставлены автоматически: сначала по точному артикулу,
            затем через кросс-номера поставщика, и только в крайнем случае — LLM по названию.
          </p>
        </div>
      </div>

      {!llmConfigured && (
        <div className="hint-banner hint-warning">
          <AlertCircleIcon />
          <span>
            LLM-модель не выбрана — шаг сопоставления по названию будет недоступен, такие позиции
            уйдут на ручную проверку.
            {user?.role === "admin" && <> <Link to="/admin/llm">Выбрать модель →</Link></>}
          </span>
        </div>
      )}

      <div className="two-col-grid">
        <form className="panel" onSubmit={handleSubmit}>
          <div className="dropzone-row">
            <Dropzone id="contract" label="Договор" file={contractFile} onChange={setContractFile} />
            <Dropzone id="repair_order" label="Заказ-наряд" file={orderFile} onChange={setOrderFile} />
          </div>

          <div className="format-chip-list" style={{ marginBottom: 18 }}>
            {ACCEPTED.map((ext) => (
              <span className="format-chip" key={ext}>
                {ext}
              </span>
            ))}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 18 }}>
            <div className="field">
              <label htmlFor="contragent">Контрагент</label>
              <select id="contragent" value={contragentId} onChange={(e) => setContragentId(e.target.value)}>
                <option value="">— не выбран —</option>
                {contragents.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.hourly_rate} ₽/ч)
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="vehicle_vin">VIN</label>
              <input id="vehicle_vin" value={vehicleVin} onChange={(e) => setVehicleVin(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="vehicle_make">Марка автомобиля</label>
              <input
                id="vehicle_make"
                value={vehicleMake}
                onChange={(e) => setVehicleMake(e.target.value)}
                placeholder="например, ВАЗ"
              />
            </div>
            <div className="field">
              <label htmlFor="vehicle_model">Модель</label>
              <input
                id="vehicle_model"
                value={vehicleModel}
                onChange={(e) => setVehicleModel(e.target.value)}
                placeholder="например, Granta"
              />
            </div>
            <div className="field">
              <label htmlFor="vehicle_year">Год выпуска</label>
              <input
                id="vehicle_year"
                type="number"
                value={vehicleYear}
                onChange={(e) => setVehicleYear(e.target.value)}
              />
            </div>
          </div>
          <p className="text-muted" style={{ fontSize: 12.5, marginTop: -8, marginBottom: 18 }}>
            Марка/модель нужны, чтобы автоматически подтянуть нормо-часы для работ из заказ-наряда;
            контрагент — чтобы посчитать их стоимость по его ставке.
          </p>

          <button
            className="btn btn-primary"
            style={{ width: "100%", justifyContent: "center" }}
            disabled={submitting || !contractFile || !orderFile}
            type="submit"
          >
            <UploadIcon /> {submitting ? "Загрузка…" : "Загрузить и сопоставить"}
          </button>
        </form>

        <div className="panel">
          <div className="panel-header">
            <h3>Как проходит сопоставление</h3>
          </div>
          <div className="stepper" style={{ flexDirection: "column", alignItems: "stretch", gap: 14 }}>
            <div className="step">
              <span className="step-dot">1</span>
              <div>
                <div style={{ color: "var(--text)", fontWeight: 600 }}>Точный артикул</div>
                <div className="text-muted" style={{ fontWeight: 400 }}>
                  Позиция договора совпадает с позицией наряда по артикулу — самый надёжный вариант.
                </div>
              </div>
            </div>
            <div className="step">
              <span className="step-dot">2</span>
              <div>
                <div style={{ color: "var(--text)", fontWeight: 600 }}>Кросс-номера поставщика</div>
                <div className="text-muted" style={{ fontWeight: 400 }}>
                  Если артикулы не совпали напрямую — проверяем аналоги через API поставщика запчастей.
                </div>
              </div>
            </div>
            <div className="step">
              <span className="step-dot">3</span>
              <div>
                <div style={{ color: "var(--text)", fontWeight: 600 }}>LLM по названию</div>
                <div className="text-muted" style={{ fontWeight: 400 }}>
                  Последний вариант — сопоставление по смыслу названия. Всегда помечается как
                  требующее проверки человеком.
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
