import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../../context/ToastContext.jsx";
import { ErrorLogProvider } from "../../context/ErrorLogContext.jsx";
import { api } from "../../api/client.js";
import Contragents from "./Contragents.jsx";

vi.mock("../../api/client.js", () => ({
  api: {
    listContragents: vi.fn(),
    createContragent: vi.fn(),
    importContragentHourlyRates: vi.fn(),
    updateContragent: vi.fn(),
    deleteContragent: vi.fn(),
  },
}));

function renderPage() {
  return render(
    <ErrorLogProvider>
      <ToastProvider>
        <Contragents />
      </ToastProvider>
    </ErrorLogProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listContragents.mockResolvedValue([]);
});

describe("Contragents — создание с файлом ставок сразу", () => {
  it("без выбранного файла создаёт контрагента без попытки импорта", async () => {
    api.createContragent.mockResolvedValue({ id: 1, name: "Рога и копыта" });

    renderPage();
    await userEvent.click(await screen.findByText("Добавить контрагента"));
    await userEvent.type(screen.getByLabelText("Название"), "Рога и копыта");
    await userEvent.type(screen.getByLabelText("Ставка за нормо-час, ₽"), "900");
    await userEvent.click(screen.getByText("Создать"));

    expect(await screen.findByText("Контрагент добавлен")).toBeInTheDocument();
    expect(api.importContragentHourlyRates).not.toHaveBeenCalled();
  });

  it("с выбранным файлом ставок создаёт контрагента и сразу же импортирует файл в него", async () => {
    // Регрессия: заказчик не мог найти, где загрузить файл со ставками по
    // маркам, потому что раньше это было доступно ТОЛЬКО отдельным
    // действием у уже существующего контрагента — легко не заметить,
    // особенно когда единственный файл на руках — это как раз файл ставок.
    api.createContragent.mockResolvedValue({ id: 42, name: "Управление дорог" });
    api.importContragentHourlyRates.mockResolvedValue({ created: 5, updated: 2, total: 7 });

    renderPage();
    await userEvent.click(await screen.findByText("Добавить контрагента"));
    await userEvent.type(screen.getByLabelText("Название"), "Управление дорог");
    await userEvent.type(screen.getByLabelText("Ставка за нормо-час, ₽"), "540");
    const file = new File(["данные"], "Нормочасы.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    const fileInput = screen.getByLabelText(/Ставки по маркам \(файл, необязательно\)/);
    await userEvent.upload(fileInput, file);
    await userEvent.click(screen.getByText("Создать"));

    expect(api.createContragent).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Управление дорог", hourly_rate: "540" })
    );
    expect(api.importContragentHourlyRates).toHaveBeenCalledWith(42, file);
    expect(await screen.findByText(/5 новых, 2 обновлено/)).toBeInTheDocument();
  });

  it("если импорт файла упал — контрагент всё равно считается созданным, ошибка показывается отдельно", async () => {
    api.createContragent.mockResolvedValue({ id: 7, name: "ООО Тест" });
    api.importContragentHourlyRates.mockRejectedValue(new Error("Не удалось распознать таблицу в файле"));

    renderPage();
    await userEvent.click(await screen.findByText("Добавить контрагента"));
    await userEvent.type(screen.getByLabelText("Название"), "ООО Тест");
    await userEvent.type(screen.getByLabelText("Ставка за нормо-час, ₽"), "1000");
    const file = new File(["данные"], "rates.xlsx", { type: "application/vnd.ms-excel" });
    await userEvent.upload(screen.getByLabelText(/Ставки по маркам \(файл, необязательно\)/), file);
    await userEvent.click(screen.getByText("Создать"));

    expect(
      await screen.findByText(/Контрагент добавлен, но файл со ставками не загрузился/)
    ).toBeInTheDocument();
  });
});
