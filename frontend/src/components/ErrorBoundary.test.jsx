import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import ErrorBoundary from "./ErrorBoundary.jsx";

function Boom() {
  throw new Error("тестовая ошибка рендера");
}

describe("ErrorBoundary", () => {
  it("рендерит детей как обычно, если ошибок нет", () => {
    render(
      <ErrorBoundary>
        <div>всё хорошо</div>
      </ErrorBoundary>
    );
    expect(screen.getByText("всё хорошо")).toBeInTheDocument();
  });

  it("ловит ошибку рендера дочернего компонента и показывает запасной экран вместо белого пустого", () => {
    // React логирует ошибку ещё и в консоль при перехвате — подавляем в тесте,
    // чтобы не засорять вывод, само поведение это не отменяет.
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>
    );

    expect(screen.getByText("Что-то пошло не так")).toBeInTheDocument();
    expect(screen.getByText("Обновить страницу")).toBeInTheDocument();
    expect(screen.queryByText("всё хорошо")).not.toBeInTheDocument();

    consoleSpy.mockRestore();
  });
});
