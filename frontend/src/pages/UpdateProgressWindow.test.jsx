import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client.js";
import UpdateProgressWindow from "./UpdateProgressWindow.jsx";

vi.mock("../api/client.js", () => ({
  api: {
    getUpdateProgress: vi.fn(),
    startUpdateDownload: vi.fn(),
    cancelUpdateDownload: vi.fn(),
    applyUpdate: vi.fn(),
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  delete window.pywebview;
});

afterEach(() => {
  vi.useRealTimers();
});

describe("UpdateProgressWindow", () => {
  it("показывает прогресс скачивания в МБ, процентах и скорости", async () => {
    api.getUpdateProgress.mockResolvedValue({
      phase: "downloading",
      downloaded_bytes: 52428800, // 50 МБ
      total_bytes: 104857600, // 100 МБ
      speed_bytes_per_sec: 5242880, // 5 МБ/с
      error: null,
    });

    render(<UpdateProgressWindow />);

    expect(await screen.findByText(/50\.0 МБ из 100\.0 МБ \(50%\)/)).toBeInTheDocument();
    expect(screen.getByText("5.0 МБ/с")).toBeInTheDocument();
  });

  it("кнопка «Отменить» во время скачивания вызывает cancelUpdateDownload", async () => {
    api.getUpdateProgress.mockResolvedValue({
      phase: "downloading",
      downloaded_bytes: 1024,
      total_bytes: 2048,
      speed_bytes_per_sec: 0,
    });
    api.cancelUpdateDownload.mockResolvedValue({ phase: "canceled" });

    render(<UpdateProgressWindow />);
    const cancelBtn = await screen.findByText("Отменить");
    await userEvent.click(cancelBtn);

    expect(api.cancelUpdateDownload).toHaveBeenCalledOnce();
  });

  it("когда скачано — показывает кнопки «Установить обновление» и «Отменить»", async () => {
    api.getUpdateProgress.mockResolvedValue({ phase: "downloaded", downloaded_bytes: 2048, total_bytes: 2048 });

    render(<UpdateProgressWindow />);

    expect(await screen.findByText("Обновление скачано")).toBeInTheDocument();
    expect(screen.getByText("Установить обновление")).toBeInTheDocument();
    expect(screen.getByText("Отменить")).toBeInTheDocument();
  });

  it("клик «Установить обновление» вызывает applyUpdate", async () => {
    api.getUpdateProgress.mockResolvedValue({ phase: "downloaded", downloaded_bytes: 2048, total_bytes: 2048 });
    api.applyUpdate.mockResolvedValue({ status: "applying" });

    render(<UpdateProgressWindow />);
    const installBtn = await screen.findByText("Установить обновление");
    await userEvent.click(installBtn);

    expect(api.applyUpdate).toHaveBeenCalledOnce();
  });

  it("во время установки не предлагает отмену — процесс уже необратим", async () => {
    api.getUpdateProgress.mockResolvedValue({ phase: "applying" });

    render(<UpdateProgressWindow />);

    expect(await screen.findByText("Устанавливаем обновление…")).toBeInTheDocument();
    expect(screen.queryByText("Отменить")).not.toBeInTheDocument();
  });

  it("показывает ошибку и позволяет повторить или закрыть окно через нативный API", async () => {
    api.getUpdateProgress.mockResolvedValue({ phase: "error", error: "GitHub недоступен: timeout" });
    const closeWindow = vi.fn();
    window.pywebview = { api: { close_window: closeWindow } };

    render(<UpdateProgressWindow />);

    expect(await screen.findByText("GitHub недоступен: timeout")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Закрыть"));

    expect(closeWindow).toHaveBeenCalledOnce();
  });

  it("состояние idle предлагает начать скачивание вручную", async () => {
    api.getUpdateProgress.mockResolvedValue({ phase: "idle" });
    api.startUpdateDownload.mockResolvedValue({ phase: "downloading" });

    render(<UpdateProgressWindow />);
    const startBtn = await screen.findByText("Скачать обновление");
    await userEvent.click(startBtn);

    expect(api.startUpdateDownload).toHaveBeenCalledOnce();
  });

  it("опрашивает прогресс регулярно, пока окно открыто", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.getUpdateProgress.mockResolvedValue({ phase: "downloading", downloaded_bytes: 0, total_bytes: 100 });

    render(<UpdateProgressWindow />);
    await waitFor(() => expect(api.getUpdateProgress).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(900);
    expect(api.getUpdateProgress.mock.calls.length).toBeGreaterThanOrEqual(3);
  });
});
