import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client.js";

function jsonResponse(data, { status = 200, headers = {} } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name) => headers[name] ?? null },
    text: async () => JSON.stringify(data),
    json: async () => data,
  };
}

function errorResponse(body, { status = 400, contentType = "application/json" } = {}) {
  return {
    ok: false,
    status,
    headers: { get: (name) => (name === "content-type" ? contentType : null) },
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  };
}

describe("api client (request/withPaging через простые методы api.*)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("возвращает JSON как есть, когда нет заголовка X-Total-Count", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ total_orders: 5 }, { headers: { "content-type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await api.dashboardSummary();

    expect(result).toEqual({ total_orders: 5 });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:5000/api/dashboard/summary",
      expect.objectContaining({ headers: { "Content-Type": "application/json" } }),
    );
  });

  it("извлекает сообщение об ошибке из JSON-тела {error: ...} и бросает Error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(errorResponse({ error: "модель не найдена" })),
    );

    await expect(api.selectLlmModel("openai", "gpt-x")).rejects.toThrow("модель не найдена");
  });

  it("извлекает сообщение об ошибке из JSON-тела {message: ...}, если поля error нет", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(errorResponse({ message: "нет доступа" })),
    );

    await expect(api.dashboardSummary()).rejects.toThrow("нет доступа");
  });

  it("если тело ошибки не JSON — показывает его как есть", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(errorResponse("Internal Server Error", { contentType: "text/plain" })),
    );

    await expect(api.dashboardSummary()).rejects.toThrow("Internal Server Error");
  });

  it("собирает query-строку из параметров и возвращает {items, total} по заголовку X-Total-Count", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse([{ id: 1 }, { id: 2 }], {
        headers: { "content-type": "application/json", "X-Total-Count": "42" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await api.listHistory({ page: 2, page_size: 20, entity_type: "" });

    expect(result).toEqual({ items: [{ id: 1 }, { id: 2 }], total: 42 });
    const calledUrl = fetchMock.mock.calls[0][0];
    expect(calledUrl).toBe("http://localhost:5000/api/history?page=2&page_size=20");
    expect(calledUrl).not.toContain("entity_type");
  });

  it("не добавляет query-строку, если параметров пагинации нет", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse([], { headers: { "content-type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.listHistory();

    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:5000/api/history");
  });

  it("для не-JSON ответа возвращает blob и прикрепляет unresolvedTokens из X-Unresolved-Tokens", async () => {
    const fakeBlob = { size: 3 };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: {
          get: (name) => {
            if (name === "content-type") return "application/octet-stream";
            if (name === "X-Unresolved-Tokens") return "Артикул 123, Артикул 456";
            return null;
          },
        },
        blob: async () => fakeBlob,
      }),
    );

    const result = await api.exportMatchesCsv(7);

    expect(result).toBe(fakeBlob);
    expect(result.unresolvedTokens).toEqual(["Артикул 123", "Артикул 456"]);
  });

  it("не добавляет unresolvedTokens, если заголовка X-Unresolved-Tokens нет", async () => {
    const fakeBlob = {};
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: (name) => (name === "content-type" ? "text/csv" : null) },
        blob: async () => fakeBlob,
      }),
    );

    const result = await api.exportMatchesCsv(7);

    expect(result.unresolvedTokens).toBeUndefined();
  });

  it("для FormData-тела не выставляет Content-Type (браузер сам подставит boundary)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ ok: true }, { headers: { "content-type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.uploadDocuments([], []);

    const options = fetchMock.mock.calls[0][1];
    expect(options.headers).toEqual({});
    expect(options.body).toBeInstanceOf(FormData);
  });
});
