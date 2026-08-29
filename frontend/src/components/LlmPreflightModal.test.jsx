import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../context/ToastContext.jsx";
import { api } from "../api/client.js";
import LlmPreflightModal from "./LlmPreflightModal.jsx";

vi.mock("../api/client.js", () => ({
  api: {
    listLlmModels: vi.fn(),
    selectLlmModel: vi.fn(),
    testLlmConnection: vi.fn(),
  },
}));

function renderModal(props = {}) {
  return render(
    <ToastProvider>
      <LlmPreflightModal onClose={vi.fn()} onContinue={vi.fn()} {...props} />
    </ToastProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("LlmPreflightModal", () => {
  it("показывает, что модель не выбрана, и список доступных моделей для выбора", async () => {
    api.listLlmModels.mockResolvedValue({
      selected: null,
      previous_selection: null,
      providers: {
        ollama: { available: true, models: [{ name: "qwen2.5:3b" }] },
        lmstudio: { available: false, server_running: false, models: [] },
      },
    });

    renderModal();

    expect(await screen.findByText(/Модель не выбрана/)).toBeInTheDocument();
    expect(screen.getByText("qwen2.5:3b")).toBeInTheDocument();
    expect(screen.getByText("Использовать")).toBeInTheDocument();
  });

  it("выбор модели вызывает selectLlmModel и обновляет статус на «выбрана»", async () => {
    api.listLlmModels
      .mockResolvedValueOnce({
        selected: null,
        previous_selection: null,
        providers: { ollama: { available: true, models: [{ name: "qwen2.5:3b" }] } },
      })
      .mockResolvedValueOnce({
        selected: { provider: "ollama", model: "qwen2.5:3b" },
        previous_selection: null,
        providers: { ollama: { available: true, models: [{ name: "qwen2.5:3b" }] } },
      });
    api.selectLlmModel.mockResolvedValue({ provider: "ollama", model: "qwen2.5:3b" });

    renderModal();

    await userEvent.click(await screen.findByText("Использовать"));

    expect(api.selectLlmModel).toHaveBeenCalledWith("ollama", "qwen2.5:3b");
    expect(await screen.findByText("выбрана")).toBeInTheDocument();
  });

  it("реальная проверка модели показывает точную причину сбоя, а не общий 'не работает'", async () => {
    // Регрессия: заказчик видел out-of-memory от Ollama посреди обработки
    // заказ-наряда — эта кнопка должна показать ТУ ЖЕ причину заранее,
    // до загрузки файлов, а не абстрактное "ошибка".
    api.listLlmModels.mockResolvedValue({
      selected: { provider: "ollama", model: "qwen2.5:14b" },
      previous_selection: null,
      providers: { ollama: { available: true, models: [{ name: "qwen2.5:14b" }] } },
    });
    api.testLlmConnection.mockResolvedValue({
      ok: false,
      error: "llm-service -> 502: ollama -> 500: llama-server reported out-of-memory during startup",
    });

    renderModal();

    await userEvent.click(await screen.findByText("Проверить, что модель реально отвечает"));

    expect(await screen.findByText(/out-of-memory/)).toBeInTheDocument();
  });

  it("успешная проверка показывает подтверждение и кнопка продолжения работает без блокировки", async () => {
    api.listLlmModels.mockResolvedValue({
      selected: { provider: "ollama", model: "qwen2.5:3b" },
      previous_selection: null,
      providers: { ollama: { available: true, models: [{ name: "qwen2.5:3b" }] } },
    });
    api.testLlmConnection.mockResolvedValue({ ok: true, message: "Модель отвечает, можно продолжать." });
    const onContinue = vi.fn();

    renderModal({ onContinue });

    await userEvent.click(await screen.findByText("Проверить, что модель реально отвечает"));
    expect(await screen.findByText("Модель отвечает, можно продолжать.")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Загрузить и сопоставить"));
    expect(onContinue).toHaveBeenCalled();
  });

  it("продолжить можно и без ИИ вообще — кнопка не блокируется отсутствием выбора", async () => {
    api.listLlmModels.mockResolvedValue({
      selected: null,
      previous_selection: null,
      providers: { ollama: { available: true, models: [] } },
    });
    const onContinue = vi.fn();

    renderModal({ onContinue });

    const continueButton = await screen.findByText("Всё равно загрузить и сопоставить");
    await userEvent.click(continueButton);
    expect(onContinue).toHaveBeenCalled();
  });
});
