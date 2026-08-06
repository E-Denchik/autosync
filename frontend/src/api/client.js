const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:5000/api";

let authToken = null;
let onUnauthorized = null;

export function setAuthToken(token) {
  authToken = token;
}

export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

async function request(path, options = {}) {
  const headers = options.body instanceof FormData ? {} : { "Content-Type": "application/json" };
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

  const resp = await fetch(`${API_BASE_URL}${path}`, {
    headers,
    ...options,
  });

  if (resp.status === 401 && onUnauthorized) {
    onUnauthorized();
  }

  if (!resp.ok) {
    const text = await resp.text();
    let message = text;
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed?.error === "string") message = parsed.error;
      else if (typeof parsed?.message === "string") message = parsed.message;
    } catch {
      // не JSON — показываем как есть
    }
    throw new Error(message);
  }
  const contentType = resp.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return resp.json();
  }
  return resp.blob();
}

export const api = {
  // Авторизация
  setupRequired: () => request("/auth/setup-required"),
  setup: (email, password) =>
    request("/auth/setup", { method: "POST", body: JSON.stringify({ email, password }) }),
  login: (email, password) =>
    request("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  me: () => request("/auth/me"),
  listUsers: () => request("/auth/users"),
  createUser: (data) => request("/auth/users", { method: "POST", body: JSON.stringify(data) }),
  deleteUser: (id) => request(`/auth/users/${id}`, { method: "DELETE" }),
  changeOwnPassword: (currentPassword, newPassword) =>
    request("/auth/me/password", {
      method: "PATCH",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),
  resetUserPassword: (id, newPassword) =>
    request(`/auth/users/${id}/password`, {
      method: "PATCH",
      body: JSON.stringify({ new_password: newPassword }),
    }),

  // Настройки LLM
  listLlmModels: () => request("/llm/models"),
  selectLlmModel: (provider, model) =>
    request("/llm/select", { method: "POST", body: JSON.stringify({ provider, model }) }),

  // Дашборд
  dashboardSummary: () => request("/dashboard/summary"),

  // История / журнал действий
  listHistoryEntityTypes: () => request("/history/entity-types"),
  listHistory: (params = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") query.set(key, value);
    });
    const qs = query.toString();
    return request(`/history${qs ? `?${qs}` : ""}`);
  },

  // Интеграции с внешними API
  listIntegrations: () => request("/integrations/status"),
  testIntegration: (id) => request(`/integrations/test/${id}`, { method: "POST" }),
  saveIntegrationKeys: (values) =>
    request("/integrations/keys", { method: "POST", body: JSON.stringify(values) }),

  // Ozon: цены
  listPriceSnapshots: (status = "pending") => request(`/ozon/pricing?status=${status}`),
  approvePriceSnapshot: (id) => request(`/ozon/pricing/${id}/approve`, { method: "POST" }),
  rejectPriceSnapshot: (id) => request(`/ozon/pricing/${id}/reject`, { method: "POST" }),
  analyzePrice: (productId) => request(`/ozon/pricing/analyze/${productId}`, { method: "POST" }),

  // Ozon: товары и карточки
  listProductCategories: () => request("/ozon/cards/categories"),
  listProducts: (params = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") query.set(key, value);
    });
    const qs = query.toString();
    return request(`/ozon/cards${qs ? `?${qs}` : ""}`);
  },
  syncOzonCatalog: () => request("/ozon/cards/sync", { method: "POST" }),
  updateCostPrice: (productId, costPrice) =>
    request(`/ozon/cards/${productId}`, { method: "PATCH", body: JSON.stringify({ cost_price: costPrice }) }),
  generateCard: (productId) => request(`/ozon/cards/${productId}/generate`, { method: "POST" }),

  // Заказ-наряды: загрузка
  uploadDocuments: (contractFile, repairOrderFile) => {
    const formData = new FormData();
    formData.append("contract", contractFile);
    formData.append("repair_order", repairOrderFile);
    return request("/repair-orders/upload", { method: "POST", body: formData });
  },
  listRepairOrders: () => request("/repair-orders/upload"),
  getUploadStatus: (repairOrderId) => request(`/repair-orders/upload/${repairOrderId}/status`),

  // Заказ-наряды: сопоставление
  listMatches: (repairOrderId) => request(`/repair-orders/matching/${repairOrderId}`),
  listCandidates: (repairOrderId) => request(`/repair-orders/matching/${repairOrderId}/candidates`),
  editMatch: (matchId, data) =>
    request(`/repair-orders/matching/${matchId}`, { method: "PATCH", body: JSON.stringify(data) }),
  approveMatch: (matchId) => request(`/repair-orders/matching/${matchId}/approve`, { method: "POST" }),
  rejectMatch: (matchId) => request(`/repair-orders/matching/${matchId}/reject`, { method: "POST" }),
  bulkReview: (ids, action) =>
    request(`/repair-orders/matching/bulk`, { method: "POST", body: JSON.stringify({ ids, action }) }),
  exportMatchesCsv: (repairOrderId) => request(`/repair-orders/matching/${repairOrderId}/export`),
  generateDocument: (repairOrderId) =>
    request(`/repair-orders/matching/${repairOrderId}/generate-document`, { method: "POST" }),
};
