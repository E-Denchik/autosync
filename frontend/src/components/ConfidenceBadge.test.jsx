import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ConfidenceBadge from "./ConfidenceBadge.jsx";

describe("ConfidenceBadge", () => {
  it("показывает русскую подпись и css-класс уровня для точного совпадения", () => {
    render(<ConfidenceBadge level="exact" />);

    const badge = screen.getByText("точное совпадение");
    expect(badge).toHaveClass("badge", "badge-exact");
  });

  it("для кросс-номера не показывает проценты, даже если score передан", () => {
    render(<ConfidenceBadge level="cross_ref" score={0.87} />);

    expect(screen.getByText("кросс-номер")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("для догадки LLM показывает процент уверенности, округлённый до целого", () => {
    render(<ConfidenceBadge level="llm_guess" score={0.873} />);

    expect(screen.getByText("догадка LLM · 87%")).toBeInTheDocument();
  });

  it("для догадки LLM без числового score не добавляет процент", () => {
    render(<ConfidenceBadge level="llm_guess" />);

    expect(screen.getByText("догадка LLM")).toBeInTheDocument();
  });

  it("показывает предупреждающую иконку с подсказкой, когда уверенность ниже порога", () => {
    render(<ConfidenceBadge level="llm_guess" score={0.4} belowThreshold />);

    const warning = screen.getByTitle("Уверенность ниже порога — проверьте эту позицию в первую очередь");
    expect(warning).toHaveTextContent("⚠");
  });

  it("не показывает предупреждающую иконку, когда belowThreshold не передан", () => {
    render(<ConfidenceBadge level="exact" />);

    expect(screen.queryByTitle(/Уверенность ниже порога/)).not.toBeInTheDocument();
  });

  it("для неизвестного уровня показывает сам уровень как подпись", () => {
    render(<ConfidenceBadge level="mystery" />);

    expect(screen.getByText("mystery")).toBeInTheDocument();
  });
});
