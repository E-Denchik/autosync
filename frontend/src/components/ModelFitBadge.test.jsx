import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ModelFitBadge from "./ModelFitBadge.jsx";

describe("ModelFitBadge", () => {
  it("показывает «хорошо подойдёт» и badge-verified для comfortable", () => {
    render(<ModelFitBadge fit={{ status: "comfortable", note: null }} />);
    expect(screen.getByText("хорошо подойдёт")).toHaveClass("badge", "badge-verified");
  });

  it("показывает «впритык» и badge-guess для tight", () => {
    render(<ModelFitBadge fit={{ status: "tight", note: "Весит близко к свободной памяти" }} />);
    expect(screen.getByText("впритык")).toHaveClass("badge", "badge-guess");
  });

  it("показывает «скорее всего не поместится» и badge-no_match для too_big", () => {
    render(<ModelFitBadge fit={{ status: "too_big", note: "Больше, чем вся RAM" }} />);
    expect(screen.getByText("скорее всего не поместится")).toHaveClass("badge", "badge-no_match");
  });

  it("показывает «размер неизвестен» вместо бейджа для unknown/отсутствующего fit", () => {
    render(<ModelFitBadge fit={{ status: "unknown", note: null }} />);
    expect(screen.getByText("размер неизвестен")).toBeInTheDocument();

    render(<ModelFitBadge fit={undefined} />);
    expect(screen.getAllByText("размер неизвестен").length).toBeGreaterThan(0);
  });

  it("объединяет capabilityNote и fit.note в тултипе", () => {
    render(<ModelFitBadge fit={{ status: "tight", note: "впритык по памяти" }} capabilityNote="компактная модель" />);
    expect(screen.getByText("впритык")).toHaveAttribute("title", "компактная модель впритык по памяти");
  });
});
