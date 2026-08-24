import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../context/ToastContext.jsx";
import { api } from "../api/client.js";
import UpdateChecker from "./UpdateChecker.jsx";

vi.mock("../api/client.js", () => ({
  api: {
    getPendingUpdateResult: vi.fn(),
    checkForUpdate: vi.fn(),
    startUpdateDownload: vi.fn(),
  },
}));

function renderWithToast() {
  return render(
    <ToastProvider>
      <UpdateChecker />
    </ToastProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getPendingUpdateResult.mockResolvedValue(null);
  delete window.pywebview;
});

describe("UpdateChecker — результат предыдущей попытки обновления", () => {
  it("показывает тост об успехе, если предыдущее обновление применилось", async () => {
    api.getPendingUpdateResult.mockResolvedValue({ success: true, commit: "abc123" });

    renderWithToast();

    expect(await screen.findByText("Обновление успешно установлено")).toBeInTheDocument();
  });

  it("показывает тост с причиной, если предыдущее обновление не применилось", async () => {
    api.getPendingUpdateResult.mockResolvedValue({
      success: false,
      exit_code: "1",
      message: "Установка обновления завершилась с ошибкой (код 1).",
    });

    renderWithToast();

    expect(await screen.findByText("Установка обновления завершилась с ошибкой (код 1).")).toBeInTheDocument();
  });

  it("ничего не показывает, если предыдущих попыток обновления не было", async () => {
    renderWithToast();

    await screen.findByText("Проверить обновление"); // дожидаемся, что компонент отрисовался
    expect(screen.queryByText(/установлено|не удалось/i)).not.toBeInTheDocument();
  });
});

describe("UpdateChecker — скачивание и открытие системного окна", () => {
  it("клик «Скачать и установить» запускает скачивание и открывает окно через нативный API", async () => {
    api.checkForUpdate.mockResolvedValue({
      update_available: true,
      frozen: true,
      changes: ["Fix X"],
      current_commit: "old",
      latest_commit: "new",
    });
    api.startUpdateDownload.mockResolvedValue({ phase: "downloading" });
    const openUpdateWindow = vi.fn().mockResolvedValue({ ok: true });
    window.pywebview = { api: { open_update_window: openUpdateWindow } };

    renderWithToast();
    await userEvent.click(await screen.findByText("Проверить обновление"));
    await userEvent.click(await screen.findByText("Скачать и установить"));

    expect(api.startUpdateDownload).toHaveBeenCalledOnce();
    expect(openUpdateWindow).toHaveBeenCalledOnce();
  });

  it("если нативный API окна недоступен — показывает ошибку, а не падает молча", async () => {
    api.checkForUpdate.mockResolvedValue({
      update_available: true,
      frozen: true,
      changes: [],
      current_commit: "old",
      latest_commit: "new",
    });
    api.startUpdateDownload.mockResolvedValue({ phase: "downloading" });
    // window.pywebview намеренно не задан

    renderWithToast();
    await userEvent.click(await screen.findByText("Проверить обновление"));
    await userEvent.click(await screen.findByText("Скачать и установить"));

    expect(await screen.findByText(/Не удалось открыть окно обновления/)).toBeInTheDocument();
  });
});
