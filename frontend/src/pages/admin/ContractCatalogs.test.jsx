import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../../context/ToastContext.jsx";
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
      <ToastProvider>
        <ContractCatalogs />
      </ToastProvider>
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
