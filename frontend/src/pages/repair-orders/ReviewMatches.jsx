import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client.js";
import ConfidenceBadge from "../../components/ConfidenceBadge.jsx";
import StatusStepper from "../../components/StatusStepper.jsx";
import Spinner from "../../components/Spinner.jsx";
import EmptyState from "../../components/EmptyState.jsx";
import MatchEditModal from "../../components/MatchEditModal.jsx";
import LaborEditModal from "../../components/LaborEditModal.jsx";
import InlineCorrection from "../../components/InlineCorrection.jsx";
import RepairInstructionsModal from "../../components/RepairInstructionsModal.jsx";
import FilePreviewModal from "../../components/FilePreviewModal.jsx";
import HowToUse from "../../components/HowToUse.jsx";
import SupplierSearchModal from "../../components/SupplierSearchModal.jsx";
import { useToast } from "../../context/ToastContext.jsx";
import { AlertCircleIcon, CheckCircleIcon, DownloadIcon, EditIcon, SearchIcon, SparklesIcon } from "../../components/icons.jsx";
import { saveFile, CSV_FILE_TYPES, XLSX_FILE_TYPES } from "../../utils/saveFile.js";

const PROCESSING_STATUSES = new Set(["uploaded", "parsing", "matching"]);

// Отдельный, честный текст на каждую фазу вместо одного общего "обычно
// занимает несколько секунд" — парсинг больших/сканированных файлов и
// сопоставление заказ-наряда с большим числом позиций без точных
// совпадений по артикулу реально могут занимать минуты, не секунды (см.
// llm_client.py: extract_table_from_text, matcher.py/labor_matcher.py).
const PROCESSING_MESSAGES = {
  uploaded: "Файлы приняты, обработка вот-вот начнётся…",
  parsing: "Идёт разбор файлов — распознаём таблицы и извлекаем позиции. Для больших или сканированных файлов это может занять несколько минут.",
  matching: "Идёт сопоставление позиций с каталогом контракта. Чем больше позиций и чем меньше точных совпадений по артикулу — тем дольше.",
};

function parseUtcTimestamp(iso) {
  if (!iso) return null;
  // Бэкенд отдаёт наивный UTC (datetime.utcnow().isoformat(), без суффикса
  // часового пояса) — без явного "Z" браузer разобрал бы строку как
  // локальное время, а не UTC, и прошедшее время до текущего момента
  // считалось бы со сдвигом на часовой пояс пользователя (вплоть до
  // отрицательного значения сразу после загрузки).
  return new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
}

