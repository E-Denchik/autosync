import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client.js";
import ConfidenceBadge from "../../components/ConfidenceBadge.jsx";
import StatusStepper from "../../components/StatusStepper.jsx";
import Spinner from "../../components/Spinner.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { CheckCircleIcon } from "../../components/icons.jsx";

const PROCESSING_STATUSES = new Set(["uploaded", "parsing", "matching"]);

export default function ReviewMatches() {
  const { repairOrderId } = useParams();
  const [status, setStatus] = useState(null);
  const [matches, setMatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);
  const [generating, setGenerating] = useState(false);
  const toast = useToast();
  const pollRef = useRef(null);

  const loadMatches = () => {
    api
      .listMatches(repairOrderId)
      .then(setMatches)
      .catch((e) => toast.error(e.message));
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
  const isProcessing = PROCESSING_STATUSES.has(status);

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Проверка сопоставлений</h2>
          <p>
            Позиции с меткой «догадка LLM» — это предположение модели по названию, а не подтверждённое
            совпадение. Их обязательно нужно проверить вручную перед генерацией документа.
          </p>
        </div>
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
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
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
                      {m.contract_article || "—"} / {m.contract_name}
                    </td>
                    <td>{m.matched_name || "не найдено"}</td>
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
                      {m.review_status === "pending" && (
                        <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
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
                        </div>
                      )}
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
    </div>
  );
}
