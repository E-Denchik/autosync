const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:5000/api";

async function request(path, options = {}) {
  const headers = options.body instanceof FormData ? {} : { "Content-Type": "application/json" };

  const resp = await fetch(`${API_BASE_URL}${path}`, {
    headers,
    ...options,
  });

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
    const data = await resp.json();
    const totalHeader = resp.headers.get("X-Total-Count");
    if (totalHeader !== null) {
      return { items: data, total: parseInt(totalHeader, 10) };
    }
    return data;
  }
  const blob = await resp.blob();
  const unresolvedHeader = resp.headers.get("X-Unresolved-Tokens");
  if (unresolvedHeader) blob.unresolvedTokens = unresolvedHeader.split(", ");
  return blob;
}

function withPaging(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, value);
  });
  const qs = query.toString();
  return qs ? `?${qs}` : "";
}

export const api = {
  // Настройки LLM
  listLlmModels: () => request("/llm/models"),
  selectLlmModel: (provider, model) =>
    request("/llm/select", { method: "POST", body: JSON.stringify({ provider, model }) }),

  // Дашборд
  dashboardSummary: () => request("/dashboard/summary"),

  // История / журнал действий
  listHistoryEntityTypes: () => request("/history/entity-types"),
  listHistory: (params = {}) => request(`/history${withPaging(params)}`),

  // Интеграции с внешними API
  listIntegrations: () => request("/integrations/status"),
  testIntegration: (id) => request(`/integrations/test/${id}`, { method: "POST" }),
  saveIntegrationKeys: (values) =>
    request("/integrations/keys", { method: "POST", body: JSON.stringify(values) }),

  // Ozon: цены
  listPriceSnapshots: (status = "pending", params = {}) =>
    request(`/ozon/pricing${withPaging({ status, ...params })}`),
  approvePriceSnapshot: (id) => request(`/ozon/pricing/${id}/approve`, { method: "POST" }),
  rejectPriceSnapshot: (id) => request(`/ozon/pricing/${id}/reject`, { method: "POST" }),
  analyzePrice: (productId) => request(`/ozon/pricing/analyze/${productId}`, { method: "POST" }),

  // Ozon: товары и карточки
  listProductCategories: () => request("/ozon/cards/categories"),
  listProducts: (params = {}) => request(`/ozon/cards${withPaging(params)}`),
  syncOzonCatalog: () => request("/ozon/cards/sync", { method: "POST" }),
  updateCostPrice: (productId, costPrice) =>
    request(`/ozon/cards/${productId}`, { method: "PATCH", body: JSON.stringify({ cost_price: costPrice }) }),
  generateCard: (productId) => request(`/ozon/cards/${productId}/generate`, { method: "POST" }),

  // Заказ-наряды: загрузка
  uploadDocuments: (contractFiles, repairOrderFiles, extra = {}) => {
    const formData = new FormData();
    contractFiles.forEach((f) => formData.append("contract", f));
    repairOrderFiles.forEach((f) => formData.append("repair_order", f));
    Object.entries(extra).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") formData.append(key, value);
    });
    return request("/repair-orders/upload", { method: "POST", body: formData });
  },
  listRepairOrders: (params = {}) => request(`/repair-orders/upload${withPaging(params)}`),
  getUploadStatus: (repairOrderId) => request(`/repair-orders/upload/${repairOrderId}/status`),
  updateRepairOrder: (repairOrderId, data) =>
    request(`/repair-orders/upload/${repairOrderId}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteRepairOrder: (repairOrderId) => request(`/repair-orders/upload/${repairOrderId}`, { method: "DELETE" }),

  listContracts: () => request("/contracts"),
  getContract: (id) => request(`/contracts/${id}`),
  getContractStatus: (id) => request(`/contracts/${id}/status`),
  createContract: (files, extra = {}) => {
    const formData = new FormData();
    (Array.isArray(files) ? files : [files]).forEach((f) => formData.append("file", f));
    Object.entries(extra).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") formData.append(key, value);
    });
    return request("/contracts", { method: "POST", body: formData });
  },
  importMoreIntoContract: (id, files, extra = {}) => {
    const formData = new FormData();
    (Array.isArray(files) ? files : [files]).forEach((f) => formData.append("file", f));
    Object.entries(extra).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") formData.append(key, value);
    });
    return request(`/contracts/${id}/import`, { method: "POST", body: formData });
  },
  listContractParts: (id, params = {}) => request(`/contracts/${id}/parts${withPaging(params)}`),
  listContractLaborNorms: (id, params = {}) => request(`/contracts/${id}/labor-norms${withPaging(params)}`),
  deleteContract: (id) => request(`/contracts/${id}`, { method: "DELETE" }),
  mergeContract: (sourceId, targetId) =>
    request(`/contracts/${sourceId}/merge-into/${targetId}`, { method: "POST" }),
  archiveContract: (id) => request(`/contracts/${id}/archive`, { method: "POST" }),
  unarchiveContract: (id) => request(`/contracts/${id}/unarchive`, { method: "POST" }),
  listContractHourlyRates: (id) => request(`/contracts/${id}/hourly-rates`),
  createContractHourlyRate: (id, data) =>
    request(`/contracts/${id}/hourly-rates`, { method: "POST", body: JSON.stringify(data) }),
  deleteContractHourlyRate: (id, rateId) =>
    request(`/contracts/${id}/hourly-rates/${rateId}`, { method: "DELETE" }),
  importContractHourlyRates: (id, file) => {
    const formData = new FormData();
    formData.append("file", file);
    return request(`/contracts/${id}/hourly-rates/import`, { method: "POST", body: formData });
  },

  // Заказ-наряды: сопоставление
  listMatches: (repairOrderId) => request(`/repair-orders/matching/${repairOrderId}`),
  listCandidates: (repairOrderId, q = "") =>
    request(`/repair-orders/matching/${repairOrderId}/candidates${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  editMatch: (matchId, data) =>
    request(`/repair-orders/matching/${matchId}`, { method: "PATCH", body: JSON.stringify(data) }),
  approveMatch: (matchId) => request(`/repair-orders/matching/${matchId}/approve`, { method: "POST" }),
  rejectMatch: (matchId) => request(`/repair-orders/matching/${matchId}/reject`, { method: "POST" }),
  bulkReview: (ids, action) =>
    request(`/repair-orders/matching/bulk`, { method: "POST", body: JSON.stringify({ ids, action }) }),
  exportMatchesCsv: (repairOrderId) => request(`/repair-orders/matching/${repairOrderId}/export`),
  generateDocument: (repairOrderId, templateId) =>
    request(
      `/repair-orders/matching/${repairOrderId}/generate-document${templateId ? `?template_id=${templateId}` : ""}`,
      { method: "POST" }
    ),
  addPartFromSupplier: (repairOrderId, data) =>
    request(`/repair-orders/matching/${repairOrderId}/parts`, { method: "POST", body: JSON.stringify(data) }),

  // Поиск позиций у поставщиков запчастей (Rossco/АвтоЕвро/Москворечье)
  searchSuppliers: (article, brand) =>
    request(`/parts-suppliers/search${withPaging({ article, brand })}`),

  // Заказ-наряды: работы (нормо-часы)
  listLaborLines: (repairOrderId) => request(`/repair-orders/labor/${repairOrderId}`),
  editLaborLine: (laborLineId, data) =>
    request(`/repair-orders/labor/${laborLineId}`, { method: "PATCH", body: JSON.stringify(data) }),
  approveLaborLine: (laborLineId) => request(`/repair-orders/labor/${laborLineId}/approve`, { method: "POST" }),
  rejectLaborLine: (laborLineId) => request(`/repair-orders/labor/${laborLineId}/reject`, { method: "POST" }),
  bulkReviewLabor: (ids, action) =>
    request(`/repair-orders/labor/bulk`, { method: "POST", body: JSON.stringify({ ids, action }) }),

  // Контрагенты
  listContragents: () => request("/contragents"),
  createContragent: (data) => request("/contragents", { method: "POST", body: JSON.stringify(data) }),
  updateContragent: (id, data) => request(`/contragents/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteContragent: (id) => request(`/contragents/${id}`, { method: "DELETE" }),
  listContragentHourlyRates: (id) => request(`/contragents/${id}/hourly-rates`),
  createContragentHourlyRate: (id, data) =>
    request(`/contragents/${id}/hourly-rates`, { method: "POST", body: JSON.stringify(data) }),
  deleteContragentHourlyRate: (id, rateId) =>
    request(`/contragents/${id}/hourly-rates/${rateId}`, { method: "DELETE" }),
  importContragentHourlyRates: (id, file) => {
    const formData = new FormData();
    formData.append("file", file);
    return request(`/contragents/${id}/hourly-rates/import`, { method: "POST", body: formData });
  },

  // Справочник нормо-часов
  listLaborCatalog: () => request("/labor-catalog"),
  createLaborCatalogEntry: (data) => request("/labor-catalog", { method: "POST", body: JSON.stringify(data) }),
  updateLaborCatalogEntry: (id, data) =>
    request(`/labor-catalog/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteLaborCatalogEntry: (id) => request(`/labor-catalog/${id}`, { method: "DELETE" }),

  // Ozon: статистика/инфографика
  ozonStatsSummary: () => request("/ozon/stats/summary"),
  ozonStatsProducts: (sort, order) => request(`/ozon/stats/products${withPaging({ sort, order })}`),
  ozonProductPriceHistory: (productId) => request(`/ozon/stats/products/${productId}/history`),

  // Номенклатура/остатки (внутренний склад заказчика)
  listNomenclature: (q = "", params = {}) => request(`/nomenclature${withPaging({ q, ...params })}`),
  createNomenclatureEntry: (data) => request("/nomenclature", { method: "POST", body: JSON.stringify(data) }),
  updateNomenclatureEntry: (id, data) =>
    request(`/nomenclature/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteNomenclatureEntry: (id) => request(`/nomenclature/${id}`, { method: "DELETE" }),
  uploadNomenclatureFile: (files) => {
    const formData = new FormData();
    (Array.isArray(files) ? files : [files]).forEach((f) => formData.append("file", f));
    return request("/nomenclature/upload", { method: "POST", body: formData });
  },
  downloadNomenclatureTemplate: () => request("/nomenclature/template"),

  getCompanyProfile: () => request("/company-profile"),
  updateCompanyProfile: (data) => request("/company-profile", { method: "PUT", body: JSON.stringify(data) }),

  listDocumentTemplates: () => request("/document-templates"),
  uploadDocumentTemplate: (name, file) => {
    const formData = new FormData();
    formData.append("name", name);
    formData.append("file", file);
    return request("/document-templates", { method: "POST", body: formData });
  },
  deleteDocumentTemplate: (id) => request(`/document-templates/${id}`, { method: "DELETE" }),
  downloadStarterTemplate: () => request("/document-templates/starter"),
  previewRenderedTemplate: ({ templateId, file }) => {
    const formData = new FormData();
    if (templateId) formData.append("template_id", templateId);
    if (file) formData.append("file", file);
    return request("/document-templates/preview-rendered", { method: "POST", body: formData });
  },

  previewFile: (file) => {
    const formData = new FormData();
    formData.append("file", file);
    return request("/file-preview", { method: "POST", body: formData });
  },
  getRepairOrderSourceFile: (repairOrderId, source) =>
    request(`/repair-orders/upload/${repairOrderId}/file?source=${source}`),

  checkForUpdate: () => request("/update/check"),
  getPendingUpdateResult: () => request("/update/pending-result"),
  startUpdateDownload: () => request("/update/download", { method: "POST" }),
  getUpdateProgress: () => request("/update/progress"),
  cancelUpdateDownload: () => request("/update/cancel", { method: "POST" }),
  applyUpdate: () => request("/update/apply", { method: "POST" }),
};
