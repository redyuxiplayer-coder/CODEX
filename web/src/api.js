async function request(path, options = {}) {
  const response = await fetch(path, { credentials: "same-origin", ...options });
  if (response.status === 401) {
    throw new Error("请先登录");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "请求失败");
  }
  return data;
}

export function login(username, password) {
  const body = new URLSearchParams({ username, password });
  return request("/api/v1/login", { method: "POST", body });
}

export function logout() {
  return request("/api/v1/logout", { method: "POST" });
}

export function me() {
  return request("/api/v1/me");
}

export function fetchBalances(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) query.set(key, value);
  });
  const suffix = query.toString() ? `?${query}` : "";
  return request(`/api/v1/orders/balances${suffix}`);
}

export function fetchOrderLine(id) {
  return request(`/api/v1/order-lines/${id}`);
}

export function postForm(path, data) {
  const body = new URLSearchParams();
  Object.entries(data).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      body.set(key, value);
    }
  });
  return request(path, { method: "POST", body });
}

export function postFormData(path, formData) {
  return request(path, { method: "POST", body: formData });
}

export function postJson(path, data) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function fetchCompanies() {
  return request("/api/v1/companies");
}

export function updateCompanyCode(companyId, code) {
  return postJson(`/api/v1/companies/${companyId}/code`, { code });
}

export function fetchSpus(q = "") {
  return request(`/api/v1/spus${q ? `?q=${encodeURIComponent(q)}` : ""}`);
}

export function createSpu(data) {
  return postJson("/api/v1/spus", data);
}

export function updateSpu(spuId, data) {
  return postJson(`/api/v1/spus/${spuId}/update`, data);
}

export function fetchSalesOrders(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) query.set(key, value);
  });
  const suffix = query.toString() ? `?${query}` : "";
  return request(`/api/v1/sales-orders${suffix}`);
}

export function fetchSalesOrder(orderId) {
  return request(`/api/v1/sales-orders/${orderId}`);
}

export function archiveSalesOrder(orderId) {
  return request(`/api/v1/sales-orders/${orderId}/archive`, { method: "POST" });
}

export function restoreSalesOrder(orderId) {
  return request(`/api/v1/sales-orders/${orderId}/restore`, { method: "POST" });
}

export function createSalesOrder(data) {
  return postJson("/api/v1/sales-orders", data);
}

export function fetchDashboard() {
  return request("/api/v1/dashboard");
}

export function fetchOrdersOptions() {
  return request("/api/v1/orders/options");
}

export function createOrders(data) {
  return postForm("/api/v1/orders", data);
}

export function fetchReviewPending() {
  return request("/api/v1/review/pending");
}

export function reviewApprove(reportId, note) {
  return postForm(`/api/v1/review/${reportId}/approve`, { note });
}

export function reviewReject(reportId, note) {
  return postForm(`/api/v1/review/${reportId}/reject`, { note });
}

export function workInfoProposalApprove(proposalId, note) {
  return postForm(`/api/v1/work-info/proposals/${proposalId}/approve`, { note });
}

export function workInfoProposalReject(proposalId, note) {
  return postForm(`/api/v1/work-info/proposals/${proposalId}/reject`, { note });
}

export function fetchShipments(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) query.set(key, value);
  });
  const suffix = query.toString() ? `?${query}` : "";
  return request(`/api/v1/shipments${suffix}`);
}

export function uploadShipmentPhotos(reportId, formData) {
  return postFormData(`/api/v1/shipments/${reportId}/photos`, formData);
}

export function updateShipmentWaybill(reportId, waybillNo) {
  return postForm(`/api/v1/shipments/${reportId}/waybill`, { waybill_no: waybillNo });
}

export function fetchSkus(q = "") {
  return request(`/api/v1/skus${q ? `?q=${encodeURIComponent(q)}` : ""}`);
}

export function updateSku(mappingId, data) {
  return postForm(`/api/v1/skus/${mappingId}/update`, data);
}

export function importSkus(formData) {
  return postFormData("/api/v1/skus/import", formData);
}

export function fetchDailyStats(shipDate = "") {
  return request(`/api/v1/daily-stats${shipDate ? `?ship_date=${shipDate}` : ""}`);
}

export function fetchGoals(goalDate = "") {
  return request(`/api/v1/goals${goalDate ? `?goal_date=${goalDate}` : ""}`);
}

export function saveGoals(goalDate, goalText) {
  return postForm("/api/v1/goals", { goal_date: goalDate, goal_text: goalText });
}

export function fetchUsers() {
  return request("/api/v1/users");
}

export function createUser(data) {
  return postForm("/api/v1/users", data);
}

export function updateUser(userId, data) {
  return postForm(`/api/v1/users/${userId}/update`, data);
}

export function setUserPassword(userId, password) {
  return postForm(`/api/v1/users/${userId}/password`, { password });
}

export function fetchLogs() {
  return request("/api/v1/logs");
}

export function fetchWaybills() {
  return request("/api/v1/waybills");
}

export function uploadWaybills(formData) {
  return postFormData("/api/v1/waybills/upload", formData);
}

export function updateWaybillDate(photoId, waybillDate) {
  return postForm(`/api/v1/waybills/${photoId}/date`, { waybill_date: waybillDate });
}

export function fetchWorkInfo(company, product, style) {
  const query = new URLSearchParams({ company, product, style });
  return request(`/api/v1/work-info?${query}`);
}

export function saveWorkInfo(formData) {
  return postFormData("/api/v1/work-info", formData);
}

export function fetchLogistics(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) query.set(key, value);
  });
  const suffix = query.toString() ? `?${query}` : "";
  return request(`/api/v1/logistics${suffix}`);
}

export function createLogistics(data) {
  return postForm("/api/v1/logistics", data);
}

export function updateLogistics(id, data) {
  return postForm(`/api/v1/logistics/${id}/update`, data);
}

export function deleteLogistics(id) {
  return request(`/api/v1/logistics/${id}`, { method: "DELETE" });
}

export function fetchLogisticsDetail(id) {
  return request(`/api/v1/logistics/${id}`);
}

export function linkLogisticsReports(id, reportIds) {
  const body = new URLSearchParams();
  reportIds.forEach((reportId) => body.append("report_ids", reportId));
  return request(`/api/v1/logistics/${id}/reports`, { method: "POST", body });
}

export function unlinkLogisticsReport(id, reportId) {
  return request(`/api/v1/logistics/${id}/reports/${reportId}/remove`, { method: "POST" });
}

export function fetchLogisticsCandidates(company, shipDate) {
  const query = new URLSearchParams({ company, ship_date: shipDate });
  return request(`/api/v1/logistics/candidates?${query}`);
}

export function fetchUnlinkedLogistics(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) query.set(key, value);
  });
  const suffix = query.toString() ? `?${query}` : "";
  return request(`/api/v1/logistics/unlinked${suffix}`);
}

export function quickLinkLogistics(data) {
  return postForm("/api/v1/logistics/quick-link", data);
}

export function setUnlinkedReason(reportId, reason) {
  return postForm(`/api/v1/shipments/${reportId}/unlinked-reason`, { reason });
}
