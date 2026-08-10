<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { archiveSalesOrder, fetchSalesOrder, restoreSalesOrder } from "../api";

const props = defineProps({ id: String });
const order = ref(null);
const actionLoading = ref(false);

async function load() {
  order.value = await fetchSalesOrder(props.id);
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
}

function blockingText() {
  return (order.value?.blocking_sizes || []).map((row) => `${row.size} 码还需 ${row.remaining} 件`).join("，");
}

async function archiveOrder() {
  try {
    await ElMessageBox.confirm(
      `确认归档订单 ${order.value.system_order_no}？归档后员工不能再选择该订单发货。`,
      "确认归档",
      { type: "warning", confirmButtonText: "确认归档", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }
  actionLoading.value = true;
  try {
    order.value = await archiveSalesOrder(props.id);
    ElMessage.success("订单已归档");
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    actionLoading.value = false;
  }
}

async function restoreOrder() {
  try {
    await ElMessageBox.confirm(
      `确认恢复订单 ${order.value.system_order_no}？恢复后员工可以再次选择该订单发货。`,
      "确认恢复",
      { type: "warning", confirmButtonText: "确认恢复", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }
  actionLoading.value = true;
  try {
    order.value = await restoreSalesOrder(props.id);
    ElMessage.success("订单已恢复");
  } catch (error) {
    ElMessage.error(error.message);
  } finally {
    actionLoading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div v-if="order">
    <div class="filter-bar">
      <h1 class="page-title">订单 {{ order.system_order_no }}</h1>
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
        <el-descriptions-item label="客户订单号">{{ order.customer_order_no || "—" }}</el-descriptions-item>
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
        <el-table-column prop="size" label="尺码" width="120" />
        <el-table-column prop="quantity" label="数量" width="120" />
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
  </div>
</template>