function formatElapsed(totalSeconds) {
  if (totalSeconds < 60) return `${totalSeconds} с`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes} мин ${seconds} с`;
}

// Сколько уже сделано из скольки нужно ХОТЯ БЫ для первой, грубой оценки —
// на 1 элементе (особенно в первую секунду фазы, когда несколько потоков
// парсинга/сопоставления финишируют почти одновременно) оценка скорости
// слишком шумная и может показать что-то нелепое вроде "осталось 40 минут"
// сразу после старта, хотя на деле всё идёт быстро.
const MIN_COMPLETED_FOR_ESTIMATE = 2;

function estimateRemainingSeconds(progress, phaseElapsedSeconds) {
  if (!progress || phaseElapsedSeconds <= 0) return null;
  const { current, total } = progress;
  if (current < MIN_COMPLETED_FOR_ESTIMATE || total <= current) return null;
  const rate = current / phaseElapsedSeconds; // единиц в секунду
  return Math.max(0, Math.round((total - current) / rate));
}

const CATEGORY_LABELS = {
  exact: "точное совпадение",
  cross_ref: "кросс-номер",
  llm_guess: "догадка ИИ",
  no_match: "не найдено",
  llm_error: "ошибка ИИ",
  cross_make_estimate: "оценка ИИ, другая марка",
  suggested_addition: "предложено ИИ",
  from_repair_order: "из наряда, не из справочника",
};

// Порядок важен для чтения — от надёжного к тому, что стоит проверить в
// первую очередь, а не как попало из Object.entries.
const CATEGORY_ORDER = [
  "exact",
  "cross_ref",
  "llm_guess",
  "from_repair_order",
  "cross_make_estimate",
  "suggested_addition",
  "no_match",
  "llm_error",
];

function countByCategory(items) {
  const counts = {};
  for (const item of items) {
    if (!item.match_category) continue;
    counts[item.match_category] = (counts[item.match_category] || 0) + 1;
  }
  return counts;
}

function formatRub(value) {
  return `${Math.round(value).toLocaleString("ru-RU")} ₽`;
}

function CategoryBreakdown({ counts }) {
  const present = CATEGORY_ORDER.filter((cat) => counts[cat] > 0);
  if (present.length === 0) return null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
      {present.map((cat) => (
        <span key={cat} className={`badge badge-${cat}`}>
          {CATEGORY_LABELS[cat]}: {counts[cat]}
        </span>
      ))}
    </div>
  );
}

export default function ReviewMatches() {
  const { repairOrderId } = useParams();
  const [status, setStatus] = useState(null);
  const [orderInfo, setOrderInfo] = useState(null);
  const [matches, setMatches] = useState([]);
  const [laborLines, setLaborLines] = useState([]);
  const [laborCatalog, setLaborCatalog] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);
  const [laborBusyId, setLaborBusyId] = useState(null);
  const [editingHoursId, setEditingHoursId] = useState(null);
  const [hoursInput, setHoursInput] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [laborBulkBusy, setLaborBulkBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const [laborSelected, setLaborSelected] = useState(new Set());
  const [editingMatch, setEditingMatch] = useState(null);
  const [editingLaborLine, setEditingLaborLine] = useState(null);
  const [instructionsFor, setInstructionsFor] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [generatedPreview, setGeneratedPreview] = useState(null);
  const [showSupplierSearch, setShowSupplierSearch] = useState(false);
  const [addingLaborLine, setAddingLaborLine] = useState(false);
  const [suppliersConfigured, setSuppliersConfigured] = useState(true); // оптимистично, пока не пришёл ответ
  const [now, setNow] = useState(Date.now());
  const toast = useToast();
  const pollRef = useRef(null);

  const loadMatches = () => {
    api
      .listMatches(repairOrderId)
      .then(setMatches)
      .catch((e) => toast.error(e.message));
    api
      .listLaborLines(repairOrderId)
      .then(setLaborLines)
      .catch(() => {});
    api
      .listLaborCatalog()
      .then(setLaborCatalog)
      .catch(() => {});
  };

  useEffect(() => {
    api
      .listDocumentTemplates()
      .then(setTemplates)
      .catch(() => {});
    api
      .listIntegrations()
      .then((list) => {
        const supplierIds = new Set(["rossco", "autoeuro", "moskvorechye"]);
        setSuppliersConfigured(list.some((it) => supplierIds.has(it.id) && it.configured));
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const s = await api.getUploadStatus(repairOrderId);
        if (cancelled) return;
        setStatus(s.status);
        setOrderInfo(s);
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

  // Отдельный тикер раз в секунду только для "сколько уже идёт обработка" —
  // не завязан на опрос статуса (тот раз в 2с и может не дойти вовремя),
  // чтобы счётчик времени не дёргался, а тикал плавно, пока видно спиннер.
  useEffect(() => {
    if (!PROCESSING_STATUSES.has(status)) return;
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tick);
  }, [status]);

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

  const toggleLaborSelected = (id) => {
    setLaborSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleSelectAllPendingLabor = () => {
    const pendingIds = laborLines.filter((l) => l.review_status === "pending").map((l) => l.id);
    setLaborSelected((prev) => (prev.size === pendingIds.length ? new Set() : new Set(pendingIds)));
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

  const handleBulkLabor = async (action) => {
    if (laborSelected.size === 0) return;
    setLaborBulkBusy(true);
    try {
      const { updated, skipped } = await api.bulkReviewLabor(Array.from(laborSelected), action);
      const updatedById = new Map(updated.map((l) => [l.id, l]));
      setLaborLines((prev) => prev.map((l) => updatedById.get(l.id) || l));
      setLaborSelected(new Set());
      if (skipped && skipped.length > 0) {
        toast.error(
          `Без нормы часов, не приняты (${skipped.length}): ${skipped.map((s) => s.description).join(", ")}`
        );
      } else if (updated.length > 0) {
        toast.success(action === "approve" ? "Работы приняты" : "Работы отклонены");
      }
    } catch (e) {
      toast.error(e.message);
    } finally {
      setLaborBulkBusy(false);
    }
  };

  const handleLaborDecision = async (id, decision) => {
    setLaborBusyId(id);
    try {
      const updated =
        decision === "approve" ? await api.approveLaborLine(id) : await api.rejectLaborLine(id);
      setLaborLines((prev) => prev.map((l) => (l.id === id ? updated : l)));
    } catch (e) {
      toast.error(e.message);
    } finally {
      setLaborBusyId(null);
    }
  };

  const startEditHours = (line) => {
    setEditingHoursId(line.id);
    setHoursInput(line.norm_hours ?? "");
  };

  const saveHours = async (id) => {
    setLaborBusyId(id);
    try {
      const updated = await api.editLaborLine(id, { norm_hours: Number(hoursInput) });
      setLaborLines((prev) => prev.map((l) => (l.id === id ? updated : l)));
      setEditingHoursId(null);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setLaborBusyId(null);
    }
  };

  // Общий путь для правки одной позиции — и через модалку поиска
  // (MatchEditModal), и через InlineCorrection прямо в таблице. Возвращает
  // true/false, чтобы вызывающий код (например, модалка) знал, закрываться
  // ли ему после сохранения.
  const applyMatchEdit = async (matchId, patch, { toastMessage } = {}) => {
    setBusyId(matchId);
    try {
      const updated = await api.editMatch(matchId, patch);
      setMatches((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
      toast.success(toastMessage || "Сопоставление обновлено вручную");
      return true;
    } catch (e) {
      toast.error(e.message);
      return false;
    } finally {
      setBusyId(null);
    }
  };

  const applyLaborEdit = async (laborLineId, patch, { toastMessage } = {}) => {
    setLaborBusyId(laborLineId);
    try {
      const updated = await api.editLaborLine(laborLineId, patch);
      setLaborLines((prev) => prev.map((l) => (l.id === updated.id ? updated : l)));
      toast.success(toastMessage || "Работа обновлена вручную");
      return true;
    } catch (e) {
      toast.error(e.message);
      return false;
    } finally {
      setLaborBusyId(null);
    }
  };

  const handleSaveEdit = async (patch) => {
    if (await applyMatchEdit(editingMatch.id, patch)) setEditingMatch(null);
  };

  const handleSaveLaborEdit = async (patch) => {
    if (await applyLaborEdit(editingLaborLine.id, patch)) setEditingLaborLine(null);
  };

  const handleAddLaborLine = async (patch) => {
    setLaborBusyId("new");
    try {
      const created = await api.addLaborLine(repairOrderId, patch);
      setLaborLines((prev) => [...prev, created]);
      toast.success("Работа добавлена вручную");
      setAddingLaborLine(false);
    } catch (e) {
      toast.error(e.message);
    } finally {
      setLaborBusyId(null);
    }
  };

  const handleExportCsv = async () => {
    setExporting(true);
    try {
      const blob = await api.exportMatchesCsv(repairOrderId);
      const result = await saveFile(blob, `repair_order_${repairOrderId}_matches.csv`, CSV_FILE_TYPES);
      if (result.ok) {
        toast.success(result.native ? `CSV-файл сохранён: ${result.path}` : "CSV-файл скачан");
      } else if (!result.canceled) {
        toast.error(result.error || "Не удалось сохранить файл");
      }
    } catch (e) {
      toast.error(e.message);
    } finally {
      setExporting(false);
    }
  };

  const handleGenerateDocument = async () => {
    setGenerating(true);
    try {
      const fileName = `repair_order_${repairOrderId}_final.xlsx`;
      const blob = await api.generateDocument(repairOrderId, selectedTemplateId || undefined);
      const result = await saveFile(blob, fileName, XLSX_FILE_TYPES);
      if (result.ok) {
        toast.success(result.native ? `Итоговый документ сохранён: ${result.path}` : "Итоговый документ сформирован и скачан");
      } else if (!result.canceled) {
        toast.error(result.error || "Не удалось сохранить файл");
      }
      if (blob.unresolvedTokens?.length) {
        toast.error(
          `В документе остались нераспознанные плейсхолдеры: ${blob.unresolvedTokens.join(", ")} — проверьте шаблон.`
        );
      }
      setGeneratedPreview({ blob, fileName });
      // Бэкенд при успешной генерации всегда переводит заказ-наряд в
      // reviewed (см. api/repair_orders/matching.py: generate_document) —
      // без этого степпер наверху страницы так и показывал бы "Проверка"
      // как текущий шаг, хотя документ уже готов.
      setStatus("reviewed");
    } catch (e) {
      toast.error(e.message);
    } finally {
      setGenerating(false);
    }
  };

  if (loading) return <Spinner label="Проверяем статус обработки…" />;

  const partsPending = matches.filter((m) => m.review_status === "pending").length;
  const laborPending = laborLines.filter((l) => l.review_status === "pending").length;
  const pendingCount = partsPending + laborPending;
  const pendingIds = matches.filter((m) => m.review_status === "pending").map((m) => m.id);
  const laborPendingIds = laborLines.filter((l) => l.review_status === "pending").map((l) => l.id);
  // Отличаем "ИИ честно не нашла совпадение" от "ИИ вообще была недоступна"
  // (llm-service не запущен, модель не выбрана и т.п., см. matcher.py/
  // labor_matcher.py) — раньше для проверяющего оба случая выглядели
  // одинаково как голое "не найдено", хотя во втором случае решение —
  // не разбирать все позиции руками, а починить ИИ и загрузить заново.
  const llmErrorCount = [...matches, ...laborLines].filter((m) => m.llm_error).length;
  const isProcessing = PROCESSING_STATUSES.has(status);
  const startedAt = orderInfo?.created_at ? parseUtcTimestamp(orderInfo.created_at) : null;
  const elapsedSeconds = startedAt ? Math.max(0, Math.floor((now - startedAt) / 1000)) : null;
  const progress = orderInfo?.progress || null;
  // started_at — от сервера (см. progress_tracker.py: report()), а не от
  // момента, когда браузер открыл/перезагрузил эту страницу — иначе после
  // обновления страницы посреди долгой обработки оценка скорости считалась
  // бы по нескольким секундам, которые фронт "успел понаблюдать", а не по
  // тому, сколько эта пачка реально обрабатывается, и оставшееся время
  // выглядело бы то заниженным, то завышенным на пустом месте.
  const phaseStartedAt = progress?.started_at ? parseUtcTimestamp(progress.started_at) : null;
  const phaseElapsedSeconds = phaseStartedAt ? Math.max(0, (now - phaseStartedAt) / 1000) : 0;
  const remainingSeconds = estimateRemainingSeconds(progress, phaseElapsedSeconds);
  const processingLabel =
    (PROCESSING_MESSAGES[status] || "Обрабатываем заказ-наряд…") +
    (elapsedSeconds !== null ? ` Идёт уже ${formatElapsed(elapsedSeconds)}.` : "");
  const progressLabel = progress
    ? `Обработано ${progress.current} из ${progress.total}` +
      (remainingSeconds !== null
        ? ` · осталось примерно ${formatElapsed(remainingSeconds)}`
        : progress.current < progress.total
          ? " · оцениваем время…"
          : "")
    : null;

  // Настоящая, проверяемая статистика вместо голого текста от ИИ — каждое
  // число здесь можно свести с таблицами ниже (match_category приходит с
  // бэкенда, см. api/repair_orders/matching.py и labor.py, чтобы не
  // рассинхронизировать классификацию между фронтом и бэком).
  const partsByCategory = countByCategory(matches);
  const laborByCategory = countByCategory(laborLines);
  const partsApprovedSum = matches
    .filter((m) => m.review_status === "approved")
    .reduce((sum, m) => sum + (m.matched_price || 0) * (m.contract_qty ?? 1), 0);
  const laborApprovedSum = laborLines
    .filter((l) => l.review_status === "approved")
    .reduce((sum, l) => sum + (l.total_cost || 0), 0);
  const partsApprovedCount = matches.filter((m) => m.review_status === "approved").length;
  const laborApprovedCount = laborLines.filter((l) => l.review_status === "approved").length;
  // Позиция без цены в итоговом документе просто останется с пустой ячейкой
  // (см. document_generator.py) — не потому, что что-то потерялось в коде, а
  // потому, что у поставщика в исходном прайсе цены не было. Молча это не
  // проходит незамеченным — подсказка ДО генерации, чтобы проверить/вписать
  // цену руками, а не находить пробел уже в готовом заказ-наряде.
  const partsApprovedNoPriceCount = matches.filter(
    (m) => m.review_status === "approved" && (m.matched_price === null || m.matched_price === undefined)
  ).length;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Проверка сопоставлений</h2>
          <p>
            Позиции с меткой «догадка» — это предположение модели, а не подтверждённое совпадение.
            Проверьте их вручную: примите, отклоните, впишите вариант прямо в таблице или подберите
            правильную позицию через поиск.
          </p>
          {orderInfo && (orderInfo.order_number || orderInfo.contragent_name || orderInfo.vehicle_make) && (
            <p className="text-muted" style={{ fontSize: 12.5, marginTop: 4 }}>
              {orderInfo.order_number && (
                <>
                  Заказ-наряд: <strong>№ {orderInfo.order_number}{orderInfo.order_date && ` от ${orderInfo.order_date}`}</strong>
                </>
              )}
              {orderInfo.order_number && (orderInfo.contragent_name || orderInfo.vehicle_make) && " · "}
              {orderInfo.contragent_name && <>Контрагент: <strong>{orderInfo.contragent_name}</strong></>}
              {orderInfo.contragent_name && orderInfo.vehicle_make && " · "}
              {orderInfo.vehicle_make && (
                <>
                  Автомобиль: <strong>{orderInfo.vehicle_make} {orderInfo.vehicle_model || ""}</strong>
                </>
              )}
            </p>
          )}
        </div>
        {!isProcessing && (
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-secondary" onClick={() => setShowSupplierSearch(true)}>
              <SearchIcon /> Добавить запчасть у поставщика
            </button>
            <button className="btn btn-secondary" onClick={() => setAddingLaborLine(true)}>
              <SearchIcon /> Добавить работу вручную
            </button>
            <button
              className="btn btn-secondary"
              onClick={() =>
                setInstructionsFor({ operationName: "", vehicleMake: orderInfo?.vehicle_make, vehicleModel: orderInfo?.vehicle_model })
              }
              title="Получить пошаговую инструкцию по произвольной работе"
            >
              <SparklesIcon /> Расписать работу
            </button>
            {matches.length > 0 && (
              <button className="btn btn-secondary" disabled={exporting} onClick={handleExportCsv}>
                <DownloadIcon /> {exporting ? "Экспорт…" : "Экспорт CSV"}
              </button>
            )}
          </div>
        )}
      </div>

      <HowToUse
        steps={[
          "Каждую позицию и работу нужно принять или отклонить — по одной или выделите чекбоксами и обработайте пачкой кнопками «Принять/Отклонить выбранные».",
          "Если сопоставление неверное, нажмите «Изменить» и подберите нужную позицию или операцию вручную через поиск.",
          "Кнопка «Сгенерировать итоговый документ» станет активной, только когда не останется непроверенных позиций и работ.",
          "Перед генерацией можно выбрать свой шаблон документа (Администрирование → Шаблоны документов) вместо встроенного формата.",
          "Если нужной запчасти нет в заказ-наряде вовсе, нажмите «Добавить запчасть у поставщика» — найдёт её у Rossco/АвтоЕвро/Москворечье и добавит уже подтверждённой строкой, которая попадёт в итоговый документ.",
          "Если для работы не нашлось ни каталога, ни нормо-часов — нажмите «Добавить работу вручную» и впишите операцию и часы в свободной форме.",
        ]}
      />

      {llmErrorCount > 0 && !isProcessing && (
        <div className="hint-banner hint-warning">
          <AlertCircleIcon />
          <span>
            ИИ-сопоставление по названию было недоступно для {llmErrorCount}{" "}
            {llmErrorCount === 1 ? "позиции" : "позиций"} — llm-service не ответил (не запущен, не выбрана
            модель и т.п.), а не потому, что совпадений действительно нет. Проверьте{" "}
            <Link to="/admin/llm">настройки LLM →</Link> и, если дело было в этом, загрузите заказ-наряд заново.
          </span>
        </div>
      )}

      {!suppliersConfigured && !isProcessing && matches.length > 0 && (
        <div className="hint-banner hint-warning">
          <AlertCircleIcon />
          <span>
            Ни один поставщик кросс-номеров (Rossco, АвтоЕвро, Москворечье) не настроен — если много
            позиций ниже «не найдено» с догадкой LLM 0%, скорее всего дело в этом, а не в самих
            запчастях. <Link to="/admin/integrations">Настроить ключи →</Link>, затем загрузите
            заказ-наряд заново.
          </span>
        </div>
      )}

      {partsApprovedNoPriceCount > 0 && !isProcessing && (
        <div className="hint-banner hint-warning">
          <AlertCircleIcon />
          <span>
            {partsApprovedNoPriceCount} одобренн{partsApprovedNoPriceCount === 1 ? "ая позиция" : "ых позиции"} без
            цены — у поставщика в прайсе цена не указана, в итоговом документе ячейка останется пустой.
            Проверьте перед генерацией и, если нужно, впишите цену через «Изменить».
          </span>
        </div>
      )}

      <StatusStepper status={status} />

      {!isProcessing && (matches.length > 0 || laborLines.length > 0) && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <div style={{ fontWeight: 650, fontSize: 13, marginBottom: 10 }}>Статистика проверки</div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: matches.length > 0 && laborLines.length > 0 ? "1fr 1fr" : "1fr",
              gap: 18,
            }}
          >
            {matches.length > 0 && (
              <div>
                <div style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
                  Запчасти: {matches.length} всего · одобрено {partsApprovedCount} из {matches.length}
                </div>
                <CategoryBreakdown counts={partsByCategory} />
                {partsApprovedSum > 0 && (
                  <div style={{ fontSize: 12.5, marginTop: 8 }}>
                    Сумма одобренного: <strong>{formatRub(partsApprovedSum)}</strong>
                  </div>
                )}
              </div>
            )}
            {laborLines.length > 0 && (
              <div>
                <div style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
                  Работы: {laborLines.length} всего · одобрено {laborApprovedCount} из {laborLines.length}
                </div>
                <CategoryBreakdown counts={laborByCategory} />
                {laborApprovedSum > 0 && (
                  <div style={{ fontSize: 12.5, marginTop: 8 }}>
                    Сумма одобренного: <strong>{formatRub(laborApprovedSum)}</strong>
                  </div>
                )}
              </div>
            )}
          </div>

          {matches.length > 0 && laborLines.length > 0 && partsApprovedSum + laborApprovedSum > 0 && (
            <div style={{ fontSize: 13, marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--border)" }}>
              Итого одобрено: <strong>{formatRub(partsApprovedSum + laborApprovedSum)}</strong>
            </div>
          )}

          {orderInfo?.review_summary && (
            <div
              style={{
                display: "flex",
                gap: 8,
                alignItems: "flex-start",
                marginTop: 12,
                paddingTop: 12,
                borderTop: "1px solid var(--border)",
              }}
            >
              <SparklesIcon style={{ width: 14, height: 14, flexShrink: 0, marginTop: 2, color: "var(--accent)" }} />
              <div style={{ fontSize: 13, color: "var(--text-muted)" }}>{orderInfo.review_summary}</div>
            </div>
          )}
        </div>
      )}

      {isProcessing ? (
        <div className="table-wrap">
          <Spinner label={processingLabel} />
          {progressLabel && (
            <div className="text-muted" style={{ textAlign: "center", fontSize: 12.5, marginTop: -8, paddingBottom: 16 }}>
              {progressLabel}
            </div>
          )}
        </div>
      ) : matches.length === 0 && laborLines.length === 0 ? (
        <div className="table-wrap">
          <EmptyState title="Не удалось найти позиции" hint="Проверьте формат загруженных файлов." />
        </div>
      ) : (
        <>
          {matches.length > 0 && selected.size > 0 && (
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

          {matches.length > 0 && (
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
                  <th>Кол-во</th>
                  <th>Цена</th>
                  <th>Сумма</th>
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
                      {m.matched_name || (m.llm_error ? "ИИ недоступна" : "не найдено")}
                      {m.llm_error && (
                        <span className="text-muted" style={{ fontSize: 11, marginLeft: 6 }} title={m.llm_error}>
                          (сервис ИИ не ответил, а не "не найдено")
                        </span>
                      )}
                      {m.manually_edited && (
                        <span className="text-muted" style={{ fontSize: 11.5, marginLeft: 6 }}>
                          (ручная правка)
                        </span>
                      )}
                      {m.nomenclature_source && (
                        <div className="text-muted" style={{ fontSize: 11.5, marginTop: 2 }}>
                          код: {m.nomenclature_code || "—"}
                          {m.nomenclature_cat_number && ` · № кат.: ${m.nomenclature_cat_number}`}
                          {m.nomenclature_manufacturer && ` · ${m.nomenclature_manufacturer}`}
                          {" · остаток: "}
                          {m.nomenclature_stock_qty ?? "—"}
                          {m.nomenclature_reserved_qty ? ` (резерв: ${m.nomenclature_reserved_qty})` : ""}
                          {m.nomenclature_warehouse && ` · ${m.nomenclature_warehouse}`}
                        </div>
                      )}
                      {!m.is_verified && (
                        <InlineCorrection
                          fields={[{ key: "matched_name", placeholder: "Добавить вариант самостоятельно", required: true }]}
                          saving={busyId === m.id}
                          onSave={(values) =>
                            applyMatchEdit(m.id, { matched_name: values.matched_name }, { toastMessage: "Вариант сохранён" })
                          }
                        />
                      )}
                    </td>
                    <td>{m.contract_qty ?? 1}</td>
                    <td>{m.matched_price ?? "—"}</td>
                    <td>{m.matched_price != null ? formatRub(m.matched_price * (m.contract_qty ?? 1)) : "—"}</td>
                    <td>
                      <ConfidenceBadge
                        isVerified={m.is_verified}
                        matchCategory={m.match_category}
                        level={m.confidence_level}
                        score={m.confidence_score}
                      />
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
          )}

          {laborLines.length > 0 && (
            <div className="table-wrap" style={{ marginTop: 18 }}>
              <div className="panel-header" style={{ padding: "10px 16px 0" }}>
                <h3>Работы (нормо-часы)</h3>
              </div>

              {laborSelected.size > 0 && (
                <div
                  className="panel"
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    margin: "12px 16px 0",
                    padding: "10px 16px",
                  }}
                >
                  <span style={{ fontSize: 13, fontWeight: 600 }}>Выбрано: {laborSelected.size}</span>
                  <button
                    className="btn btn-approve btn-sm"
                    disabled={laborBulkBusy}
                    onClick={() => handleBulkLabor("approve")}
                  >
                    Принять выбранные
                  </button>
                  <button
                    className="btn btn-reject btn-sm"
                    disabled={laborBulkBusy}
                    onClick={() => handleBulkLabor("reject")}
                  >
                    Отклонить выбранные
                  </button>
                  <button
                    className="btn btn-secondary btn-sm"
                    style={{ marginLeft: "auto" }}
                    onClick={() => setLaborSelected(new Set())}
                  >
                    Снять выделение
                  </button>
                </div>
              )}

              <table>
                <thead>
                  <tr>
                    <th style={{ width: 28 }}>
                      <input
                        type="checkbox"
                        checked={
                          laborPendingIds.length > 0 && laborSelected.size === laborPendingIds.length
                        }
                        onChange={toggleSelectAllPendingLabor}
                        disabled={laborPendingIds.length === 0}
                      />
                    </th>
                    <th>Описание (заказ-наряд)</th>
                    <th>Операция</th>
                    <th>Нормо-часы</th>
                    <th>Сумма</th>
                    <th>Уверенность</th>
                    <th>Статус</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {laborLines.map((l) => (
                    <tr key={l.id}>
                      <td>
                        {l.review_status === "pending" && (
                          <input
                            type="checkbox"
                            checked={laborSelected.has(l.id)}
                            onChange={() => toggleLaborSelected(l.id)}
                          />
                        )}
                      </td>
                      <td>
                        {l.description}
                        {l.suggested_addition && (
                          <span
                            className="status-pill"
                            style={{ marginLeft: 6, fontSize: 11 }}
                            title="Этой работы не было в загруженном заказ-наряде — система предположила, что она нужна вместе с уже указанными"
                          >
                            предложено системой
                          </span>
                        )}
                      </td>
                      <td>
                        {l.matched_operation_name || (l.llm_error ? "ИИ недоступна" : "не найдено")}
                        {l.llm_error && (
                          <span className="text-muted" style={{ fontSize: 11, marginLeft: 6 }} title={l.llm_error}>
                            (сервис ИИ не ответил, а не "не найдено")
                          </span>
                        )}
                        {l.match_category === "no_match" && (
                          <a
                            href={`https://yandex.ru/search/?text=${encodeURIComponent(
                              [orderInfo?.vehicle_make, orderInfo?.vehicle_model, l.description, "нормо-часы трудоёмкость"]
                                .filter(Boolean)
                                .join(" ")
                            )}`}
                            target="_blank"
                            rel="noreferrer"
                            style={{ fontSize: 11, marginLeft: 6 }}
                            title="Ни в одном каталоге норма не найдена — поискать вручную в интернете (цифру ИИ не подставляет)"
                          >
                            найти в интернете →
                          </a>
                        )}
                        {l.manually_edited && (
                          <span className="text-muted" style={{ fontSize: 11.5, marginLeft: 6 }}>
                            (ручная правка)
                          </span>
                        )}
                        {!l.is_verified && (
                          <InlineCorrection
                            fields={[
                              { key: "matched_operation_name", placeholder: "Добавить вариант самостоятельно", required: true },
                              { key: "norm_hours", placeholder: "Нормо-часы", type: "number", required: true },
                            ]}
                            saving={laborBusyId === l.id}
                            onSave={(values) =>
                              applyLaborEdit(
                                l.id,
                                { matched_operation_name: values.matched_operation_name, norm_hours: values.norm_hours },
                                { toastMessage: "Вариант сохранён" }
                              )
                            }
                          />
                        )}
                      </td>
                      <td>
                        {editingHoursId === l.id ? (
                          <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                            <input
                              type="number"
                              min="0"
                              step="0.1"
                              autoFocus
                              disabled={laborBusyId === l.id}
                              value={hoursInput}
                              onChange={(e) => setHoursInput(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") saveHours(l.id);
                                if (e.key === "Escape") setEditingHoursId(null);
                              }}
                              style={{ width: 70, padding: "4px 6px", fontSize: 13 }}
                            />
                            <button
                              className="btn btn-primary btn-sm"
                              disabled={laborBusyId === l.id}
                              onClick={() => saveHours(l.id)}
                            >
                              OK
                            </button>
                          </div>
                        ) : (
                          <span
                            onClick={() => startEditHours(l)}
                            title={
                              l.norm_hours == null
                                ? "Норма часов не указана — без неё работа не попадёт в итоговый документ. Нажмите, чтобы вписать."
                                : l.cross_make_estimate
                                ? `Для этой марки в справочнике ничего нет — ИИ перенёс норму с похожей операции по ${[l.cross_make_estimate.from_make, l.cross_make_estimate.from_model].filter(Boolean).join(" ")}. Проверьте внимательнее обычного и нажмите, чтобы поправить.`
                                : l.norm_hours_from_repair_order
                                ? "Не найдено в справочнике — норма взята из самого заказ-наряда, как есть. Проверьте и нажмите, чтобы поправить."
                                : "Изменить нормо-часы вручную"
                            }
                            style={{
                              cursor: "pointer",
                              borderBottom: "1px dashed var(--border-strong)",
                              color: l.norm_hours == null ? "var(--warning)" : undefined,
                              fontWeight: l.norm_hours == null ? 600 : undefined,
                            }}
                          >
                            {l.norm_hours ?? "не указана"}
                          </span>
                        )}
                        {l.norm_hours_from_repair_order && (
                          <span className="text-muted" style={{ fontSize: 11, marginLeft: 6 }}>
                            (из наряда)
                          </span>
                        )}
                        {l.cross_make_estimate && (
                          <span
                            className="status-pill"
                            style={{ marginLeft: 6, fontSize: 11 }}
                            title={`Норма перенесена с ${[l.cross_make_estimate.from_make, l.cross_make_estimate.from_model].filter(Boolean).join(" ")} — в справочнике для этой марки ничего нет`}
                          >
                            оценка ИИ, другая марка
                          </span>
                        )}
                      </td>
                      <td>{l.total_cost ?? "—"}</td>
                      <td>
                        <ConfidenceBadge
                          isVerified={l.is_verified}
                          matchCategory={l.match_category}
                          level={l.confidence_level}
                          score={l.confidence_score}
                        />
                      </td>
                      <td>
                        <span className={`status-pill status-${l.review_status}`}>
                          {l.review_status === "pending"
                            ? "ожидает"
                            : l.review_status === "approved"
                            ? "принято"
                            : "отклонено"}
                        </span>
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                          <button
                            className="btn btn-secondary btn-sm"
                            disabled={laborBusyId === l.id}
                            onClick={() => setEditingLaborLine(l)}
                            title="Подобрать операцию из справочника или вписать вручную"
                          >
                            <EditIcon /> Изменить
                          </button>
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={() =>
                              setInstructionsFor({
                                operationName: l.matched_operation_name || l.description,
                                vehicleMake: orderInfo?.vehicle_make,
                                vehicleModel: orderInfo?.vehicle_model,
                              })
                            }
                            title="Получить пошаговую инструкцию по выполнению этой работы"
                          >
                            <SparklesIcon /> Расписать
                          </button>
                          {l.review_status === "pending" && (
                            <>
                              <button
                                className="btn btn-approve btn-sm"
                                disabled={laborBusyId === l.id}
                                onClick={() => handleLaborDecision(l.id, "approve")}
                              >
                                Принять
                              </button>
                              <button
                                className="btn btn-reject btn-sm"
                                disabled={laborBusyId === l.id}
                                onClick={() => handleLaborDecision(l.id, "reject")}
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
          )}

          <div style={{ marginTop: 18, display: "flex", alignItems: "center", gap: 8 }}>
            <select
              value={selectedTemplateId}
              onChange={(e) => setSelectedTemplateId(e.target.value)}
              style={{ maxWidth: 240 }}
              disabled={generating}
            >
              <option value="">Встроенный формат (как у 1С)</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
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
          repairOrderId={repairOrderId}
          saving={busyId === editingMatch.id}
          onClose={() => setEditingMatch(null)}
          onSave={handleSaveEdit}
        />
      )}

      {editingLaborLine && (
        <LaborEditModal
          line={editingLaborLine}
          catalog={laborCatalog}
          saving={laborBusyId === editingLaborLine.id}
          onClose={() => setEditingLaborLine(null)}
          onSave={handleSaveLaborEdit}
        />
      )}

      {instructionsFor && (
        <RepairInstructionsModal
          initialOperationName={instructionsFor.operationName}
          vehicleMake={instructionsFor.vehicleMake}
          vehicleModel={instructionsFor.vehicleModel}
          onClose={() => setInstructionsFor(null)}
        />
      )}

      {addingLaborLine && (
        <LaborEditModal
          line={{ description: "Добавлено вручную", matched_operation_name: "", norm_hours: "" }}
          catalog={laborCatalog}
          saving={laborBusyId === "new"}
          onClose={() => setAddingLaborLine(false)}
          onSave={handleAddLaborLine}
        />
      )}

      {generatedPreview && (
        <FilePreviewModal
          blob={generatedPreview.blob}
          fileName={generatedPreview.fileName}
          onClose={() => setGeneratedPreview(null)}
          onDownload={async () => {
            const result = await saveFile(generatedPreview.blob, generatedPreview.fileName, XLSX_FILE_TYPES);
            if (result.ok && result.native) toast.success(`Сохранено: ${result.path}`);
            else if (!result.ok && !result.canceled) toast.error(result.error || "Не удалось сохранить файл");
          }}
        />
      )}

      {showSupplierSearch && (
        <SupplierSearchModal
          title="Добавить запчасть у поставщика"
          selectLabel="Добавить в заказ-наряд"
          onSelect={async (item) => {
            await api.addPartFromSupplier(repairOrderId, {
              matched_article: item.article,
              matched_name: item.name || `${item.brand || ""} ${item.article || ""}`.trim() || item.article,
              matched_price: item.price,
              source: item.supplier,
            });
            loadMatches();
            toast.success("Позиция добавлена в заказ-наряд");
          }}
          onClose={() => setShowSupplierSearch(false)}
        />
      )}
    </div>
  );
}
