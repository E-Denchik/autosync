import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ToastProvider } from "../../context/ToastContext.jsx";
import { ErrorLogProvider } from "../../context/ErrorLogContext.jsx";
import { api } from "../../api/client.js";
import VsegptStats from "./VsegptStats.jsx";

vi.mock("../../api/client.js", () => ({
  api: {
    vsegptStatus: vi.fn(),
  },
}));

function renderPage() {
  return render(
    <ErrorLogProvider>
      <ToastProvider>
        <VsegptStats />
      </ToastProvider>
    </ErrorLogProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("VsegptStats", () => {
  it("показывает реальные поля v1/balance — баланс в кредитах, статус-светофор и подписку", async () => {
    // Регрессия: раньше страница читала несуществующие поля ответа API
    // (balance/currency/spent/requests_made/requests_remaining вместо
    // настоящих credits/user_status/user_status_text/subscription_*) — баланс
    // всегда показывал "—", даже с рабочим ключом (см. llm-service/server.py).
    api.vsegptStatus.mockResolvedValue({
      status: {
        configured: true,
        available: true,
        balance: 10.75,
        user_status: 1,
        user_status_text: "Less than 500 credits on account.",
        subscription_status: "ok",
        subscription_end: "2024-05-02 00:08:02",
        local_requests: 12,
        local_successes: 10,
        local_errors: 2,
      },
    });

    renderPage();

    expect(await screen.findByText("10.75 кредитов")).toBeInTheDocument();
    expect(screen.getByText("предупреждение")).toBeInTheDocument();
    expect(screen.getByText("Less than 500 credits on account.")).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("здоровый аккаунт (user_status=0) показывает зелёный статус", async () => {
    api.vsegptStatus.mockResolvedValue({
      status: {
        configured: true,
        available: true,
        balance: 500,
        user_status: 0,
        user_status_text: null,
        subscription_status: null,
        subscription_end: null,
        local_requests: 0,
        local_successes: 0,
        local_errors: 0,
      },
    });

    renderPage();

    const pill = await screen.findByText("в порядке");
    expect(pill).toHaveClass("status-approved");
  });

  it("без настроенного ключа объясняет, где его добавить", async () => {
    api.vsegptStatus.mockResolvedValue({ status: { configured: false, available: false } });

    renderPage();

    expect(await screen.findByText(/API-ключ vsegpt.ru не настроен/)).toBeInTheDocument();
  });

  it("при недоступности API показывает причину, а не молча пустую страницу", async () => {
    api.vsegptStatus.mockResolvedValue({
      status: { configured: true, available: false, error: "vsegpt.ru не принял API-ключ" },
    });

    renderPage();

    expect(await screen.findByText("vsegpt.ru не принял API-ключ")).toBeInTheDocument();
  });
});
