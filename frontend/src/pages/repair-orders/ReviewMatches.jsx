import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client.js";
import ConfidenceBadge from "../../components/ConfidenceBadge.jsx";
import StatusStepper from "../../components/StatusStepper.jsx";
import Spinner from "../../components/Spinner.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import MatchEditModal from "../../components/MatchEditModal.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { CheckCircleIcon, DownloadIcon, EditIcon } from "../../components/icons.jsx";

const PROCESSING_STATUSES = new Set(["uploaded", "parsing", "matching"]);

export default function ReviewMatches() {
  const { repairOrderId } = useParams();
  const [status, setStatus] = useState(null);
  const [matches, setMatches] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const [editingMatch, setEditingMatch] = useState(null);
  const toast = useToast();
  const pollRef = useRef(null);

  const loadMatches = () => {
    api
      .listMatches(repairOrderId)
      .then(setMatches)
      .catch((e) => toast.error(e.message));
    api
      .listCandidates(repairOrderId)
      .then(setCandidates)
      .catch(() => {});
  };

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const s = await api.getUploadStatus(repairOrderId);
        if (cancelled) return;
        setStatus(s.status);
        setLoading(false);

        if (s.status === "failed") {
          toast.error(s.error_message || "Обработка завершилась ошибкой");
          clearInterval(pollRef.current);
          return;
        }

        if (!PROCESSING_STATUSES.has(s.status)) {
          loadMatches();
          clearInterval(pollRef.current);
        }
      } catch (e) {
        if (!cancelled) toast.error(e.message);
      }
    };

    poll();
    pollRef.current = setInterval(poll, 2000);
    return () => {
      cancelled = true;
      clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repairOrderId]);

  const toggleSelected = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleSelectAllPending = () => {
    const pendingIds = matches.filter((m) => m.review_status === "pending").map((m) => m.id);
    setSelected((prev) => (prev.size === pendingIds.length ? new Set() : new Set(pendingIds)));
  };

  const handleDecision = async (id, decision) => {
    setBusyId(id);
    try {
      const updated = decision === "approve" ? await api.approveMatch(id) : await api.rejectMatch(id);
      setMatches((prev) => prev.map((m) => (m.id === id ? updated : m)));
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusyId(null);
    }
  };

  const handleBulk = async (action) => {
    if (selected.size === 0) return;
    setBulkBusy(true);
    try {
      const updated = await api.bulkReview(Array.from(selected), action);
      const updatedById = new Map(updated.map((m) => [m.id, m]));
      setMatches((prev) => prev.map((m) => updatedById.get(m.id) || m));
      setSelected(new Set());
      toast.success(action === "approve" ? "Позиции приняты" : "Позиции отклонены");
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBulkBusy(false);
    }
  };

  const handleSaveEdit = async (patch) => {
    setBusyId(editingMatch.id);
    try {
      const updated = await api.editMatch(editingMatch.id, patch);
      setMatches((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
      toast.success("Сопоставление обновлено вручную");
      setEditingMatch(null);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusyId(null);
    }
  };

  const handleExportCsv = async () => {
    setExporting(true);
    try {
      const blob = await api.exportMatchesCsv(repairOrderId);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `repair_order_${repairOrderId}_matches.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setExporting(false);
    }
  };

  const handleGenerateDocument = async () => {
    setGenerating(true);
    try {
      const blob = await api.generateDocument(repairOrderId);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `repair_order_${repairOrderId}_final.xlsx`;
      a.click();
      window.URL.revokeObjectURL(url);
      toast.success("Итоговый документ сформирован");
    } catch (e) {
      toast.error(e.message);
    } finally {
      setGenerating(false);
    }
  };

  if (loading) return <Spinner label="Проверяем статус обработки…" />;

  const pendingCount = matches.filter((m) => m.review_status === "pending").length;
  const pendingIds = matches.filter((m) => m.review_status === "pending").map((m) => m.id);
  const isProcessing = PROCESSING_STATUSES.has(status);

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Проверка сопоставлений</h2>
          <p>
            Позиции с меткой «догадка LLM» — это предположение модели по названию, а не подтверждённое
            совпадение. Проверьте их вручную: примите, отклоните или подберите правильную позицию через
            поиск.
          </p>
        </div>
        {!isProcessing && matches.length > 0 && (
          <button className="btn btn-secondary" disabled={exporting} onClick={handleExportCsv}>
            <DownloadIcon /> {exporting ? "Экспорт…" : "Экспорт CSV"}
          </button>
        )}
      </div>

      <StatusStepper status={status} />

      {isProcessing ? (
        <div className="table-wrap">
          <Spinner label="Парсим документы и сопоставляем позиции — обычно это занимает несколько секунд…" />
        </div>
      ) : matches.length === 0 ? (
        <div className="table-wrap">
          <EmptyState title="Не удалось найти позиции" hint="Проверьте формат загруженных файлов." />
        </div>
      ) : (
        <>
          {selected.size > 0 && (
            <div
              className="panel"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                marginBottom: 12,
                padding: "10px 16px",
              }}
            >
              <span style={{ fontSize: 13, fontWeight: 600 }}>Выбрано: {selected.size}</span>
              <button className="btn btn-approve btn-sm" disabled={bulkBusy} onClick={() => handleBulk("approve")}>
                Принять выбранные
              </button>
              <button className="btn btn-reject btn-sm" disabled={bulkBusy} onClick={() => handleBulk("reject")}>
                Отклонить выбранные
              </button>
              <button
                className="btn btn-secondary btn-sm"
                style={{ marginLeft: "auto" }}
                onClick={() => setSelected(new Set())}
              >
                Снять выделение
              </button>
            </div>
          )}

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 28 }}>
                    <input
                      type="checkbox"
                      checked={pendingIds.length > 0 && selected.size === pendingIds.length}
                      onChange={toggleSelectAllPending}
                      disabled={pendingIds.length === 0}
                    />
                  </th>
                  <th>Договор: артикул / название</th>
                  <th>Сопоставлено с</th>
                  <th>Цена</th>
                  <th>Уверенность</th>
                  <th>Статус</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {matches.map((m) => (
                  <tr key={m.id}>
                    <td>
                      {m.review_status === "pending" && (
                        <input
                          type="checkbox"
                          checked={selected.has(m.id)}
                          onChange={() => toggleSelected(m.id)}
                        />
                      )}
                    </td>
                    <td>
                      {m.contract_article || "—"} / {m.contract_name}
                    </td>
                    <td>
                      {m.matched_name || "не найдено"}
                      {m.manually_edited && (
                        <span className="text-muted" style={{ fontSize: 11.5, marginLeft: 6 }}>
                          (ручная правка)
                        </span>
                      )}
                    </td>
                    <td>{m.matched_price ?? "—"}</td>
                    <td>
                      <ConfidenceBadge level={m.confidence_level} score={m.confidence_score} />
                    </td>
                    <td>
                      <span className={`status-pill status-${m.review_status}`}>
                        {m.review_status === "pending"
                          ? "ожидает"
                          : m.review_status === "approved"
                          ? "принято"
                          : "отклонено"}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                        <button
                          className="btn btn-secondary btn-sm"
                          disabled={busyId === m.id}
                          onClick={() => setEditingMatch(m)}
                          title="Подобрать другую позицию вручную"
                        >
                          <EditIcon /> Изменить
                        </button>
                        {m.review_status === "pending" && (
                          <>
                            <button
                              className="btn btn-approve btn-sm"
                              disabled={busyId === m.id}
                              onClick={() => handleDecision(m.id, "approve")}
                            >
                              Принять
                            </button>
                            <button
                              className="btn btn-reject btn-sm"
                              disabled={busyId === m.id}
                              onClick={() => handleDecision(m.id, "reject")}
                            >
                              Отклонить
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ marginTop: 18 }}>
            <button
              className="btn btn-primary"
              disabled={pendingCount > 0 || generating}
              onClick={handleGenerateDocument}
              title={pendingCount > 0 ? `Осталось непроверенных позиций: ${pendingCount}` : ""}
            >
              <CheckCircleIcon /> {generating ? "Генерация…" : "Сгенерировать итоговый документ"}
            </button>
            {pendingCount > 0 && (
              <span className="text-muted" style={{ marginLeft: 12, fontSize: 12.5 }}>
                Осталось проверить: {pendingCount}
              </span>
            )}
          </div>
        </>
      )}

      {editingMatch && (
        <MatchEditModal
          match={editingMatch}
          candidates={candidates}
          saving={busyId === editingMatch.id}
          onClose={() => setEditingMatch(null)}
          onSave={handleSaveEdit}
        />
      )}
    </div>
  );
}
