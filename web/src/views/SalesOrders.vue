<script setup>
import { onMounted, ref } from "vue";
import { fetchCompanies, fetchSalesOrders } from "../api";

const orders = ref([]);
const companies = ref([]);
const companyId = ref("");
const q = ref("");
const loading = ref(false);

async function load() {
  loading.value = true;
  try {
    orders.value = (await fetchSalesOrders({ company_id: companyId.value, q: q.value })).orders;
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  companies.value = (await fetchCompanies()).companies;
  load();
});
</script>

<template>
  <div>
    <h1 class="page-title">正式订单</h1>
    <div class="section-card">
      <div class="filter-bar">
        <el-select v-model="companyId" placeholder="全部公司" clearable style="width:180px" @change="load">
          <el-option v-for="c in companies" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-input v-model="q" placeholder="订单号、客户单号或款式" clearable style="width:260px" @keyup.enter="load" />
        <el-button type="primary" @click="load">查询</el-button>
        <el-button @click="$router.push('/orders/new')">新增订单</el-button>
      </div>
      <el-table :data="orders" v-loading="loading" border>
        <el-table-column label="系统订单号" min-width="190">
          <template #default="{ row }"><el-button type="primary" link @click="$router.push(`/sales-orders/${row.id}`)">{{ row.system_order_no }}</el-button></template>
        </el-table-column>
        <el-table-column prop="customer_order_no" label="客户订单号" min-width="130" />
        <el-table-column prop="company.name" label="公司" min-width="110" />
        <el-table-column prop="spu.code" label="SPU" width="120" />
        <el-table-column prop="style_name" label="款式" min-width="150" />
        <el-table-column prop="color_name" label="颜色" width="100"><template #default="{ row }">{{ row.color_name || "—" }}</template></el-table-column>
        <el-table-column prop="order_date" label="下单日期" width="110" />
        <el-table-column label="数量" width="90" align="right"><template #default="{ row }">{{ row.lines.reduce((n, l) => n + l.quantity, 0) }}</template></el-table-column>
      </el-table>
    </div>
  </div>
</template>
