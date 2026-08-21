function fillSelect(select, values, placeholder = "") {
  select.innerHTML = "";
  if (placeholder) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = placeholder;
    select.appendChild(option);
  }
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
}

async function fetchReportOptions(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) query.set(key, value);
  });
  const response = await fetch(`/mobile/report/options${query.toString() ? `?${query}` : ""}`, {
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new Error("options request failed");
  }
  return response.json();
}

function getSizeBalance(company, product, style) {
  const choices = window.ORDER_CHOICES || {};
  const balances = window.ORDER_BALANCES || {};
  const sizes = (((choices[company] || {})[product] || {})[style]) || [];
  const balanceBySize = (((balances[company] || {})[product] || {})[style]) || {};
  return { sizes, balances: balanceBySize };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderSizeRows(sizes, balanceBySize) {
  const box = document.getElementById("size-box");
  if (!box) return;
  box.innerHTML = "<label>尺码数量</label>";
  sizes.forEach((size) => {
    const balance = balanceBySize[size] || { ordered: 0, shipped: 0, remaining: 0, over_shipped: 0 };
    const alertClass = balance.over_shipped > 0 ? " danger-card" : (balance.remaining <= 0 ? " done-card" : "");
    const row = document.createElement("div");
    row.className = `size-row balance-size-row${alertClass}`;
    row.innerHTML = `
      <label>${size}</label>
      <input type="hidden" name="sizes" value="${size}">
      <div class="qty-wrap">
        <input name="quantities" type="text" inputmode="decimal" value="0" placeholder="如 60+60+45">
        <button type="button" class="plus-btn" aria-label="追加加号">+</button>
      </div>
      <div class="size-balance-hint">下单 ${balance.ordered} / 已发 ${balance.shipped} / 还差 ${balance.remaining}${balance.over_shipped > 0 ? ` / 超发 ${balance.over_shipped}` : ""}</div>
    `;
    box.appendChild(row);
  });
  if (!sizes.length) {
    box.innerHTML += "<p class='hint'>还没有可选尺码，请先在电脑端导入或新增订单。</p>";
  }
}

function renderOrderLineRows(lines) {
  const box = document.getElementById("size-box");
  if (!box) return;
  box.innerHTML = "<label>订单尺码数量</label>";
  lines.forEach((line) => {
    const alertClass = line.over_shipped > 0 ? " danger-card" : (line.remaining <= 0 ? " done-card" : "");
    const row = document.createElement("div");
    row.className = `size-row balance-size-row${alertClass}`;
    const orderLabel = `${line.size}${line.customer_sku ? ` / 客户SKU ${line.customer_sku}` : ""}`;
    row.innerHTML = `
      <label>${escapeHtml(orderLabel)}</label>
      <input type="hidden" name="order_line_ids" value="${escapeHtml(line.order_line_id || "")}">
      <input type="hidden" name="sizes" value="${escapeHtml(line.size)}">
      <div class="qty-wrap">
        <input name="quantities" type="text" inputmode="decimal" value="0" placeholder="如 60+60+45">
        <button type="button" class="plus-btn" aria-label="追加加号">+</button>
      </div>
      <div class="size-balance-hint">本单下单 ${line.ordered} / 已发 ${line.shipped} / 还差 ${line.remaining}${line.over_shipped > 0 ? ` / 超发 ${line.over_shipped}` : ""}</div>
    `;
    box.appendChild(row);
  });
  if (!lines.length) {
    box.innerHTML += "<p class='hint'>还没有可选订单，请先在电脑端导入或新增订单。</p>";
  }
}

function getNewReportForm() {
  return document.querySelector('.report-draft-form[data-autosave-key="new"]');
}

async function updateFormalOrderLines() {
  const form = getNewReportForm();
  const select = form && form.querySelector('[name="order_id"]');
  const detail = document.getElementById("formal-order-detail");
  const box = document.getElementById("size-box");
  if (!select || !select.value) {
    if (detail) detail.textContent = "";
    renderOrderLineRows([]);
    return;
  }
  if (box) box.innerHTML = "<label>订单尺码数量</label><p class='hint'>订单加载中...</p>";
  const result = await fetchReportOptions({ order_id: select.value });
  const order = result.order || {};
  if (detail) {
    detail.textContent =
      `${order.company_name || ""} · ${order.product_name || ""} · ${order.style_name || ""} · `
      + `${order.color_name || "无颜色"} · 下单 ${order.order_date || "未填写"} · 还差 ${order.remaining_summary || "已发完"}`;
  }
  renderOrderLineRows(result.lines || []);
}

function setupFormalOrderSelector() {
  const form = getNewReportForm();
  const select = form && form.querySelector('[name="order_id"]');
  const companyFilter = form && form.querySelector("[data-order-company-filter]");
  const styleColorFilter = form && form.querySelector("[data-order-style-color-filter]");
  const searchInput = form && form.querySelector("[data-order-search-filter]");
  if (!form || !select || !companyFilter || !styleColorFilter || !searchInput) return;

  const placeholderOption = select.querySelector('option[value=""]');
  const orderOptions = Array.from(select.options).filter((option) => option.value);

  const updateStyleColorChoices = () => {
    const company = companyFilter.value;
    const values = Array.from(new Set(
      orderOptions
        .filter((option) => !company || option.dataset.company === company)
        .map((option) => option.dataset.styleColor || "")
        .filter(Boolean),
    ));
    const current = styleColorFilter.value;
    fillSelect(styleColorFilter, values, "全部款式/颜色");
    if (current && values.includes(current)) {
      styleColorFilter.value = current;
    }
  };

  const filterOptions = () => {
    const company = companyFilter.value;
    const styleColor = styleColorFilter.value;
    const query = searchInput.value.trim().toLowerCase();
    const selectedValue = select.value;
    const visibleOptions = orderOptions.filter((option) => (
      (!company || option.dataset.company === company)
        && (!styleColor || option.dataset.styleColor === styleColor)
        && (!query || option.dataset.search.toLowerCase().includes(query.toLowerCase()))
    ));
    select.replaceChildren(...(placeholderOption ? [placeholderOption] : []), ...visibleOptions);
    if (selectedValue && visibleOptions.some((option) => option.value === selectedValue)) {
      select.value = selectedValue;
    } else if (selectedValue) {
      select.value = "";
      updateFormalOrderLines();
    }
  };

  form._formalOrderFilters = {
    updateStyleColorChoices,
    filterOptions,
  };

  fillSelect(companyFilter, Array.from(new Set(orderOptions.map((option) => option.dataset.company || "").filter(Boolean))), "全部公司");
  updateStyleColorChoices();
  filterOptions();

  companyFilter.addEventListener("change", () => {
    updateStyleColorChoices();
    filterOptions();
    saveReportDraft(form);
    if (form._syncReportLogistics) form._syncReportLogistics();
  });
  styleColorFilter.addEventListener("change", () => {
    filterOptions();
    saveReportDraft(form);
  });
  searchInput.addEventListener("input", () => {
    filterOptions();
    saveReportDraft(form);
  });
  select.addEventListener("change", async () => {
    await updateFormalOrderLines();
    if (form._syncReportLogistics) form._syncReportLogistics();
    saveReportDraft(form);
  });
  renderOrderLineRows([]);
}

async function updateProducts(preferredProduct = "") {
  const choices = window.ORDER_CHOICES || {};
  const company = document.getElementById("company").value;
  const productSelect = document.getElementById("product");
  const styleSelect = document.getElementById("style");
  if (!company) {
    fillSelect(productSelect, [], "请先选择公司");
    fillSelect(styleSelect, [], "请先选择产品");
    renderSizeRows([], {});
    return;
  }
  fillSelect(productSelect, [], "产品加载中...");
  fillSelect(styleSelect, [], "请先选择产品");
  renderSizeRows([], {});
  const products = window.ORDER_CHOICES
    ? Object.keys(choices[company] || {})
    : (await fetchReportOptions({ company })).products || [];
  fillSelect(productSelect, products, "请选择产品");
  if (preferredProduct) productSelect.value = preferredProduct;
  await updateStyles();
}

async function updateStyles(preferredStyle = "") {
  const choices = window.ORDER_CHOICES || {};
  const company = document.getElementById("company").value;
  const product = document.getElementById("product").value;
  const styleSelect = document.getElementById("style");
  if (!company || !product) {
    fillSelect(styleSelect, [], "请先选择产品");
    renderSizeRows([], {});
    return;
  }
  fillSelect(styleSelect, [], "款式加载中...");
  renderSizeRows([], {});
  const styles = window.ORDER_CHOICES
    ? Object.keys(((choices[company] || {})[product]) || {})
    : (await fetchReportOptions({ company, product })).styles || [];
  fillSelect(styleSelect, styles, "请选择款式");
  if (preferredStyle) styleSelect.value = preferredStyle;
  await updateSizes();
}

async function updateSizes() {
  const company = document.getElementById("company").value;
  const product = document.getElementById("product").value;
  const style = document.getElementById("style").value;
  const box = document.getElementById("size-box");
  if (!company || !product || !style) {
    renderSizeRows([], {});
    return;
  }
  if (box) box.innerHTML = "<label>尺码数量</label><p class='hint'>尺码加载中...</p>";
  if (window.ORDER_BALANCES) {
    const result = getSizeBalance(company, product, style);
    renderSizeRows(result.sizes, result.balances);
    return;
  }
  const result = await fetchReportOptions({ company, product, style });
  if (result.lines) {
    renderOrderLineRows(result.lines || []);
  } else {
    renderSizeRows(result.sizes || [], result.balances || {});
  }
}

function getReportDraftKey(form, packDateOverride) {
  if (form.dataset.autosaveKey === "new") {
    const packDate = (packDateOverride ?? (form.querySelector('[name="pack_date"]')?.value || "")).trim();
    return `zy-report-draft:new:${packDate}`;
  }
  return `zy-report-draft:${form.dataset.autosaveKey || "new"}`;
}

function updateReportDraftKey(form, nextKey) {
  const previousKey = form.dataset.reportDraftKey || "";
  if (previousKey && previousKey !== nextKey) {
    try {
      localStorage.removeItem(previousKey);
    } catch (_) {
      // Ignore storage write failures and continue with normal submission flow.
    }
  }
  form.dataset.reportDraftKey = nextKey;
}

function collectReportDraft(form) {
  return {
    packDate: form.querySelector('[name="pack_date"]')?.value || "",
    orderId: form.querySelector('[name="order_id"]')?.value || "",
    orderCompanyFilter: form.querySelector("[data-order-company-filter]")?.value || "",
    orderStyleColorFilter: form.querySelector("[data-order-style-color-filter]")?.value || "",
    orderSearchFilter: form.querySelector("[data-order-search-filter]")?.value || "",
    company: form.querySelector('[name="company_name"]')?.value || "",
    product: form.querySelector('[name="product_name"]')?.value || "",
    style: form.querySelector('[name="style_name"]')?.value || "",
    shippingMethod: form.querySelector('[name="shipping_method"]')?.value || "",
    tripMode: form.querySelector("[data-trip-mode]:checked")?.value || "new",
    existingTrip: form.querySelector("[data-existing-trip]")?.value || "",
    waybillNo: form.querySelector('[name="waybill_no"]')?.value || "",
    packageCount: form.querySelector('[name="package_count"]')?.value || "",
    weightKg: form.querySelector('[name="weight_kg"]')?.value || "",
    note: form.querySelector('[name="note"]')?.value || "",
    quantities: Array.from(form.querySelectorAll('[name="quantities"]')).map((input) => input.value),
  };
}

function saveReportDraft(form) {
  const nextKey = getReportDraftKey(form);
  try {
    updateReportDraftKey(form, nextKey);
    localStorage.setItem(nextKey, JSON.stringify(collectReportDraft(form)));
  } catch (_) {
    // Local storage can be unavailable in private mode; submission should still work.
  }
}

async function restoreReportDraft(form) {
  const draftKey = getReportDraftKey(form);
  form.dataset.reportDraftKey = draftKey;
  let draft;
  try {
    draft = JSON.parse(localStorage.getItem(draftKey) || "null");
  } catch (_) {
    draft = null;
  }
  if (!draft) return;

  const packDateInput = form.querySelector('[name="pack_date"]');
  if (packDateInput && draft.packDate) {
    packDateInput.value = draft.packDate;
  }

  const companyFilter = form.querySelector("[data-order-company-filter]");
  const styleColorFilter = form.querySelector("[data-order-style-color-filter]");
  const searchFilter = form.querySelector("[data-order-search-filter]");
  if (companyFilter && draft.orderCompanyFilter) {
    companyFilter.value = draft.orderCompanyFilter;
  }
  if (searchFilter && draft.orderSearchFilter) {
    searchFilter.value = draft.orderSearchFilter;
  }
  if (form._formalOrderFilters) {
    form._formalOrderFilters.updateStyleColorChoices();
  }
  if (styleColorFilter && draft.orderStyleColorFilter) {
    styleColorFilter.value = draft.orderStyleColorFilter;
  }
  if (form._formalOrderFilters) {
    form._formalOrderFilters.filterOptions();
  }

  const formalOrder = form.querySelector('[name="order_id"]');
  if (formalOrder && draft.orderId) {
    formalOrder.value = draft.orderId;
    await updateFormalOrderLines();
  }

  const company = form.querySelector('[name="company_name"]');
  const product = form.querySelector('[name="product_name"]');
  const style = form.querySelector('[name="style_name"]');
  if (company && draft.company) {
    company.value = draft.company;
  }
  if (product && draft.product) {
    await updateProducts(draft.product);
  } else if (company && draft.company) {
    await updateProducts();
  }
  if (style && draft.style) {
    await updateStyles(draft.style);
  }
  const shippingMethod = form.querySelector('[name="shipping_method"]');
  if (shippingMethod && draft.shippingMethod) {
    shippingMethod.value = draft.shippingMethod;
  }
  const tripMode = draft.tripMode || "";
  if (tripMode) {
    form.querySelectorAll("[data-trip-mode]").forEach((input) => {
      input.checked = input.value === tripMode;
    });
  }
  const existingTrip = form.querySelector("[data-existing-trip]");
  if (existingTrip && draft.existingTrip) {
    existingTrip.dataset.pendingValue = draft.existingTrip;
  }
  const waybillNo = form.querySelector('[name="waybill_no"]');
  if (waybillNo && draft.waybillNo !== undefined) {
    waybillNo.value = draft.waybillNo || "";
  }
  const packageCount = form.querySelector('[name="package_count"]');
  if (packageCount && draft.packageCount !== undefined) {
    packageCount.value = draft.packageCount || "";
  }
  const weightKg = form.querySelector('[name="weight_kg"]');
  if (weightKg && draft.weightKg !== undefined) {
    weightKg.value = draft.weightKg || "";
  }
  const note = form.querySelector('[name="note"]');
  if (note) note.value = draft.note || "";
  Array.from(form.querySelectorAll('[name="quantities"]')).forEach((input, index) => {
    if (draft.quantities && draft.quantities[index] !== undefined) input.value = draft.quantities[index];
  });
  form.dataset.lastLogisticsKey = "";
}

function updateSubmitStatus(form, message) {
  const status = form.querySelector(".upload-status");
  if (status) status.textContent = message;
  const button = form.querySelector('button[type="submit"], button:not([type])');
  if (button) {
    button.dataset.originalText = button.dataset.originalText || button.textContent;
    button.textContent = message;
    button.disabled = true;
  }
}

function setupPhotoLimit(form) {
  form.querySelectorAll('input[type="file"][name="photos"]').forEach((input) => {
    input.addEventListener("change", () => {
      if (input.files && input.files.length > 20) {
        alert("每次最多上传20张照片，请分批保存。");
        input.value = "";
        return;
      }
      compressSelectedPhotos(input, form);
    });
  });
}

const photoCompressionTasks = new WeakMap();

function setUploadStatus(form, message) {
  const status = form.querySelector(".upload-status");
  if (status) status.textContent = message;
}

function readImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("image load failed"));
    };
    image.src = url;
  });
}

