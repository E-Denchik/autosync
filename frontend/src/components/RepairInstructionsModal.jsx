import { useState } from "react";
import { api } from "../api/client.js";
import { SparklesIcon } from "./icons.jsx";

// Точка входа А (кнопка в строке работы) приходит с уже заполненным
// initialOperationName; точка входа Б (кнопка в шапке страницы) — с пустым,
// оператор вписывает название сам. Запрос уходит только по явному клику —
// не автоматически при открытии, чтобы не тратить время/деньги на каждое
// открытие модалки.
export default function RepairInstructionsModal({ initialOperationName, vehicleMake, vehicleModel, onClose }) {
  const [operationName, setOperationName] = useState(initialOperationName || "");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const handleGenerate = async (e) => {
    e.preventDefault();
    if (!operationName.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.generateRepairInstructions({
        operation_name: operationName.trim(),
        vehicle_make: vehicleMake || undefined,
        vehicle_model: vehicleModel || undefined,
      });
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(10, 11, 16, 0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
      onClick={onClose}
    >
      <div
        className="panel"
        style={{ width: 520, maxHeight: "80vh", display: "flex", flexDirection: "column" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="section-title">Инструкция по выполнению работы</div>
        {(vehicleMake || vehicleModel) && (
          <p className="text-muted" style={{ fontSize: 12.5, marginTop: -6, marginBottom: 14 }}>
            Автомобиль: <strong>{[vehicleMake, vehicleModel].filter(Boolean).join(" ")}</strong>
          </p>
        )}

        <form onSubmit={handleGenerate} style={{ display: "flex", gap: 8, marginBottom: 14 }}>
          <input
            autoFocus
            placeholder="Название работы, например «замена колодок»"
            value={operationName}
            onChange={(e) => setOperationName(e.target.value)}
            style={{ flex: 1 }}
          />
          <button className="btn btn-primary" type="submit" disabled={!operationName.trim() || loading}>
            <SparklesIcon /> {loading ? "Генерация…" : "Получить инструкцию"}
          </button>
        </form>

        <div style={{ overflowY: "auto", flex: 1 }}>
          {error && (
            <p className="text-muted" style={{ color: "var(--danger-text)", fontSize: 13 }}>
              {error}
            </p>
          )}
          {!error && !result && !loading && (
            <p className="text-muted" style={{ fontSize: 13 }}>
              Введите название работы и нажмите «Получить инструкцию».
            </p>
          )}
          {result && (
            <>
              {result.steps.length > 0 ? (
                <ol style={{ paddingLeft: 20, margin: 0, display: "flex", flexDirection: "column", gap: 8 }}>
                  {result.steps.map((step, i) => (
                    <li key={i} style={{ fontSize: 13.5, lineHeight: 1.4 }}>
                      {step}
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-muted" style={{ fontSize: 13 }}>Инструкция не получена.</p>
              )}
              {result.note && (
                <p className="text-muted" style={{ fontSize: 12.5, marginTop: 10 }}>
                  {result.note}
                </p>
              )}
            </>
          )}
        </div>

        <div style={{ display: "flex", marginTop: 14 }}>
          <button className="btn btn-secondary" onClick={onClose} style={{ marginLeft: "auto" }}>
            Закрыть
          </button>
        </div>
      </div>
    </div>
  );
}
