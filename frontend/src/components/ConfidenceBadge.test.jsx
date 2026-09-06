import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ConfidenceBadge from "./ConfidenceBadge.jsx";

describe("ConfidenceBadge", () => {
  it("показывает «проверено» и badge-verified для точного совпадения", () => {
    render(<ConfidenceBadge isVerified matchCategory="exact" level="exact" />);

    const badge = screen.getByText("проверено");
    expect(badge).toHaveClass("badge", "badge-verified");
  });

  it("показывает «проверено» для догадки LLM выше порога уверенности (is_verified=true)", () => {
    render(<ConfidenceBadge isVerified matchCategory="llm_guess" level="llm_guess" score={0.87} />);

    expect(screen.getByText("проверено")).toHaveClass("badge-verified");
  });

  it("показывает «догадка» и badge-guess, когда is_verified=false и совпадение всё же есть", () => {
    render(<ConfidenceBadge isVerified={false} matchCategory="llm_guess" level="llm_guess" score={0.4} />);

    expect(screen.getByText("догадка")).toHaveClass("badge", "badge-guess");
  });

  it("показывает «не найдено» вместо «догадка», когда категория no_match", () => {
    render(<ConfidenceBadge isVerified={false} matchCategory="no_match" level="llm_guess" score={0} />);

    expect(screen.getByText("не найдено")).toHaveClass("badge", "badge-no_match");
  });

  it("показывает «не найдено» и для категории llm_error (ИИ была недоступна)", () => {
    render(<ConfidenceBadge isVerified={false} matchCategory="llm_error" level="llm_guess" />);

    expect(screen.getByText("не найдено")).toHaveClass("badge-no_match");
  });

  it("в тултипе показывает подробный уровень и процент для догадки LLM", () => {
    render(<ConfidenceBadge isVerified={false} matchCategory="llm_guess" level="llm_guess" score={0.873} />);

    expect(screen.getByText("догадка")).toHaveAttribute("title", "догадка LLM · 87%");
  });

  it("в тултипе не показывает процент для точного совпадения", () => {
    render(<ConfidenceBadge isVerified matchCategory="exact" level="exact" score={1} />);

    expect(screen.getByText("проверено")).toHaveAttribute("title", "точное совпадение");
  });
});