function blobFromCanvas(canvas) {
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.58));
}

function withTimeout(promise, ms) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), ms)),
  ]);
}

async function compressOnePhoto(file) {
  if (!file.type.startsWith("image/") || file.size < 260 * 1024) return file;
  const image = await withTimeout(readImage(file), 8000);
  const maxSide = 1024;
  const scale = Math.min(1, maxSide / Math.max(image.naturalWidth || image.width, image.naturalHeight || image.height));
  if (scale >= 1 && file.size < 360 * 1024) return file;
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round((image.naturalWidth || image.width) * scale));
  canvas.height = Math.max(1, Math.round((image.naturalHeight || image.height) * scale));
  canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
  const blob = await withTimeout(blobFromCanvas(canvas), 8000);
  if (!blob || blob.size >= file.size) return file;
  const name = file.name.replace(/\.[^.]+$/, "") + ".jpg";
  return new File([blob], name, { type: "image/jpeg", lastModified: Date.now() });
}

function nextFrame() {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

async function compressSelectedPhotos(input, form) {
  if (!input.files || input.files.length === 0 || typeof DataTransfer === "undefined") return;
  const originalFiles = Array.from(input.files);
  input.dataset.compressing = "1";
  setUploadStatus(form, `正在压缩 ${originalFiles.length} 张照片，可先填写数量`);
  const task = (async () => {
    const transfer = new DataTransfer();
    let savedBytes = 0;
    for (const [index, file] of originalFiles.entries()) {
      setUploadStatus(form, `正在处理照片 ${index + 1}/${originalFiles.length}`);
      const compressed = await compressOnePhoto(file).catch(() => file);
      savedBytes += Math.max(0, file.size - compressed.size);
      transfer.items.add(compressed);
      await nextFrame();
    }
    input.files = transfer.files;
    const savedMb = (savedBytes / 1024 / 1024).toFixed(1);
    setUploadStatus(form, savedBytes > 0 ? `照片已压缩，约少传 ${savedMb}MB` : "照片已准备好，点击保存即可");
  })();
  photoCompressionTasks.set(input, task);
  try {
    await task;
  } finally {
    input.dataset.compressing = "0";
    if (photoCompressionTasks.get(input) === task) {
      photoCompressionTasks.delete(input);
    }
  }
}

async function waitForPhotoCompression(form) {
  const inputs = Array.from(form.querySelectorAll('input[type="file"][name="photos"]'));
  const tasks = inputs
    .filter((input) => input.dataset.compressing === "1")
    .map((input) => photoCompressionTasks.get(input))
    .filter(Boolean);
  if (!tasks.length) return;
  setUploadStatus(form, "照片处理中，处理完会自动保存");
  await Promise.allSettled(tasks);
}

function setupReportDraftForms() {
  document.querySelectorAll(".report-draft-form").forEach((form) => {
    if (form._currentWaybill) {
      form.dataset.currentWaybill = form._currentWaybill;
    }
    setupPhotoLimit(form);
    restoreReportDraft(form).then(() => {
      if (form._syncReportLogistics) form._syncReportLogistics();
    });
    form.addEventListener("input", () => saveReportDraft(form));
    form.addEventListener("change", () => saveReportDraft(form));
    form.addEventListener("submit", async (event) => {
      if (form.dataset.submitting === "1") return;
      event.preventDefault();
      form.dataset.submitting = "1";
      saveReportDraft(form);
      await waitForPhotoCompression(form);
      updateSubmitStatus(form, "保存中，请稍等");
      HTMLFormElement.prototype.submit.call(form);
    });
  });
}

function setupReportLogisticsForms() {
  document.querySelectorAll(".report-draft-form").forEach((form) => {
    const methodSelect = form.querySelector('[name="shipping_method"]');
    const waybillInput = form.querySelector("[data-waybill-input]");
    const waybillHint = form.querySelector("[data-waybill-hint]");
    const packDateInput = form.querySelector('[name="pack_date"]');
    const packageCountInput = form.querySelector('[name="package_count"]');
    const weightInput = form.querySelector('[name="weight_kg"]');
    const huolalaPanel = form.querySelector("[data-huolala-panel]");
    const existingTripSelect = form.querySelector("[data-existing-trip]");
    const tripModeInputs = Array.from(form.querySelectorAll("[data-trip-mode]"));
    if (!methodSelect || !waybillInput || !packDateInput || !packageCountInput || !weightInput) return;

    const getCurrentCompany = () => {
      const selectedOrder = form.querySelector('[name="order_id"] option:checked');
      if (selectedOrder && selectedOrder.dataset.company) return selectedOrder.dataset.company;
      return form.dataset.companyName || form.querySelector('[name="company_name"]')?.value || "";
    };

    const getTripMode = () => form.querySelector("[data-trip-mode]:checked")?.value || "new";

    const clearIncompatibleLogistics = () => {
      methodSelect.value = "";
      if (existingTripSelect) {
        existingTripSelect.value = "";
        existingTripSelect.dataset.pendingValue = "";
      }
      tripModeInputs.forEach((input) => {
        input.checked = input.value === "new";
      });
      waybillInput.value = "";
      packageCountInput.value = "";
      weightInput.value = "";
      form.dataset.currentWaybill = "";
    };

    const hasLogisticsValues = () => (
      !!methodSelect.value
      || !!waybillInput.value
      || !!packageCountInput.value
      || !!weightInput.value
      || !!(existingTripSelect && existingTripSelect.value)
    );

    const resetExistingTripOptions = (selectedValue = "") => {
      if (!existingTripSelect) return;
      existingTripSelect.innerHTML = '<option value="">请选择已有货拉拉车次</option>';
      existingTripSelect.value = selectedValue;
    };

    const renderExistingTripOptions = (trips, selectedValue = "") => {
      if (!existingTripSelect) return;
      resetExistingTripOptions();
      trips.forEach((trip) => {
        const option = document.createElement("option");
        option.value = trip.waybill_no || "";
        option.dataset.company = trip.company_name || "";
        option.dataset.packDate = trip.ship_date || "";
        option.dataset.packageCount = String(trip.package_count ?? "");
        option.dataset.weightKg = trip.weight_kg === undefined || trip.weight_kg === null ? "" : String(trip.weight_kg);
        option.textContent = `${trip.waybill_no}｜${trip.company_name}｜${trip.ship_date}｜${trip.package_count}件｜${trip.weight_kg}kg`;
        existingTripSelect.appendChild(option);
      });
      existingTripSelect.value = selectedValue;
      if (existingTripSelect.value !== selectedValue) {
        existingTripSelect.value = "";
      }
      existingTripSelect.dataset.pendingValue = existingTripSelect.value;
    };

    async function fetchHuolalaTrips(company, shipDate) {
      if (!company || !shipDate) return [];
      const params = new URLSearchParams({ company, ship_date: shipDate });
      const response = await fetch(`/mobile/report/huolala-trips?${params.toString()}`, {
        credentials: "same-origin",
      }).catch(() => null);
      if (!response || !response.ok) return [];
      const payload = await response.json().catch(() => ({ trips: [] }));
      return Array.isArray(payload.trips) ? payload.trips : [];
    }

    const loadExistingTrips = async () => {
      if (!existingTripSelect) return;
      const company = getCurrentCompany();
      const shipDate = packDateInput.value;
      const selectedValue = existingTripSelect.value
        || existingTripSelect.dataset.pendingValue
        || form.dataset.currentWaybill
        || "";
      if (!company || !shipDate) {
        form.dataset.tripQuery = "";
        resetExistingTripOptions();
        existingTripSelect.dataset.pendingValue = "";
        return;
      }
      const queryKey = `${company}|${shipDate}`;
      const requestKey = `${queryKey}|${Date.now()}`;
      form.dataset.tripRequestKey = requestKey;
      const trips = await fetchHuolalaTrips(company, shipDate);
      if (form.dataset.tripRequestKey !== requestKey) {
        return;
      }
      form.dataset.tripQuery = queryKey;
      renderExistingTripOptions(trips, selectedValue);
    };

    const sync = async () => {
      const currentKey = `${getCurrentCompany()}|${packDateInput.value}`;
      if (form.dataset.lastLogisticsKey && form.dataset.lastLogisticsKey !== currentKey && hasLogisticsValues()) {
        clearIncompatibleLogistics();
      }
      form.dataset.lastLogisticsKey = currentKey;

      const isCourier = methodSelect.value === "courier";
      const isHuolala = methodSelect.value === "huolala";
      const useExistingTrip = isHuolala && getTripMode() === "existing";

      if (huolalaPanel) huolalaPanel.hidden = !isHuolala;
      tripModeInputs.forEach((input) => {
        input.disabled = !isHuolala;
      });
      if (existingTripSelect) {
        existingTripSelect.disabled = !isHuolala;
        existingTripSelect.required = useExistingTrip;
      }

      waybillInput.required = isCourier;
      if (isCourier) {
        waybillInput.readOnly = false;
        packageCountInput.readOnly = false;
        weightInput.readOnly = false;
        waybillInput.placeholder = "例如 YT1234567890";
        if (waybillHint) waybillHint.textContent = "快递必须填写真实运单号。";
        return;
      }

      if (isHuolala) {
        await loadExistingTrips();
      } else if (existingTripSelect) {
        resetExistingTripOptions();
        existingTripSelect.dataset.pendingValue = "";
      }

      const selectedTrip = existingTripSelect && existingTripSelect.selectedOptions[0] && existingTripSelect.value
        ? existingTripSelect.selectedOptions[0]
        : null;

      if (isHuolala && useExistingTrip && selectedTrip) {
        waybillInput.value = selectedTrip.value;
        packageCountInput.value = selectedTrip.dataset.packageCount || "";
        weightInput.value = selectedTrip.dataset.weightKg || "";
        waybillInput.readOnly = true;
        packageCountInput.readOnly = true;
        weightInput.readOnly = true;
        existingTripSelect.dataset.pendingValue = selectedTrip.value;
        if (waybillHint) waybillHint.textContent = "已有货拉拉车次会自动带出并锁定件数和重量。";
        return;
      }

      waybillInput.readOnly = false;
      packageCountInput.readOnly = false;
      weightInput.readOnly = false;
      waybillInput.placeholder = isHuolala ? "留空会自动生成货拉拉车次号" : "例如 YT1234567890";
      if (useExistingTrip) {
        waybillInput.value = "";
        packageCountInput.value = "";
        weightInput.value = "";
      }
      if (waybillHint) {
        waybillHint.textContent = isHuolala
          ? (useExistingTrip ? "请先选择同公司同日期的已有车次。" : "货拉拉可新建车次，或选择已有车次复用。")
          : "请先选择发货方式。";
      }
    };

    const currentWaybill = form.dataset.currentWaybill || "";
    if (currentWaybill && existingTripSelect) {
      form._currentWaybill = currentWaybill;
      existingTripSelect.dataset.pendingValue = currentWaybill;
    }

    form._syncReportLogistics = sync;

    methodSelect.addEventListener("change", sync);
    packDateInput.addEventListener("change", sync);
    const formalOrder = form.querySelector('[name="order_id"]');
    if (formalOrder) {
      formalOrder.addEventListener("change", sync);
    }
    tripModeInputs.forEach((input) => input.addEventListener("change", sync));
    if (existingTripSelect) existingTripSelect.addEventListener("change", sync);
    sync();
  });
}

function setupQuantityPlusButtons() {
  document.addEventListener("click", (event) => {
    const button = event.target.closest(".plus-btn");
    if (!button) return;
    const wrap = button.closest(".qty-wrap");
    const input = wrap && wrap.querySelector('input[name="quantities"]');
    if (!input) return;
    event.preventDefault();
    const current = input.value.trim();
    input.value = current ? `${current}+` : "";
    input.focus();
  });
}

function setupBarcodeScan() {
  const input = document.getElementById("scan-code");
  const button = document.getElementById("scan-btn");
  if (!input || !button) return;
  async function scan() {
    const code = input.value.trim();
    if (!code) return;
    input.disabled = true;
    button.disabled = true;
    try {
      const response = await fetch(`/mobile/report/scan?code=${encodeURIComponent(code)}`, {
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error("scan failed");
      const data = await response.json();
      if (!data.company) {
        alert(data.detail || "未找到该条码对应的款式");
        return;
      }
      const company = document.getElementById("company");
      const product = document.getElementById("product");
      const style = document.getElementById("style");
      company.value = data.company;
      await updateProducts(data.product);
      await updateStyles(data.style);
      await updateSizes();
    } catch (_) {
      alert("扫码查询失败，请检查网络");
    } finally {
      input.disabled = false;
      button.disabled = false;
      input.focus();
    }
  }
  button.addEventListener("click", scan);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      scan();
    }
  });
}

