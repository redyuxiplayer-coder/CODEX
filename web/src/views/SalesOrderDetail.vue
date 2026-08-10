<script setup>
import { onMounted, ref } from "vue";
import { fetchSalesOrder } from "../api";

const props = defineProps({ id: String });
const order = ref(null);
onMounted(async () => { order.value = await fetchSalesOrder(props.id); });
</script>

<template>
  <div v-if="order">
    <h1 class="page-title">订单 {{ order.system_order_no }}</h1>
    <div class="section-card">
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
    </div>
  </div>
</template>
