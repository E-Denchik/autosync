import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ToastProvider } from "../../context/ToastContext.jsx";
import { ErrorLogProvider } from "../../context/ErrorLogContext.jsx";
import { api } from "../../api/client.js";
import LlmSettings from "./LlmSettings.jsx";

vi.mock("../../api/client.js", () => ({
  api: {
    listLlmModels: vi.fn(),
    selectLlmModel: vi.fn(),
    saveIntegrationKeys: vi.fn(),
  },
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <ErrorLogProvider>
        <ToastProvider>
          <LlmSettings />
        </ToastProvider>
      </ErrorLogProvider>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("LlmSettings — подсказки о моделях", () => {
  it("показывает бейдж совместимости и тег возможностей для локальной модели", async () => {
    api.listLlmModels.mockResolvedValue({
      providers: {
        ollama: {
          available: true,
          models: [
            {
              name: "llama3.2:3b",
              size: 2019393189,
              capability: { tier: "small", label: "сбалансированная", note: "разумный компромисс" },
              fit: { status: "comfortable", note: null },
            },
          ],
        },
        lmstudio: { available: false, server_running: false, models: [] },
        vsegpt: { available: false, configured: false, models: [] },
      },
      selected: null,
      previous_selection: null,
      vsegpt_configured: false,
      cpu_only_suspected: false,
      system: { cpu_count: 8, memory_total_bytes: 8 * 1024 ** 3, memory_available_bytes: 4 * 1024 ** 3 },
    });

    renderPage();

    expect(await screen.findByText("хорошо подойдёт")).toBeInTheDocument();
    expect(screen.getByText("(сбалансированная)")).toBeInTheDocument();
  });

  it("показывает предупреждение про CPU-only только когда cpu_only_suspected=true", async () => {
    api.listLlmModels.mockResolvedValue({
      providers: {
        ollama: { available: true, models: [{ name: "m", capability: {}, fit: { status: "unknown" } }] },
        lmstudio: { available: false, server_running: false, models: [] },
        vsegpt: { available: false, configured: false, models: [] },
      },
      selected: null,
      previous_selection: null,
      vsegpt_configured: false,
      cpu_only_suspected: true,
      system: { cpu_count: 4, memory_total_bytes: 4 * 1024 ** 3, memory_available_bytes: 1 * 1024 ** 3 },
    });

    renderPage();

    expect(await screen.findByText(/вёл себя как CPU-only/)).toBeInTheDocument();
  });

  it("не показывает предупреждение про CPU-only, когда cpu_only_suspected=false", async () => {
    api.listLlmModels.mockResolvedValue({
      providers: {
        ollama: { available: true, models: [{ name: "m", capability: {}, fit: { status: "unknown" } }] },
        lmstudio: { available: false, server_running: false, models: [] },
        vsegpt: { available: false, configured: false, models: [] },
      },
      selected: null,
      previous_selection: null,
      vsegpt_configured: false,
      cpu_only_suspected: false,
      system: { cpu_count: 4, memory_total_bytes: 4 * 1024 ** 3, memory_available_bytes: 1 * 1024 ** 3 },
    });

    renderPage();

    await screen.findByText("m");
    expect(screen.queryByText(/вёл себя как CPU-only/)).not.toBeInTheDocument();
  });

  it("для vsegpt показывает один поясняющий абзац, а не бейдж на каждую модель", async () => {
    const cloudNote = "Качество и скорость не зависят от железа этого компьютера";
    api.listLlmModels.mockResolvedValue({
      providers: {
        ollama: { available: false, models: [] },
        lmstudio: { available: false, server_running: false, models: [] },
        vsegpt: {
          available: true,
          configured: true,
          models: [
            { name: "openai/gpt-4o-mini", capability: { tier: "cloud", label: "облачная", note: cloudNote } },
            { name: "openai/o3", capability: { tier: "cloud", label: "облачная", note: cloudNote } },
          ],
        },
      },
      selected: null,
      previous_selection: null,
      vsegpt_configured: true,
      cpu_only_suspected: false,
      system: { cpu_count: 4, memory_total_bytes: 4 * 1024 ** 3, memory_available_bytes: 1 * 1024 ** 3 },
    });

    renderPage();

    expect(await screen.findByText(cloudNote)).toBeInTheDocument();
    // Не показываем "Совместимость" колонку/бейджи для облачных моделей.
    expect(screen.queryByText("Совместимость с этим компьютером")).not.toBeInTheDocument();
    expect(screen.queryByText("хорошо подойдёт")).not.toBeInTheDocument();
  });
});
