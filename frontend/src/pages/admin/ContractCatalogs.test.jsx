import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../../context/ToastContext.jsx";
import { ErrorLogProvider } from "../../context/ErrorLogContext.jsx";
import { api } from "../../api/client.js";
import ContractCatalogs from "./ContractCatalogs.jsx";

vi.mock("../../api/client.js", () => ({
  api: {
    listContracts: vi.fn(),
    listContragents: vi.fn(),
    createContract: vi.fn(),
    importContractHourlyRates: vi.fn(),
  },
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <ErrorLogProvider>
        <ToastProvider>
          <ContractCatalogs />
        </ToastProvider>
      </ErrorLogProvider>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listContracts.mockResolvedValue([]);
  api.listContragents.mockResolvedValue([]);
});

describe("ContractCatalogs — отдельный файл ставок по маркам при создании контракта", () => {
  it("без файла ставок создаёт контракт как раньше, без попытки импорта", async () => {
    api.createContract.mockResolvedValue({ id: 10, reused_existing_contract: false });

    renderPage();
    await userEvent.click(await screen.findByText("Загрузить новый контракт"));
    const mainFile = new File(["данные"], "contract.xlsx", { type: "application/vnd.ms-excel" });
    await userEvent.upload(screen.getByLabelText("Файл(ы) договора"), mainFile);
    await userEvent.click(screen.getByText("Загрузить"));

    expect(await screen.findByText("Договор загружен — идёт разбор файла(ов)")).toBeInTheDocument();
    expect(api.importContractHourlyRates).not.toHaveBeenCalled();
  });

  it("с отдельным файлом ставок — создаёт контракт и сразу же загружает в него ставки по маркам", async () => {
    // Регрессия: у файла со ставками (марка + цена) структура не похожа на
    // состав контракта (запчасти/нормо-часы), общий парсер контракта его не
    // разбирает — раньше ставки можно было загрузить только отдельно, зайдя
    // в уже созданный контракт и найдя там вкладку «Ставки по маркам».
    api.createContract.mockResolvedValue({ id: 55, reused_existing_contract: false });
    api.importContractHourlyRates.mockResolvedValue({ created: 9, updated: 0, total: 9 });

    renderPage();
    await userEvent.click(await screen.findByText("Загрузить новый контракт"));
    const mainFile = new File(["данные"], "contract.xlsx", { type: "application/vnd.ms-excel" });
    await userEvent.upload(screen.getByLabelText("Файл(ы) договора"), mainFile);
    const ratesFile = new File(["данные"], "Нормочасы.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    await userEvent.upload(screen.getByLabelText(/Ставки по маркам \(файл, необязательно\)/), ratesFile);
    await userEvent.click(screen.getByText("Загрузить"));

    expect(api.importContractHourlyRates).toHaveBeenCalledWith(55, ratesFile);
    expect(await screen.findByText(/Ставки по маркам загружены: 9 новых, 0 обновлено/)).toBeInTheDocument();
  });
});

describe("ContractCatalogs — прогресс разбора файлов", () => {
  it("показывает 'разобрано X из Y файлов' пока контракт в статусе parsing", async () => {
    // Раньше массовая загрузка каталога (десятки-сотни файлов) не давала
    // вообще никакой обратной связи, кроме статуса "разбирается" — со
    // стороны выглядело как зависание (см. progress_tracker.py/
    // contract_catalog_import.py: теперь прогресс по файлам считается так
    // же, как уже считался прогресс по строкам заказ-наряда).
    api.listContracts.mockResolvedValue([
      {
        id: 7,
        name: "Большой каталог",
        original_filename: "catalog.xlsx",
        status: "parsing",
        error_message: null,
        active: true,
        parts_count: 0,
        labor_norms_count: 0,
        repair_orders_count: 0,
        progress: { current: 6, total: 179, started_at: "2026-09-02T10:00:00" },
      },
    ]);

    renderPage();

    expect(await screen.findByText("Разобрано 6 из 179 файлов")).toBeInTheDocument();
  });
});
