<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import OrderLine from "./OrderLine.vue";
import {
  archiveSalesOrder,
  fetchSalesOrder,
  restoreSalesOrder,
  updateSalesOrderCustomerNo,
} from "../api";

const props = defineProps({ id: String });
const route = useRoute();
const router = useRouter();
const order = ref(null);
const selectedLineId = ref(null);
const selectedLine = computed(() => order.value?.lines.find((line) => line.id === selectedLineId.value));
const actionLoading = ref(false);
const editingCustomerNo = ref(false);
const customerNoDraft = ref("");
const savingCustomerNo = ref(false);
let loadVersion = 0;

async function load() {
  const version = ++loadVersion;
  const orderId = props.id;
  if (order.value && String(order.value.id) !== String(orderId)) {
    order.value = null;
    selectedLineId.value = null;
    editingCustomerNo.value = false;
    customerNoDraft.value = "";
  }
  const result = await fetchSalesOrder(orderId);
  if (version !== loadVersion || String(props.id) !== String(orderId)) return;
  order.value = result;
  const requestedLine = Number(route.query.line);
  selectedLineId.value = order.value.lines.find((line) => line.id === requestedLine)?.id
    || order.value.lines[0]?.id
    || null;
}

function selectLine(lineId) {
  selectedLineId.value = lineId;
  router.replace({ path: route.path, query: { ...route.query, line: String(lineId) } });
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
}

function blockingText() {
  return (order.value?.blocking_sizes || []).map((row) => `${row.size} 码还需 ${row.remaining} 件`).join("，");
}

