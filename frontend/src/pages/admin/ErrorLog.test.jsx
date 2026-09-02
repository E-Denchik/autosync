import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider, useToast } from "../../context/ToastContext.jsx";
import { ErrorLogProvider } from "../../context/ErrorLogContext.jsx";
import ErrorLog from "./ErrorLog.jsx";

function ErrorTrigger({ message }) {
  const toast = useToast();
  return (
    <button onClick={() => toast.error(message)} data-testid="fire-error">
      fire
    </button>
  );
}

function renderPage(extra = null) {
  return render(
    <ErrorLogProvider>
      <ToastProvider>
        {extra}
        <ErrorLog />
      </ToastProvider>
    </ErrorLogProvider>
  );
}

beforeEach(() => {
  localStorage.clear();
});

describe("ErrorLog", () => {
  it("показывает пустое состояние, когда ошибок ещё не было", () => {
    renderPage();
    expect(screen.getByText("Ошибок пока не было")).toBeInTheDocument();
  });

  it("сохраняет полный текст ошибки, показанной через toast.error, даже после исчезновения тоста", async () => {
    const user = userEvent.setup();
    const longMessage =
      "Не удалось загрузить и сопоставить файлы: llm-service -> 502: ollama не ответил вовремя после 3 попыток";
    renderPage(<ErrorTrigger message={longMessage} />);

    await user.click(screen.getByTestId("fire-error"));

    // Сообщение появляется в списке журнала (не только во всплывающем тосте) —
    // используем getAllByText, т.к. один и тот же текст рендерится и в тосте,
    // и в постоянной записи журнала одновременно.
    await waitFor(() => {
      expect(screen.getAllByText(longMessage).length).toBeGreaterThan(0);
    });
    expect(screen.queryByText("Ошибок пока не было")).not.toBeInTheDocument();
  });

  it("очищает журнал по кнопке «Очистить журнал» после подтверждения", async () => {
    const user = userEvent.setup();
    renderPage(<ErrorTrigger message="ошибка для очистки" />);

    await user.click(screen.getByTestId("fire-error"));
    await waitFor(() => expect(screen.getAllByText("ошибка для очистки").length).toBeGreaterThan(0));

    await user.click(screen.getByRole("button", { name: /очистить журнал/i }));
    await user.click(screen.getByRole("button", { name: "Очистить" }));

    expect(screen.getByText("Ошибок пока не было")).toBeInTheDocument();
  });

  it("журнал переживает перемонтирование (персистентность через localStorage)", async () => {
    const user = userEvent.setup();
    const { unmount } = renderPage(<ErrorTrigger message="персистентная ошибка" />);
    await user.click(screen.getByTestId("fire-error"));
    await waitFor(() => expect(screen.getAllByText("персистентная ошибка").length).toBeGreaterThan(0));
    unmount();

    renderPage();
    expect(screen.getByText("персистентная ошибка")).toBeInTheDocument();
  });
});