function setupPhotoLightbox() {
  const overlay = document.createElement("div");
  overlay.className = "lightbox";
  overlay.innerHTML = `
    <button type="button" class="lightbox-close" aria-label="关闭">&times;</button>
    <button type="button" class="lightbox-rotate" aria-label="旋转90度">&#8635;</button>
    <button type="button" class="lightbox-prev" aria-label="上一张">&#10094;</button>
    <img class="lightbox-image" alt="">
    <button type="button" class="lightbox-next" aria-label="下一张">&#10095;</button>
  `;
  document.body.appendChild(overlay);

  let currentLinks = [];
  let currentIndex = 0;
  let rotation = 0;

  const image = overlay.querySelector(".lightbox-image");
  const close = () => {
    overlay.classList.remove("open");
    document.body.style.overflow = "";
    rotation = 0;
    image.style.transform = "";
  };
  const show = (index) => {
    currentIndex = (index + currentLinks.length) % currentLinks.length;
    image.src = currentLinks[currentIndex].getAttribute("href");
    rotation = 0;
    image.style.transform = "";
  };

  document.addEventListener("click", (event) => {
    const link = event.target.closest('a[data-lightbox]');
    if (!link) return;
    event.preventDefault();
    const group = link.getAttribute("data-lightbox");
    currentLinks = Array.from(document.querySelectorAll(`a[data-lightbox="${group}"]`));
    currentIndex = currentLinks.indexOf(link);
    overlay.classList.add("open");
    document.body.style.overflow = "hidden";
    show(currentIndex);
  });

  overlay.addEventListener("click", (event) => {
    if (event.target === overlay || event.target.classList.contains("lightbox-close")) {
      close();
    } else if (event.target.classList.contains("lightbox-prev")) {
      show(currentIndex - 1);
    } else if (event.target.classList.contains("lightbox-next")) {
      show(currentIndex + 1);
    } else if (event.target.classList.contains("lightbox-rotate")) {
      rotation = (rotation + 90) % 360;
      image.style.transform = `rotate(${rotation}deg)`;
    }
  });

  document.addEventListener("keydown", (event) => {
    if (!overlay.classList.contains("open")) return;
    if (event.key === "Escape") close();
    if (event.key === "ArrowLeft") show(currentIndex - 1);
    if (event.key === "ArrowRight") show(currentIndex + 1);
  });
}