async function archiveOrder() {
  const orderId = order.value?.id;
  if (!orderId || String(props.id) !== String(orderId)) return;
  try {
    await ElMessageBox.confirm(
      `确认归档订单 ${order.value.system_order_no}？归档后员工不能再选择该订单发货。`,
      "确认归档",
      { type: "warning", confirmButtonText: "确认归档", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }
  if (String(props.id) !== String(orderId)) return;
  actionLoading.value = true;
  try {
    const result = await archiveSalesOrder(orderId);
    if (String(props.id) === String(orderId)) order.value = result;
    ElMessage.success("订单已归档");
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    actionLoading.value = false;
  }
}

async function restoreOrder() {
  const orderId = order.value?.id;
  if (!orderId || String(props.id) !== String(orderId)) return;
  try {
    await ElMessageBox.confirm(
      `确认恢复订单 ${order.value.system_order_no}？恢复后员工可以再次选择该订单发货。`,
      "确认恢复",
      { type: "warning", confirmButtonText: "确认恢复", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }
  if (String(props.id) !== String(orderId)) return;
  actionLoading.value = true;
  try {
    const result = await restoreSalesOrder(orderId);
    if (String(props.id) === String(orderId)) order.value = result;
    ElMessage.success("订单已恢复");
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    actionLoading.value = false;
  }
}

function startEditCustomerNo() {
  customerNoDraft.value = order.value?.customer_order_no || "";
  editingCustomerNo.value = true;
}

function cancelEditCustomerNo() {
  editingCustomerNo.value = false;
}

async function saveCustomerNo() {
  const orderId = order.value?.id;
  if (!orderId || String(props.id) !== String(orderId)) return;
  savingCustomerNo.value = true;
  try {
    await updateSalesOrderCustomerNo(orderId, customerNoDraft.value);
    if (String(props.id) === String(orderId)) await load();
    editingCustomerNo.value = false;
    ElMessage.success("客户订单号已保存");
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    savingCustomerNo.value = false;
  }
}

onMounted(load);
watch(() => props.id, load);
watch(() => route.query.line, (lineId) => {
  const match = order.value?.lines.find((line) => line.id === Number(lineId));
  if (match) selectedLineId.value = match.id;
});
</script>

<template>
  <div v-if="order">
    <div class="filter-bar">
      <h1 class="page-title">订单 {{ order.system_order_no }}</h1>
      <span>客户订单号：<b>{{ order.customer_order_no || "—" }}</b></span>
      <el-tag :type="order.is_archived ? 'info' : 'success'">{{ order.is_archived ? "已归档" : "进行中" }}</el-tag>
      <el-button
        v-if="!order.is_archived"
        type="warning"
        :loading="actionLoading"
        :disabled="!order.can_archive"
        @click="archiveOrder"
      >归档订单</el-button>
      <el-button v-else type="primary" :loading="actionLoading" @click="restoreOrder">恢复订单</el-button>
    </div>
    <div class="section-card">
      <el-alert
        v-if="!order.is_archived && !order.can_archive"
        type="warning"
        :closable="false"
        :title="blockingText() || '订单没有有效明细，不能归档'"
        show-icon
        style="margin-bottom:16px"
      />
      <el-alert
        v-if="order.is_archived"
        type="info"
        :closable="false"
        :title="`归档人：${order.current_archive?.archived_by_name || '—'}；归档时间：${formatTime(order.current_archive?.archived_at)}`"
        show-icon
        style="margin-bottom:16px"
      />
      <el-descriptions :column="3" border>
        <el-descriptions-item label="系统订单号">{{ order.system_order_no }}</el-descriptions-item>
        <el-descriptions-item label="客户订单号">
          <template v-if="editingCustomerNo">
            <el-input
              v-model="customerNoDraft"
              size="small"
              maxlength="160"
              placeholder="客户没有则留空"
              style="max-width: 260px"
              @keyup.enter="saveCustomerNo"
            />
            <el-button
              size="small"
              type="primary"
              :loading="savingCustomerNo"
              @click="saveCustomerNo"
            >保存</el-button>
            <el-button size="small" :disabled="savingCustomerNo" @click="cancelEditCustomerNo">取消</el-button>
          </template>
          <template v-else>
            {{ order.customer_order_no || "—" }}
            <el-button link type="primary" size="small" @click="startEditCustomerNo">编辑</el-button>
          </template>
        </el-descriptions-item>
        <el-descriptions-item label="公司">{{ order.company.name }}</el-descriptions-item>
        <el-descriptions-item label="SPU">{{ order.spu.code }}</el-descriptions-item>
        <el-descriptions-item label="产品/款式">{{ order.product_name }} / {{ order.style_name }}</el-descriptions-item>
        <el-descriptions-item label="颜色">{{ order.color_name ? `${order.color_name} (${order.color_code})` : "无颜色" }}</el-descriptions-item>
        <el-descriptions-item label="下单日期">{{ order.order_date }}</el-descriptions-item>
        <el-descriptions-item label="交期">{{ order.delivery_date || "—" }}</el-descriptions-item>
        <el-descriptions-item label="备注">{{ order.note || "—" }}</el-descriptions-item>
      </el-descriptions>
      <h3>尺码明细</h3>
      <el-table :data="order.lines" border>
        <el-table-column label="尺码" width="110">
          <template #default="{ row }">
            <el-button type="primary" link @click="selectLine(row.id)">{{ row.size }}</el-button>
            <el-tag v-if="row.id === selectedLineId" size="small" type="success">当前</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="quantity" label="下单" width="90" />
        <el-table-column prop="totals.shipped" label="已发" width="90" />
        <el-table-column prop="totals.returned" label="已退/返工" width="105" />
        <el-table-column prop="totals.adjusted" label="核销/调整" width="105" />
        <el-table-column prop="totals.closed" label="关闭" width="90" />
        <el-table-column prop="totals.remaining" label="还差" width="90" />
        <el-table-column prop="customer_sku" label="客户 SKU"><template #default="{ row }">{{ row.customer_sku || "—" }}</template></el-table-column>
      </el-table>
      <template v-if="order.history?.length">
        <h3>归档记录</h3>
        <el-table :data="order.history" border>
          <el-table-column label="归档时间" min-width="170"><template #default="{ row }">{{ formatTime(row.archived_at) }}</template></el-table-column>
          <el-table-column prop="archived_by_name" label="归档人" min-width="100" />
          <el-table-column label="恢复时间" min-width="170"><template #default="{ row }">{{ formatTime(row.restored_at) }}</template></el-table-column>
          <el-table-column prop="restored_by_name" label="恢复人" min-width="100"><template #default="{ row }">{{ row.restored_by_name || "—" }}</template></el-table-column>
        </el-table>
      </template>
    </div>
    <div v-if="selectedLine" class="section-card">
      <h2>{{ selectedLine.size }} 码详细记录</h2>
      <OrderLine :key="selectedLine.id" :id="selectedLine.id" embedded @updated="load" />
    </div>
  </div>
</template>
