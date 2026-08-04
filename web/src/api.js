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
