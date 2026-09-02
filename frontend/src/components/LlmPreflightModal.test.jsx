import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../context/ToastContext.jsx";
import { ErrorLogProvider } from "../context/ErrorLogContext.jsx";
import { api } from "../api/client.js";
import LlmPreflightModal from "./LlmPreflightModal.jsx";

vi.mock("../api/client.js", () => ({
  api: {
    listLlmModels: vi.fn(),
    selectLlmModel: vi.fn(),
    testLlmConnection: vi.fn(),
    performance: vi.fn(),
  },
}));

function renderModal(props = {}) {
  return render(
    <ErrorLogProvider>
      <ToastProvider>
        <LlmPreflightModal onClose={vi.fn()} onContinue={vi.fn()} {...props} />
      </ToastProvider>
    </ErrorLogProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // По умолчанию — без предупреждений о памяти, чтобы существующие тесты не
  // зависели от него; тест ниже переопределяет это резолвом с warnings.
  api.performance.mockResolvedValue({
    settings: { mode: "auto", workers: 2, timeout_seconds: 180 },
    recommendation: { workers: 2, timeout_seconds: 180, reason: "", warnings: [] },
  });
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

  it("показывает модели Ollama и LM Studio, даже если vsegpt.ru не подключён", async () => {
    api.listLlmModels.mockResolvedValue({
      selected: null,
      previous_selection: null,
      providers: {
        ollama: { available: true, models: [{ name: "qwen2.5:7b" }] },
        lmstudio: { available: true, server_running: true, models: [{ name: "local-model" }] },
        vsegpt: { available: false, configured: false, models: [] },
      },
      vsegpt_configured: false,
    });

    renderModal();

    expect(await screen.findByText("qwen2.5:7b")).toBeInTheDocument();
    expect(screen.getByText("local-model")).toBeInTheDocument();
    const useButtons = screen.getAllByText("Использовать");
    expect(useButtons).toHaveLength(2);
    useButtons.forEach((button) => expect(button).not.toBeDisabled());
  });

  it("показывает предупреждение, если модель не помещается в RAM этого компьютера", async () => {
    // Регрессия: на 8 ГБ RAM с моделью 14B обработка уходила в свопирование
    // и еле ползла (179 файлов, 6 обработано за 10 минут), но пользователь
    // узнавал об этом только посреди загрузки, а не заранее.
    api.listLlmModels.mockResolvedValue({
      selected: { provider: "ollama", model: "qwen2.5:14b" },
      previous_selection: null,
      providers: { ollama: { available: true, models: [{ name: "qwen2.5:14b" }] } },
    });
    api.performance.mockResolvedValue({
      settings: { mode: "auto", workers: 1, timeout_seconds: 600 },
      recommendation: {
        workers: 1,
        timeout_seconds: 600,
        reason: "",
        warnings: ["Выбранная модель весит 9.0 ГБ — больше, чем есть RAM на этом компьютере (8.0 ГБ)"],
      },
    });

    renderModal();

    expect(await screen.findByText(/больше, чем есть RAM на этом компьютере/)).toBeInTheDocument();
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
