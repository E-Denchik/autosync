import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import Spinner from "./Spinner.jsx";
import { AlertCircleIcon, DownloadIcon, InfoIcon } from "./icons.jsx";

const TABLE_EXTENSIONS = [".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".docx", ".pdf"];
const IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png"];
const NUMERIC_CELL = /^-?[\d\s]+([.,]\d+)?%?$/;

function extOf(name) {
  const i = (name || "").lastIndexOf(".");
  return i === -1 ? "" : name.slice(i).toLowerCase();
}

function columnLetter(index) {
  let n = index + 1;
  let letters = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    letters = String.fromCharCode(65 + rem) + letters;
    n = Math.floor((n - 1) / 26);
  }
  return letters;
}

function isNumericCell(value) {
  const trimmed = (value || "").trim();
  return trimmed !== "" && NUMERIC_CELL.test(trimmed);
}

export default function FilePreviewModal({ blob, fileName, onClose, loader, subtitle, onDownload }) {
  const [rows, setRows] = useState(null);
  const [truncated, setTruncated] = useState(false);
  const [unresolvedTokens, setUnresolvedTokens] = useState([]);
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
    setUnresolvedTokens([]);
    setObjectUrl(null);

    if (loader) {
      loader()
        .then((res) => {
          if (cancelled) return;
          setRows(res.rows);
          setTruncated(res.truncated);
          setUnresolvedTokens(res.unresolved_tokens || []);
        })
        .catch((e) => !cancelled && setError(e.message))
        .finally(() => !cancelled && setLoading(false));
      return () => {
        cancelled = true;
      };
    }

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
  }, [blob, fileName, ext, showAsImage, showAsPdf, loader]);

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
        style={{
          width: rows ? "min(1200px, 100%)" : "min(960px, 100%)",
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 650, fontSize: 14.5, wordBreak: "break-all" }}>{fileName}</div>
            {subtitle && (
              <div className="text-muted" style={{ fontSize: 12.5, marginTop: 2 }}>
                {subtitle}
              </div>
            )}
            {onDownload && (
              <div className="text-muted" style={{ fontSize: 12.5, marginTop: 2 }}>
                Если хотите сохранить ещё одну копию (например, под другим именем или в другую папку),
                нажмите «Скачать» — откроется системное окно выбора места сохранения.
              </div>
            )}
          </div>
          <div style={{ display: "flex", gap: 8, flexShrink: 0, marginLeft: 12 }}>
            {onDownload && (
              <button className="btn btn-secondary btn-sm" onClick={onDownload}>
                <DownloadIcon /> Скачать
              </button>
            )}
            <button className="btn btn-secondary btn-sm" onClick={onClose}>
              Закрыть
            </button>
          </div>
        </div>

        <div style={{ overflow: "auto", flex: 1, minHeight: 0 }}>
          {loading && (
            <Spinner
              label={
                blob && blob.size > 3 * 1024 * 1024
                  ? "Загрузка предпросмотра… файл большой, это может занять несколько секунд"
                  : "Загрузка предпросмотра…"
              }
            />
          )}
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
            <>
              {unresolvedTokens.length > 0 && (
                <div className="hint-banner hint-warning" style={{ marginBottom: 12 }}>
                  <AlertCircleIcon />
                  <span>
                    Эти плейсхолдеры не распознаны и остались как есть: {unresolvedTokens.join(", ")}. Проверьте
                    написание — допустимы только латинские буквы, цифры, {"_"} и {"."}, без пробелов и дефисов.
                  </span>
                </div>
              )}
              <div className="preview-table-wrap">
                <table className="preview-table">
                  <thead>
                    <tr>
                      <th className="preview-row-gutter" />
                      {rows[0].map((_, i) => (
                        <th key={i} className="preview-col-letter">
                          {columnLetter(i)}
                        </th>
                      ))}
                    </tr>
                    <tr>
                      <th className="preview-row-gutter">1</th>
                      {rows[0].map((cell, i) => (
                        <th key={i}>{cell || `Кол. ${i + 1}`}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.slice(1).map((row, i) => (
                      <tr key={i}>
                        <td className="preview-row-gutter">{i + 2}</td>
                        {row.map((cell, j) => (
                          <td key={j} className={isNumericCell(cell) ? "preview-cell-numeric" : undefined}>
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {truncated && (
                <div className="hint-banner" style={{ marginTop: 12 }}>
                  <InfoIcon />
                  <span>Показаны первые {rows.length - 1} строк — в файле их больше.</span>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
