import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { api } from "../../api/client.js";
import { useToast } from "../../context/ToastContext.jsx";
import FilePreviewModal from "../../components/FilePreviewModal.jsx";
import HowToUse from "../../components/HowToUse.jsx";
import { UploadIcon, FileTextIcon, AlertCircleIcon, EyeIcon, CloseIcon, InfoIcon, PlusIcon } from "../../components/icons.jsx";

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
  const [contractMode, setContractMode] = useState("new");
  const [contractFiles, setContractFiles] = useState([]);
  const [existingContractId, setExistingContractId] = useState("");
  const [contracts, setContracts] = useState([]);
  const [orderFiles, setOrderFiles] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [llmConfigured, setLlmConfigured] = useState(true); // оптимистично, пока не пришёл ответ
  const [suppliersConfigured, setSuppliersConfigured] = useState(true); // оптимистично, пока не пришёл ответ
  const [contragents, setContragents] = useState([]);
  const [contragentId, setContragentId] = useState("");
  const [showNewContragentForm, setShowNewContragentForm] = useState(false);
  const [newContragentName, setNewContragentName] = useState("");
  const [newContragentRate, setNewContragentRate] = useState("");
  const [creatingContragent, setCreatingContragent] = useState(false);
  const [vehicleMake, setVehicleMake] = useState("");
  const [vehicleModel, setVehicleModel] = useState("");
  const [vehicleYear, setVehicleYear] = useState("");
  const [vehicleVin, setVehicleVin] = useState("");
  const [showMatchingInfo, setShowMatchingInfo] = useState(true);
  const navigate = useNavigate();
  const toast = useToast();

  useEffect(() => {
    api
      .dashboardSummary()
      .then((s) => setLlmConfigured(Boolean(s.llm_model)))
      .catch(() => {});
    api.listContragents().then(setContragents).catch(() => {});
    api.listContracts().then(setContracts).catch(() => {});
    api
      .listIntegrations()
      .then((list) => {
        const supplierIds = new Set(["rossco", "autoeuro", "moskvorechye"]);
        setSuppliersConfigured(list.some((it) => supplierIds.has(it.id) && it.configured));
      })
      .catch(() => {});
  }, []);

  const parsedContracts = contracts.filter((c) => c.status === "parsed" && c.active);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (orderFiles.length === 0) {
      toast.error("Нужно выбрать файл заказ-наряда");
      return;
    }
    if (contractMode === "new" && contractFiles.length === 0) {
      toast.error("Нужно выбрать файл договора (или переключиться на существующий контракт)");
      return;
    }
    if (contractMode === "existing" && !existingContractId) {
      toast.error("Нужно выбрать контракт из списка");
      return;
    }
    setSubmitting(true);
    try {
      const { repair_order_id, reused_existing_contract, reused_contract_name } = await api.uploadDocuments(
        contractMode === "new" ? contractFiles : [],
        orderFiles,
        {
          contract_id: contractMode === "existing" ? existingContractId : undefined,
          contragent_id: contragentId,
          vehicle_make: vehicleMake,
          vehicle_model: vehicleModel,
          vehicle_year: vehicleYear,
          vehicle_vin: vehicleVin,
        }
      );
      toast.success(
        reused_existing_contract
          ? `Файлы загружены — такой договор уже был, переиспользован «${reused_contract_name}»`
          : "Файлы загружены, сопоставление запущено"
      );
      navigate(`/repair-orders/${repair_order_id}/review`);
    } catch (e2) {
      toast.error(e2.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleCreateContragent = async (e) => {
    e.preventDefault();
    if (!newContragentName.trim() || newContragentRate === "") {
      toast.error("Укажите название и ставку за нормо-час");
      return;
    }
    setCreatingContragent(true);
    try {
      const created = await api.createContragent({
        name: newContragentName.trim(),
        hourly_rate: Number(newContragentRate),
      });
      setContragents((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)));
      setContragentId(String(created.id));
      setShowNewContragentForm(false);
      setNewContragentName("");
      setNewContragentRate("");
      toast.success(`Контрагент «${created.name}» добавлен и выбран`);
    } catch (e2) {
      toast.error(e2.message);
    } finally {
      setCreatingContragent(false);
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
        {!showMatchingInfo && (
          <button className="btn btn-secondary btn-sm" onClick={() => setShowMatchingInfo(true)}>
            <InfoIcon style={{ width: 13, height: 13 }} /> Как проходит сопоставление
          </button>
        )}
      </div>

      <HowToUse
        steps={[
          "Загрузите файл договора/прайса (или выберите уже загруженный контракт) и файл заказ-наряда — можно перетащить, добавить сразу несколько файлов или загрузить фото/сканы страниц вместо таблицы.",
          "Марка, модель и VIN нужны, чтобы автоматически подтянуть нормо-часы; контрагент — чтобы посчитать стоимость работ по его ставке. Все поля можно оставить пустыми и заполнить позже.",
          "После нажатия «Загрузить и сопоставить» вы попадёте на страницу проверки — там нужно будет подтвердить или поправить каждую найденную позицию.",
        ]}
      />

      {!llmConfigured && (
        <div className="hint-banner hint-warning">
          <AlertCircleIcon />
          <span>
            LLM-модель не выбрана — шаг сопоставления по названию будет недоступен, такие позиции
            уйдут на ручную проверку. <Link to="/admin/llm">Выбрать модель →</Link>
          </span>
        </div>
      )}

      {!suppliersConfigured && (
        <div className="hint-banner hint-warning">
          <AlertCircleIcon />
          <span>
            Ни один поставщик кросс-номеров (Rossco, АвтоЕвро, Москворечье) не настроен — шаг 2
            (поиск аналогов по артикулу) будет пропущен, сопоставление пойдёт сразу к LLM-догадке по
            названию, и найдётся заметно меньше позиций.{" "}
            <Link to="/admin/integrations">Настроить ключи →</Link>
          </span>
        </div>
      )}

      <div className={showMatchingInfo ? "two-col-grid" : ""}>
        <form className="panel" onSubmit={handleSubmit}>
          <div className="dropzone-row">
            <div className="field">
              <label>Договор</label>
              <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
                <button
                  type="button"
                  className={contractMode === "new" ? "btn btn-primary btn-sm" : "btn btn-secondary btn-sm"}
                  onClick={() => setContractMode("new")}
                >
                  Новый файл
                </button>
                <button
                  type="button"
                  className={contractMode === "existing" ? "btn btn-primary btn-sm" : "btn btn-secondary btn-sm"}
                  onClick={() => setContractMode("existing")}
                >
                  Уже загруженный контракт
                </button>
              </div>
              {contractMode === "existing" ? (
                <>
                  <select value={existingContractId} onChange={(e) => setExistingContractId(e.target.value)}>
                    <option value="">— выберите контракт —</option>
                    {parsedContracts.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name || c.original_filename} ({c.parts_count} запчастей, {c.labor_norms_count} нормо-часов)
                      </option>
                    ))}
                  </select>
                  {contracts.length > 0 && parsedContracts.length === 0 && (
                    <p className="text-muted" style={{ fontSize: 12, marginTop: 6 }}>
                      Есть контракты, но ни один ещё не разобран — подождите или проверьте статус в{" "}
                      <Link to="/admin/contracts">Каталогах контрактов</Link>.
                    </p>
                  )}
                </>
              ) : (
                <Dropzone
                  id="contract"
                  label=""
                  hint="Прайс-лист/каталог цен поставщика — то, с чем сверяем цены и артикулы. Не заказ-наряд."
                  files={contractFiles}
                  onChange={setContractFiles}
                />
              )}
            </div>
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
              <div style={{ display: "flex", gap: 6 }}>
                <select
                  id="contragent"
                  value={contragentId}
                  onChange={(e) => setContragentId(e.target.value)}
                  style={{ flex: 1 }}
                >
                  <option value="">— не выбран —</option>
                  {contragents.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name} ({c.hourly_rate} ₽/ч)
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  title="Добавить нового контрагента"
                  onClick={() => setShowNewContragentForm((v) => !v)}
                >
                  <PlusIcon style={{ width: 13, height: 13 }} />
                </button>
              </div>
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

          {showNewContragentForm && (
            <div className="panel" style={{ marginBottom: 18, background: "var(--bg-sunken)" }}>
              <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr auto auto", gap: 8, alignItems: "end" }}>
                <div className="field" style={{ marginBottom: 0 }}>
                  <label htmlFor="new-contragent-name">Название нового контрагента</label>
                  <input
                    id="new-contragent-name"
                    autoFocus
                    value={newContragentName}
                    onChange={(e) => setNewContragentName(e.target.value)}
                    placeholder="например, ООО «Ромашка»"
                  />
                </div>
                <div className="field" style={{ marginBottom: 0 }}>
                  <label htmlFor="new-contragent-rate">Ставка, ₽/ч</label>
                  <input
                    id="new-contragent-rate"
                    type="number"
                    min="0"
                    step="0.01"
                    value={newContragentRate}
                    onChange={(e) => setNewContragentRate(e.target.value)}
                  />
                </div>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={creatingContragent}
                  onClick={handleCreateContragent}
                >
                  {creatingContragent ? "Сохранение…" : "Добавить"}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => setShowNewContragentForm(false)}
                >
                  Отмена
                </button>
              </div>
            </div>
          )}

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

        {showMatchingInfo && (
        <div className="panel">
          <div className="panel-header">
            <h3>Как проходит сопоставление</h3>
            <button
              className="btn btn-secondary btn-sm"
              title="Скрыть"
              onClick={() => setShowMatchingInfo(false)}
            >
              <CloseIcon style={{ width: 13, height: 13 }} />
            </button>
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
        )}
      </div>
    </div>
  );
}
