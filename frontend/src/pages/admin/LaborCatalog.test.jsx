import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../../context/ToastContext.jsx";
import { api } from "../../api/client.js";
import LaborCatalog from "./LaborCatalog.jsx";

vi.mock("../../api/client.js", () => ({
  api: {
    listLaborCatalog: vi.fn(),
    createLaborCatalogEntry: vi.fn(),
    deleteLaborCatalogEntry: vi.fn(),
    importLaborCatalog: vi.fn(),
  },
}));

function renderPage() {
  return render(
    <ToastProvider>
      <LaborCatalog />
    </ToastProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listLaborCatalog.mockResolvedValue([]);
});

describe("LaborCatalog — загрузка справочника файлом", () => {
  it("клик «Загрузить файлом» и выбор файла вызывает importLaborCatalog и показывает результат", async () => {
    // Регрессия: раньше на этой странице можно было добавлять операции
    // только по одной вручную — заказчик с реальным справочником нормо-часов
    // не мог загрузить его файлом (в отличие от ставок по маркам, где такая
    // загрузка уже была).
    api.importLaborCatalog.mockResolvedValue({ created: 6, updated: 0, total: 6 });

    renderPage();
    const fileInput = (await screen.findByText("Загрузить файлом")).closest("div").querySelector('input[type="file"]');
    const file = new File(["данные"], "Нормо-часы (справочник).xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    await userEvent.upload(fileInput, file);

    expect(api.importLaborCatalog).toHaveBeenCalledWith(file);
    expect(await screen.findByText(/6 новых, 0 обновлено/)).toBeInTheDocument();
  });

  it("ошибку импорта показывает тостом, не ломая страницу", async () => {
    api.importLaborCatalog.mockRejectedValue(new Error("Не удалось найти колонку с нормо-часами"));

    renderPage();
    const fileInput = (await screen.findByText("Загрузить файлом")).closest("div").querySelector('input[type="file"]');
    const file = new File(["данные"], "bad.csv", { type: "text/csv" });
    await userEvent.upload(fileInput, file);

    expect(await screen.findByText("Не удалось найти колонку с нормо-часами")).toBeInTheDocument();
  });
});
