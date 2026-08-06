const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:5000/api";

async function request(path, options = {}) {
  const resp = await fetch(`${API_BASE_URL}${path}`, {
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${text}`);
  }
  const contentType = resp.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return resp.json();
  }
  return resp.blob();
}

export const api = {
  // Дашборд
  dashboardSummary: () => request("/dashboard/summary"),

  // Ozon: цены
  listPriceSnapshots: (status = "pending") => request(`/ozon/pricing?status=${status}`),
  approvePriceSnapshot: (id) => request(`/ozon/pricing/${id}/approve`, { method: "POST" }),
  rejectPriceSnapshot: (id) => request(`/ozon/pricing/${id}/reject`, { method: "POST" }),
  analyzePrice: (productId) => request(`/ozon/pricing/analyze/${productId}`, { method: "POST" }),

  // Ozon: товары и карточки
  listProducts: () => request("/ozon/cards"),
  createProduct: (data) => request("/ozon/cards", { method: "POST", body: JSON.stringify(data) }),
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
  approveMatch: (matchId) => request(`/repair-orders/matching/${matchId}/approve`, { method: "POST" }),
  rejectMatch: (matchId) => request(`/repair-orders/matching/${matchId}/reject`, { method: "POST" }),
  generateDocument: (repairOrderId) =>
    request(`/repair-orders/matching/${repairOrderId}/generate-document`, { method: "POST" }),
};
