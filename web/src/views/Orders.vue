<script setup>
import { computed, onMounted, ref } from "vue";
import { fetchBalances } from "../api";

const company = ref("");
const item = ref("");
const status = ref("all");
const data = ref({ companies: [], item_choices: [], balances: [] });
const loading = ref(false);

async function load() {
  loading.value = true;
  try {
    data.value = await fetchBalances({
      company: company.value,
      item: item.value,
      status: status.value,
    });
  } finally {
    loading.value = false;
  }
}

onMounted(load);

const totals = computed(() => {
  const rows = data.value.balances;
  return {
    need: rows.filter((row) => row.remaining > 0).length,
    over: rows.filter((row) => row.over_shipped > 0).length,
    done: rows.filter((row) => row.remaining <= 0 && row.over_shipped <= 0).length,
    unshipped: rows.reduce((sum, row) => sum + Math.max(0, row.remaining), 0),
  };
});
</script>

<template>
  <div>
    <h1 class="page-title">订单查询</h1>

    <div class="stat-cards">
      <div class="stat-card"><div class="label">还差订单行</div><div class="value">{{ totals.need }}</div></div>
      <div class="stat-card"><div class="label">超发订单行</div><div class="value" style="color:#f56c6c">{{ totals.over }}</div></div>
      <div class="stat-card"><div class="label">已完成</div><div class="value" style="color:#67c23a">{{ totals.done }}</div></div>
      <div class="stat-card"><div class="label">未发合计</div><div class="value">{{ totals.unshipped }}</div></div>
    </div>

    <div class="section-card">
      <div class="filter-bar">
        <el-select v-model="company" placeholder="全部公司" clearable style="width:180px" @change="load">
          <el-option v-for="c in data.companies" :key="c" :label="c" :value="c" />
        </el-select>
        <el-select v-model="item" placeholder="全部货物" clearable style="width:180px" @change="load">
          <el-option v-for="choice in data.item_choices" :key="choice" :label="choice" :value="choice" />
        </el-select>
        <el-radio-group v-model="status" @change="load">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="need">只看还差</el-radio-button>
          <el-radio-button value="over">只看超发</el-radio-button>
          <el-radio-button value="done">已完成</el-radio-button>
        </el-radio-group>
        <el-button type="primary" :loading="loading" @click="load">查询</el-button>
      </div>

      <el-table :data="data.balances" v-loading="loading" border stripe size="default" :row-class-name="({ row }) => row.over_shipped > 0 ? 'danger-row' : ''">
        <el-table-column prop="company" label="公司" min-width="110" />
        <el-table-column prop="product" label="产品" min-width="120" />
        <el-table-column prop="style" label="款式" min-width="130" />
        <el-table-column label="订单" min-width="100">
          <template #default="{ row }">{{ row.order_date || row.order_ref || "—" }}</template>
        </el-table-column>
        <el-table-column prop="size" label="尺码" width="70" />
        <el-table-column prop="sku" label="SKU" min-width="110">
          <template #default="{ row }"><span class="muted">{{ row.sku || "—" }}</span></template>
        </el-table-column>
        <el-table-column prop="ordered" label="下单" width="80" align="right" />
        <el-table-column prop="shipped" label="已发" width="80" align="right" />
        <el-table-column prop="returned" label="已退" width="70" align="right">
          <template #default="{ row }"><span v-if="row.returned" style="color:#e6a23c">{{ row.returned }}</span><span v-else>—</span></template>
        </el-table-column>
        <el-table-column prop="adjusted" label="核销" width="70" align="right">
          <template #default="{ row }"><span v-if="row.adjusted" style="color:#909399">{{ row.adjusted }}</span><span v-else>—</span></template>
        </el-table-column>
        <el-table-column prop="closed" label="关闭" width="70" align="right">
          <template #default="{ row }"><span v-if="row.closed" style="color:#909399">{{ row.closed }}</span><span v-else>—</span></template>
        </el-table-column>
        <el-table-column label="还差" width="90" align="right">
          <template #default="{ row }">
            <b :class="row.remaining > 0 ? 'danger-text' : ''">{{ row.remaining }}</b>
          </template>
        </el-table-column>
        <el-table-column label="超发" width="70" align="right">
          <template #default="{ row }"><span v-if="row.over_shipped" class="danger-text">{{ row.over_shipped }}</span><span v-else>—</span></template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="$router.push(`/order-lines/${row.order_id}`)">处理</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<style>
.el-table .danger-row {
  --el-table-tr-bg-color: #fef0f0;
}
</style>
