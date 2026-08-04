<script setup>
import { onMounted, ref } from "vue";
import { fetchDailyStats } from "../api";

const shipDate = ref(new Date().toISOString().slice(0, 10));
const data = ref({ rows: [], total: 0 });
const loading = ref(false);

async function load() {
  loading.value = true;
  try {
    data.value = await fetchDailyStats(shipDate.value);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div>
    <h1 class="page-title">每日发货统计</h1>
    <div class="section-card">
      <div class="filter-bar">
        <el-date-picker v-model="shipDate" type="date" value-format="YYYY-MM-DD" style="width:160px" @change="load" />
        <el-button type="primary" :loading="loading" @click="load">查询</el-button>
      </div>
      <div class="stat-cards">
        <div class="stat-card"><div class="label">当天已通过发货</div><div class="value">{{ data.total }}</div></div>
      </div>
      <el-table :data="data.rows" v-loading="loading" border size="small">
        <el-table-column prop="company" label="公司" min-width="110" />
        <el-table-column prop="product" label="产品" min-width="110" />
        <el-table-column prop="style" label="款式" min-width="120" />
        <el-table-column prop="size" label="尺码" width="90" />
        <el-table-column prop="quantity" label="数量" width="100" align="right" />
      </el-table>
    </div>
  </div>
</template>