function setupLoadMore() {
  document.querySelectorAll("[data-load-more]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.dataset.loading === "1") return;
      button.dataset.loading = "1";
      button.textContent = "加载中...";
      try {
        const response = await fetch(`${button.dataset.loadMore}&partial=1`, { credentials: "same-origin" });
        if (!response.ok) throw new Error("load more failed");
        const html = await response.text();
        const container = document.querySelector(button.dataset.target || "#my-reports-list");
        if (!container) return;
        const wrapper = document.createElement("div");
        wrapper.innerHTML = html.trim();
        wrapper.querySelectorAll(":scope > *").forEach((node) => container.appendChild(node));
        if (response.headers.get("X-Has-More") === "0") {
          button.remove();
          return;
        }
        const next = button.dataset.nextPage ? parseInt(button.dataset.nextPage, 10) : 2;
        button.dataset.nextPage = String(next + 1);
        button.dataset.loadMore = button.dataset.loadMore.replace(/([?&]page=)\d+/, `$1${next}`);
        button.textContent = "加载更多";
      } catch (_) {
        button.textContent = "加载失败，点击重试";
      } finally {
        button.dataset.loading = "0";
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const company = document.getElementById("company");
  if (company) {
    const companies = window.ORDER_COMPANIES || Object.keys(window.ORDER_CHOICES || {});
    fillSelect(company, companies, "请选择公司");
    company.addEventListener("change", () => updateProducts());
    document.getElementById("product").addEventListener("change", () => updateStyles());
    document.getElementById("style").addEventListener("change", () => updateSizes());
    fillSelect(document.getElementById("product"), [], "请先选择公司");
    fillSelect(document.getElementById("style"), [], "请先选择产品");
    renderSizeRows([], {});
  }
  setupFormalOrderSelector();
  setupReportLogisticsForms();
  setupReportDraftForms();
  setupQuantityPlusButtons();
  setupBarcodeScan();
  setupPhotoLightbox();
  setupLoadMore();

  const orderCompany = document.getElementById("order-company");
  if (!orderCompany) return;
  const orderProduct = document.getElementById("order-product");
  const orderStyle = document.getElementById("order-style");
  const productOptions = document.getElementById("product-options");
  const styleOptions = document.getElementById("style-options");

  function fillDatalist(list, values) {
    list.innerHTML = "";
    values.forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      list.appendChild(option);
    });
  }

  function updateOrderProducts() {
    const choices = window.ORDER_CHOICES || {};
    const products = Object.keys(choices[orderCompany.value] || {});
    fillDatalist(productOptions, products);
    updateOrderStyles();
  }

  function updateOrderStyles() {
    const choices = window.ORDER_CHOICES || {};
    const styles = Object.keys(((choices[orderCompany.value] || {})[orderProduct.value]) || {});
    fillDatalist(styleOptions, styles);
  }

  orderCompany.addEventListener("input", updateOrderProducts);
  orderProduct.addEventListener("input", updateOrderStyles);
  updateOrderProducts();
});
