import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import Spinner from "./Spinner.jsx";

const TABLE_EXTENSIONS = [".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".docx", ".pdf"];
const IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png"];

function extOf(name) {
  const i = (name || "").lastIndexOf(".");
  return i === -1 ? "" : name.slice(i).toLowerCase();
}

export default function FilePreviewModal({ blob, fileName, onClose }) {
  const [rows, setRows] = useState(null);
  const [truncated, setTruncated] = useState(false);
  const [objectUrl, setObjectUrl] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const ext = extOf(fileName);
  const showAsImage = IMAGE_EXTENSIONS.includes(ext);
  const showAsPdf = ext === ".pdf";

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setRows(null);
    setObjectUrl(null);

    if (!blob) return undefined;

    if (showAsImage) {
      const url = URL.createObjectURL(blob);
      setObjectUrl(url);
      setLoading(false);
      return () => URL.revokeObjectURL(url);
    }

    if (showAsPdf) {
      const url = URL.createObjectURL(blob);
      setObjectUrl(url);
      setLoading(false);
      return () => URL.revokeObjectURL(url);
    }

    if (TABLE_EXTENSIONS.includes(ext)) {
      const file = blob instanceof File ? blob : new File([blob], fileName || "file");
      api
        .previewFile(file)
        .then((res) => {
          if (cancelled) return;
          setRows(res.rows);
          setTruncated(res.truncated);
        })
        .catch((e) => !cancelled && setError(e.message))
        .finally(() => !cancelled && setLoading(false));
      return () => {
        cancelled = true;
      };
    }

    setError("Предпросмотр не поддерживается для этого формата файла — скачайте и откройте локально.");
    setLoading(false);
    return undefined;
  }, [blob, fileName, ext, showAsImage, showAsPdf]);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(10, 11, 16, 0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 150,
        padding: 24,
      }}
      onClick={onClose}
    >
      <div
        className="panel"
        style={{ width: "min(960px, 100%)", maxHeight: "85vh", display: "flex", flexDirection: "column" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <div style={{ fontWeight: 650, fontSize: 14.5, wordBreak: "break-all" }}>{fileName}</div>
          <button className="btn btn-secondary btn-sm" onClick={onClose} style={{ flexShrink: 0, marginLeft: 12 }}>
            Закрыть
          </button>
        </div>

        <div style={{ overflow: "auto", flex: 1, minHeight: 0 }}>
          {loading && <Spinner label="Загрузка предпросмотра…" />}
          {!loading && error && (
            <div className="text-muted" style={{ padding: "8px 0" }}>
              {error}
            </div>
          )}
          {!loading && !error && showAsPdf && objectUrl && (
            <iframe src={objectUrl} title={fileName} style={{ width: "100%", height: "70vh", border: "none" }} />
          )}
          {!loading && !error && showAsImage && objectUrl && (
            <img src={objectUrl} alt={fileName} style={{ maxWidth: "100%", display: "block" }} />
          )}
          {!loading && !error && rows && (
            <div style={{ overflow: "auto", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
              <table>
                <thead>
                  <tr>
                    {rows[0].map((cell, i) => (
                      <th key={i} style={{ whiteSpace: "nowrap" }}>
                        {cell || `Кол. ${i + 1}`}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(1).map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => (
                        <td key={j} style={{ whiteSpace: "nowrap" }}>
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {truncated && (
                <div className="text-muted" style={{ padding: 12, fontSize: 12.5 }}>
                  Показаны первые {rows.length - 1} строк — в файле их больше.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
