import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ToastProvider } from "../../context/ToastContext.jsx";
import { ErrorLogProvider } from "../../context/ErrorLogContext.jsx";
import { api } from "../../api/client.js";
import LlmModelGuide from "./LlmModelGuide.jsx";

vi.mock("../../api/client.js", () => ({
  api: {
    performance: vi.fn(),
  },
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <ErrorLogProvider>
        <ToastProvider>
          <LlmModelGuide />
        </ToastProvider>
      </ErrorLogProvider>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("LlmModelGuide", () => {
  it("показывает статическую таблицу уровней и персональные данные компьютера", async () => {
    api.performance.mockResolvedValue({
      system: { cpu_count: 8, memory_total_bytes: 16 * 1024 ** 3, memory_available_bytes: 6 * 1024 ** 3 },
      cpu_only_suspected: false,
    });

    renderPage();

    expect(screen.getByText("Компактная")).toBeInTheDocument();
    expect(screen.getByText("Облачная (vsegpt.ru)")).toBeInTheDocument();
    expect(await screen.findByText("16.0 ГБ")).toBeInTheDocument();
    expect(await screen.findByText("6.0 ГБ")).toBeInTheDocument();
  });

  it("показывает предупреждение о CPU-only, когда оно активно", async () => {
    api.performance.mockResolvedValue({
      system: { cpu_count: 4, memory_total_bytes: 8 * 1024 ** 3, memory_available_bytes: 1 * 1024 ** 3 },
      cpu_only_suspected: true,
    });

    renderPage();

    expect(await screen.findByText(/вёл себя как CPU-only/)).toBeInTheDocument();
  });
});
