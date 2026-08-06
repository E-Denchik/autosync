import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api/client.js";
import { useToast } from "../../context/ToastContext.jsx";
import { UploadIcon, FileTextIcon } from "../../components/icons.jsx";

const ACCEPTED = [".xlsx", ".xls", ".pdf"];

function isAccepted(file) {
  return ACCEPTED.some((ext) => file.name.toLowerCase().endsWith(ext));
}

function Dropzone({ id, label, file, onChange }) {
  const [dragOver, setDragOver] = useState(false);

  const handleFiles = (files) => {
    const f = files?.[0];
    if (!f) return;
    if (!isAccepted(f)) return;
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
          <div className="dz-file">{file.name}</div>
        ) : (
          <>
            <div className="dz-title">Перетащите файл сюда или нажмите для выбора</div>
            <div className="dz-hint">.xlsx, .xls, .pdf</div>
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
  const navigate = useNavigate();
  const toast = useToast();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!contractFile || !orderFile) {
      toast.error("Нужно выбрать оба файла: договор и заказ-наряд");
      return;
    }
    setSubmitting(true);
    try {
      const { repair_order_id } = await api.uploadDocuments(contractFile, orderFile);
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

      <form className="panel" style={{ maxWidth: 480 }} onSubmit={handleSubmit}>
        <Dropzone id="contract" label="Договор" file={contractFile} onChange={setContractFile} />
        <Dropzone id="repair_order" label="Заказ-наряд" file={orderFile} onChange={setOrderFile} />

        <button
          className="btn btn-primary"
          style={{ marginTop: 8, width: "100%", justifyContent: "center" }}
          disabled={submitting}
          type="submit"
        >
          <UploadIcon /> {submitting ? "Загрузка…" : "Загрузить и сопоставить"}
        </button>
      </form>
    </div>
  );
}
