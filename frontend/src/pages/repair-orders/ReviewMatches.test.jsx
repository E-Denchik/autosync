import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../../context/ToastContext.jsx";
import { api } from "../../api/client.js";
import { saveFile } from "../../utils/saveFile.js";
import ReviewMatches from "./ReviewMatches.jsx";

vi.mock("../../api/client.js", () => ({
  api: {
    listDocumentTemplates: vi.fn(),
    listIntegrations: vi.fn(),
    getUploadStatus: vi.fn(),
    listMatches: vi.fn(),
    listLaborLines: vi.fn(),
    listLaborCatalog: vi.fn(),
    generateDocument: vi.fn(),
    previewFile: vi.fn(),
  },
}));

vi.mock("../../utils/saveFile.js", () => ({
  saveFile: vi.fn(),
  CSV_FILE_TYPES: [],
  XLSX_FILE_TYPES: [],
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/repair-orders/1/review"]}>
      <ToastProvider>
        <Routes>
          <Route path="/repair-orders/:repairOrderId/review" element={<ReviewMatches />} />
        </Routes>
      </ToastProvider>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listDocumentTemplates.mockResolvedValue([]);
  api.listIntegrations.mockResolvedValue([]);
  api.listLaborLines.mockResolvedValue([]);
  api.listLaborCatalog.mockResolvedValue([]);
  api.previewFile.mockResolvedValue({ rows: [["a"]], truncated: false });
  saveFile.mockResolvedValue({ ok: true, native: false });
});

describe("ReviewMatches — статус после генерации итогового документа", () => {
  it("после успешной генерации степпер сразу показывает «Готово», не дожидаясь ручного обновления страницы", async () => {
    // Регрессия: backend при успешной генерации всегда переводит заказ-наряд
    // в reviewed (см. api/repair_orders/matching.py: generate_document), но
    // страница никогда не перечитывала статус после генерации — степпер так
    // и оставался на "Проверка", хотя документ уже готов и всё принято.
    api.getUploadStatus.mockResolvedValue({
      status: "needs_review",
      contragent_name: null,
      vehicle_make: null,
    });
    api.listMatches.mockResolvedValue([
      { id: 1, review_status: "approved", contract_article: "A1", contract_name: "Деталь", matched_name: "Деталь" },
    ]);
    api.generateDocument.mockResolvedValue(new Blob(["данные"]));

    renderPage();

    await waitFor(() => expect(screen.queryByText("Проверяем статус обработки…")).not.toBeInTheDocument());
    expect(screen.getByText("Проверка").closest(".step")).toHaveClass("active");

    await userEvent.click(screen.getByText("Сгенерировать итоговый документ"));

    await waitFor(() => expect(screen.getByText("Готово").closest(".step")).toHaveClass("done"));
    expect(screen.getByText("Проверка").closest(".step")).not.toHaveClass("active");
  });
});

describe("ReviewMatches — статистика проверки (реальные числа, не только текст ИИ)", () => {
  it("показывает разбивку по категориям и сумму одобренного по реальным данным позиций", async () => {
    // Регрессия: раньше единственным видимым "отчётом" была голая фраза от
    // ИИ, без единой проверяемой цифры — теперь числа считаются из самих
    // matches/laborLines (match_category с бэкенда), а не только пересказ ИИ.
    api.getUploadStatus.mockResolvedValue({ status: "needs_review", contragent_name: null, vehicle_make: null });
    api.listMatches.mockResolvedValue([
      {
        id: 1,
        review_status: "approved",
        contract_article: "A1",
        contract_name: "Деталь 1",
        matched_name: "Деталь 1",
        matched_price: 1000,
        match_category: "exact",
      },
      {
        id: 2,
        review_status: "pending",
        contract_article: "A2",
        contract_name: "Деталь 2",
        matched_name: null,
        match_category: "no_match",
      },
    ]);

    renderPage();

    expect(await screen.findByText("Статистика проверки")).toBeInTheDocument();
    expect(screen.getByText(/Запчасти: 2 всего · одобрено 1 из 2/)).toBeInTheDocument();
    expect(screen.getByText("точное совпадение: 1")).toBeInTheDocument();
    expect(screen.getByText("не найдено: 1")).toBeInTheDocument();
    expect(screen.getByText(/Сумма одобренного:/)).toBeInTheDocument();
    expect(screen.getByText("1 000 ₽")).toBeInTheDocument();
  });

  it("показывает сводку ИИ отдельной строкой внутри той же панели, когда она есть", async () => {
    api.getUploadStatus.mockResolvedValue({
      status: "needs_review",
      contragent_name: null,
      vehicle_make: null,
      review_summary: "Почти всё сопоставилось точно, проверка формальная.",
    });
    api.listMatches.mockResolvedValue([
      {
        id: 1,
        review_status: "approved",
        contract_article: "A1",
        contract_name: "Деталь",
        matched_name: "Деталь",
        match_category: "exact",
      },
    ]);

    renderPage();

    expect(await screen.findByText("Статистика проверки")).toBeInTheDocument();
    expect(screen.getByText("Почти всё сопоставилось точно, проверка формальная.")).toBeInTheDocument();
  });

  it("панель со статистикой остаётся видна и без сводки ИИ — цифры не зависят от того, ответила ли модель", async () => {
    api.getUploadStatus.mockResolvedValue({ status: "needs_review", contragent_name: null, vehicle_make: null });
    api.listMatches.mockResolvedValue([
      {
        id: 1,
        review_status: "approved",
        contract_article: "A1",
        contract_name: "Деталь",
        matched_name: "Деталь",
        match_category: "exact",
      },
    ]);

    renderPage();

    expect(await screen.findByText("Статистика проверки")).toBeInTheDocument();
  });
});

describe("ReviewMatches — прозрачность недоступности ИИ", () => {
  it("показывает баннер и отдельную пометку у строки, когда llm_error задан, а не путает это с «не найдено»", async () => {
    // Регрессия: раньше "ИИ была недоступна" и "ИИ честно не нашла
    // совпадение" выглядели для проверяющего абсолютно одинаково — просто
    // "не найдено" без единой подсказки о реальной причине.
    api.getUploadStatus.mockResolvedValue({ status: "needs_review", contragent_name: null, vehicle_make: null });
    api.listMatches.mockResolvedValue([
      {
        id: 1,
        review_status: "pending",
        contract_article: "A1",
        contract_name: "Деталь",
        matched_name: null,
        llm_error: "llm-service недоступен: Connection refused",
      },
    ]);

    renderPage();

    await waitFor(() => expect(screen.queryByText("Проверяем статус обработки…")).not.toBeInTheDocument());

    expect(await screen.findByText(/ИИ-сопоставление по названию было недоступно для 1 позиции/)).toBeInTheDocument();
    expect(screen.getByText("ИИ недоступна")).toBeInTheDocument();
    expect(screen.queryByText("не найдено")).not.toBeInTheDocument();
  });

  it("не показывает баннер, когда llm_error нигде не задан", async () => {
    api.getUploadStatus.mockResolvedValue({ status: "needs_review", contragent_name: null, vehicle_make: null });
    api.listMatches.mockResolvedValue([
      { id: 1, review_status: "pending", contract_article: "A1", contract_name: "Деталь", matched_name: null },
    ]);

    renderPage();

    await waitFor(() => expect(screen.queryByText("Проверяем статус обработки…")).not.toBeInTheDocument());

    expect(screen.queryByText(/ИИ-сопоставление по названию было недоступно/)).not.toBeInTheDocument();
    expect(screen.getByText("не найдено")).toBeInTheDocument();
  });
});
