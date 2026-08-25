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
    addLaborLine: vi.fn(),
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
    const approvedSumLine = screen.getByText(/Сумма одобренного:/);
    expect(approvedSumLine).toBeInTheDocument();
    expect(approvedSumLine.parentElement).toHaveTextContent("1 000 ₽");
  });

  it("учитывает contract_qty в сумме одобренного и показывает кол-во/сумму по строке", async () => {
    // Регрессия: contract_qty раньше нигде не сохранялся и не учитывался —
    // 2 шт. по 1000 ₽ считались бы как 1000 ₽, а не 2000 ₽ (см. matcher.py).
    api.getUploadStatus.mockResolvedValue({ status: "needs_review", contragent_name: null, vehicle_make: null });
    api.listMatches.mockResolvedValue([
      {
        id: 1,
        review_status: "approved",
        contract_article: "A1",
        contract_name: "Колодки тормозные",
        contract_qty: 2,
        matched_name: "Колодки тормозные",
        matched_price: 1000,
        match_category: "exact",
      },
    ]);

    renderPage();

    const approvedSumLine = await screen.findByText(/Сумма одобренного:/);
    expect(approvedSumLine.parentElement).toHaveTextContent("2 000 ₽");

    const row = screen.getByText("Колодки тормозные").closest("tr");
    expect(row).toHaveTextContent("2"); // Кол-во
    expect(row).toHaveTextContent("2 000"); // Сумма по строке
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

describe("ReviewMatches — ручное добавление работы", () => {
  it("кнопка «Добавить работу вручную» открывает форму и после сохранения строка появляется в списке", async () => {
    // Заказчик просил свободную форму добавления работ (по аналогии с уже
    // существующим «Добавить запчасть у поставщика») — когда ни каталог,
    // ни AutoData операцию не находят ни по одной марке.
    api.getUploadStatus.mockResolvedValue({ status: "needs_review", contragent_name: null, vehicle_make: null });
    api.listMatches.mockResolvedValue([]);
    api.listLaborLines.mockResolvedValue([]);
    api.addLaborLine.mockResolvedValue({
      id: 5,
      description: "Добавлено вручную",
      matched_operation_name: "Диагностика ходовой",
      norm_hours: 1.5,
      hourly_rate: 1000,
      total_cost: 1500,
      review_status: "approved",
      manually_edited: true,
    });

    renderPage();

    await waitFor(() => expect(screen.queryByText("Проверяем статус обработки…")).not.toBeInTheDocument());

    await userEvent.click(screen.getByText("Добавить работу вручную"));
    await userEvent.type(screen.getByLabelText("Операция"), "Диагностика ходовой");
    await userEvent.type(screen.getByLabelText("Нормо-часы"), "1.5");
    await userEvent.click(screen.getByText("Сохранить"));

    await waitFor(() =>
      expect(api.addLaborLine).toHaveBeenCalledWith("1", {
        matched_operation_name: "Диагностика ходовой",
        norm_hours: 1.5,
      })
    );
    expect(await screen.findByText("Диагностика ходовой")).toBeInTheDocument();
  });
});

describe("ReviewMatches — видимость цены и подсказка по нормо-часам", () => {
  it("показывает баннер, когда у одобренной запчасти нет цены", async () => {
    // У поставщика в исходном прайсе цена была пустой — matched_price
    // остаётся null (см. document_generator.py), и в итоговом документе
    // ячейка так и будет пустой. Раньше это никак не было заметно ДО
    // генерации документа.
    api.getUploadStatus.mockResolvedValue({ status: "needs_review", contragent_name: null, vehicle_make: null });
    api.listMatches.mockResolvedValue([
      {
        id: 1,
        review_status: "approved",
        contract_article: "A1",
        contract_name: "Деталь",
        matched_name: "Деталь",
        matched_price: null,
        match_category: "exact",
      },
    ]);

    renderPage();

    expect(await screen.findByText(/1 одобренная позиция без цены/)).toBeInTheDocument();
  });

  it("не показывает баннер, когда у всех одобренных позиций есть цена", async () => {
    api.getUploadStatus.mockResolvedValue({ status: "needs_review", contragent_name: null, vehicle_make: null });
    api.listMatches.mockResolvedValue([
      {
        id: 1,
        review_status: "approved",
        contract_article: "A1",
        contract_name: "Деталь",
        matched_name: "Деталь",
        matched_price: 500,
        match_category: "exact",
      },
    ]);

    renderPage();

    await waitFor(() => expect(screen.queryByText("Проверяем статус обработки…")).not.toBeInTheDocument());
    expect(screen.queryByText(/позици[яи] без цены/)).not.toBeInTheDocument();
  });

  it("для работы без единого совпадения показывает ссылку на поиск в интернете, а не подставляет цифру сама", async () => {
    api.getUploadStatus.mockResolvedValue({
      status: "needs_review",
      contragent_name: null,
      vehicle_make: "ВАЗ",
    });
    api.listMatches.mockResolvedValue([]);
    api.listLaborLines.mockResolvedValue([
      {
        id: 1,
        review_status: "pending",
        description: "Снятие ДВС",
        matched_operation_name: null,
        match_category: "no_match",
      },
    ]);

    renderPage();

    const link = await screen.findByText("найти в интернете →");
    expect(link.closest("a")).toHaveAttribute("href", expect.stringContaining("yandex.ru/search"));
    expect(link.closest("a")).toHaveAttribute("target", "_blank");
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
