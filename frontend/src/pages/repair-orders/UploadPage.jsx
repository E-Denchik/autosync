import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { api } from "../../api/client.js";
import { useToast } from "../../context/ToastContext.jsx";
import { useAuth } from "../../context/AuthContext.jsx";
import FilePreviewModal from "../../components/FilePreviewModal.jsx";
import { UploadIcon, FileTextIcon, AlertCircleIcon, EyeIcon } from "../../components/icons.jsx";

const ACCEPTED = [".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".docx", ".pdf", ".jpg", ".jpeg", ".png"];
const MAX_SIZE_BYTES = 25 * 1024 * 1024; // см. backend/app/config.py: MAX_CONTENT_LENGTH

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

function Dropzone({ id, label, hint, files, onChange }) {
  const [dragOver, setDragOver] = useState(false);
  const [previewFile, setPreviewFile] = useState(null);
  const toast = useToast();

  const addFiles = (fileList) => {
    const incoming = Array.from(fileList || []);
    if (incoming.length === 0) return;
    const accepted = [];
    for (const f of incoming) {
      const ext = "." + f.name.split(".").pop().toLowerCase();
      if (!ACCEPTED.includes(ext)) {
        toast.error(`Формат ${ext} не поддерживается. Допустимые форматы: ${ACCEPTED.join(", ")}`);
        continue;
      }
      if (f.size > MAX_SIZE_BYTES) {
        toast.error(`Файл слишком большой (${formatSize(f.size)}) — максимум ${formatSize(MAX_SIZE_BYTES)}`);
        continue;
      }
      accepted.push(f);
    }
    if (accepted.length > 0) onChange([...files, ...accepted]);
  };

  const removeAt = (index) => {
    onChange(files.filter((_, i) => i !== index));
  };

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {hint && (
        <p className="text-muted" style={{ fontSize: 12, marginTop: -2, marginBottom: 8 }}>
          {hint}
        </p>
      )}
      <div
        className={`dropzone ${dragOver ? "dragover" : ""} ${files.length > 0 ? "has-file" : ""}`}
        onClick={() => document.getElementById(id).click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          addFiles(e.dataTransfer.files);
        }}
      >
        <FileTextIcon className="dz-icon" />
        {files.length > 0 ? (
          <div style={{ width: "100%" }}>
            {files.map((f, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <div>
                  <div className="dz-file">{f.name}</div>
                  <div className="dz-meta">{formatSize(f.size)}</div>
                </div>
                <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                  <button
                    type="button"
                    className="dz-remove"
                    style={{ display: "inline-flex", alignItems: "center", gap: 3 }}
                    onClick={(e) => {
                      e.stopPropagation();
                      setPreviewFile(f);
                    }}
                  >
                    <EyeIcon style={{ width: 13, height: 13 }} /> Просмотр
                  </button>
                  <button
                    type="button"
                    className="dz-remove"
                    onClick={(e) => {
                      e.stopPropagation();
                      removeAt(i);
                    }}
                  >
                    Убрать
                  </button>
                </div>
              </div>
            ))}
            <div className="dz-hint" style={{ marginTop: 8 }}>
              Можно добавить ещё файлы (например, другие страницы) — нажмите или перетащите сюда
            </div>
          </div>
        ) : (
          <>
            <div className="dz-title">Перетащите файл(ы) сюда или нажмите для выбора</div>
            <div className="dz-hint">до {formatSize(MAX_SIZE_BYTES)} на файл, можно несколько</div>
          </>
        )}
        <input
          id={id}
          type="file"
          multiple
          accept={ACCEPTED.join(",")}
          onChange={(e) => {
            addFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      {previewFile && (
        <FilePreviewModal blob={previewFile} fileName={previewFile.name} onClose={() => setPreviewFile(null)} />
      )}
    </div>
  );
}

export default function UploadPage() {
  const [contractFiles, setContractFiles] = useState([]);
  const [orderFiles, setOrderFiles] = useState([]);
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
    if (contractFiles.length === 0 || orderFiles.length === 0) {
      toast.error("Нужно выбрать оба файла: договор и заказ-наряд");
      return;
    }
    setSubmitting(true);
    try {
      const { repair_order_id } = await api.uploadDocuments(contractFiles, orderFiles, {
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
            <Dropzone
              id="contract"
              label="Договор"
              hint="Прайс-лист/каталог цен поставщика — то, с чем сверяем цены и артикулы. Не заказ-наряд."
              files={contractFiles}
              onChange={setContractFiles}
            />
            <Dropzone
              id="repair_order"
              label="Заказ-наряд"
              hint="Черновик заказ-наряда, который нужно проверить и дозаполнить. Можно загрузить сканы/фото страниц вместо файла таблицы."
              files={orderFiles}
              onChange={setOrderFiles}
            />
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
            disabled={submitting || contractFiles.length === 0 || orderFiles.length === 0}
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
