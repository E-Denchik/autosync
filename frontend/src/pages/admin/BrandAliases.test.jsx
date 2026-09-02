import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../../context/ToastContext.jsx";
import { ErrorLogProvider } from "../../context/ErrorLogContext.jsx";
import { api } from "../../api/client.js";
import BrandAliases from "./BrandAliases.jsx";

vi.mock("../../api/client.js", () => ({
  api: {
    listBrandAliases: vi.fn(),
    createBrandAlias: vi.fn(),
    updateBrandAlias: vi.fn(),
    deleteBrandAlias: vi.fn(),
    uploadBrandAliasesFile: vi.fn(),
    normalizeBrandAliases: vi.fn(),
  },
}));

function renderPage() {
  return render(
    <ErrorLogProvider>
      <ToastProvider>
        <BrandAliases />
      </ToastProvider>
    </ErrorLogProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listBrandAliases.mockResolvedValue({ items: [], total: 0 });
});

describe("BrandAliases — добавление вручную", () => {
  it("заполнение формы и сохранение вызывает createBrandAlias и обновляет список", async () => {
    api.createBrandAlias.mockResolvedValue({ id: 1, alias: "Шевроле", canonical_make: "CHEVROLET", source: "manual" });

    renderPage();
    await userEvent.click(await screen.findByText("Добавить вручную"));
    await userEvent.type(screen.getByLabelText("Марка как у поставщика"), "Шевроле");
    await userEvent.type(screen.getByLabelText("Каноничное название"), "CHEVROLET");
    await userEvent.click(screen.getByText("Добавить"));

    expect(api.createBrandAlias).toHaveBeenCalledWith({ alias: "Шевроле", canonical_make: "CHEVROLET" });
  });
});

describe("BrandAliases — загрузка файлом", () => {
  it("выбор файла вызывает uploadBrandAliasesFile и показывает результат", async () => {
    api.uploadBrandAliasesFile.mockResolvedValue({ created: 3, updated: 1, errors: [] });

    renderPage();
    const fileInput = (await screen.findByText("Загрузить файлом")).closest("label").querySelector('input[type="file"]');
    const file = new File(["данные"], "brands.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    await userEvent.upload(fileInput, file);

    expect(api.uploadBrandAliasesFile).toHaveBeenCalledWith([file]);
    expect(await screen.findByText(/новых 3, обновлено 1/)).toBeInTheDocument();
  });
});

describe("BrandAliases — проверка через ИИ", () => {
  it("кнопка вызывает normalizeBrandAliases и показывает результат", async () => {
    api.normalizeBrandAliases.mockResolvedValue({ normalized: 2, total: 3 });

    renderPage();
    await userEvent.click(await screen.findByText("Проверить через ИИ"));

    expect(api.normalizeBrandAliases).toHaveBeenCalled();
    expect(await screen.findByText(/ИИ распознала 2 из 3/)).toBeInTheDocument();
  });
});

describe("BrandAliases — список", () => {
  it("показывает марки без каноничного названия как «не определено»", async () => {
    api.listBrandAliases.mockResolvedValue({
      items: [{ id: 1, alias: "Неизвестная", canonical_make: null, source: "upload" }],
      total: 1,
    });

    renderPage();

    expect(await screen.findByText("Неизвестная")).toBeInTheDocument();
    expect(screen.getByText("не определено")).toBeInTheDocument();
  });
});
