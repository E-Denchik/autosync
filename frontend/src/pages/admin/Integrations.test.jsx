import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../../context/ToastContext.jsx";
import { ErrorLogProvider } from "../../context/ErrorLogContext.jsx";
import { api } from "../../api/client.js";
import Integrations from "./Integrations.jsx";

vi.mock("../../api/client.js", () => ({
  api: {
    listIntegrations: vi.fn(),
    testIntegration: vi.fn(),
    saveIntegrationKeys: vi.fn(),
  },
}));

function renderPage() {
  return render(
    <ErrorLogProvider>
      <ToastProvider>
        <Integrations />
      </ToastProvider>
    </ErrorLogProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Integrations — ключ vsegpt.ru", () => {
  it("показывает карточку vsegpt.ru в общем списке интеграций, наравне с остальными", async () => {
    // Раньше ключ vsegpt.ru можно было ввести только со страницы «LLM-модель»
    // — здесь, среди Ozon/Rossco/АвтоЕвро/Москворечье, его не было вовсе.
    api.listIntegrations.mockResolvedValue([
      {
        id: "vsegpt",
        name: "vsegpt.ru",
        description: "Облачные LLM-модели",
        configured: false,
        api_base_override: null,
      },
    ]);

    renderPage();

    expect(await screen.findByText("vsegpt.ru")).toBeInTheDocument();
    expect(screen.getByText("не настроено")).toBeInTheDocument();
  });

  it("ввод и сохранение ключа vsegpt.ru вызывает тот же общий saveIntegrationKeys", async () => {
    api.listIntegrations.mockResolvedValue([
      { id: "vsegpt", name: "vsegpt.ru", description: "Облачные LLM-модели", configured: false, api_base_override: null },
    ]);
    api.saveIntegrationKeys.mockResolvedValue({ ok: true, updated: ["VSEGPT_API_KEY"] });

    renderPage();

    await userEvent.click(await screen.findByText("Задать ключи"));
    await userEvent.type(screen.getByLabelText("API-ключ vsegpt.ru"), "sk-or-secret");
    await userEvent.click(screen.getByText("Сохранить"));

    expect(api.saveIntegrationKeys).toHaveBeenCalledWith({ VSEGPT_API_KEY: "sk-or-secret" });
  });

  it("«Проверить подключение» показывает настоящую причину сбоя (не общий 'ошибка')", async () => {
    api.listIntegrations.mockResolvedValue([
      { id: "vsegpt", name: "vsegpt.ru", description: "Облачные LLM-модели", configured: true, api_base_override: null },
    ]);
    api.testIntegration.mockResolvedValue({ ok: false, message: "vsegpt.ru не принял API-ключ" });

    renderPage();

    await userEvent.click(await screen.findByText("Проверить подключение"));

    expect((await screen.findAllByText("vsegpt.ru не принял API-ключ")).length).toBeGreaterThan(0);
  });
});
