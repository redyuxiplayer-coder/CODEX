<script setup>
import { onMounted, ref } from "vue";
import { fetchDashboard } from "../api";

const data = ref(null);
const loading = ref(false);

const statusLabels = {
  pending_review: "待审核",
  auto_approved: "已通过",
  approved_after_edit: "已修改通过",
  rejected: "已驳回",
};

async function load() {
  loading.value = true;
  try {
    data.value = await fetchDashboard();
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div v-loading="loading">
    <h1 class="page-title">首页</h1>
    <template v-if="data">
      <div class="stat-cards">
        <div class="stat-card"><div class="label">今日已通过发货</div><div class="value">{{ data.today_total }}</div></div>
        <div class="stat-card"><div class="label">待审核</div><div class="value" style="color:#e6a23c">{{ data.pending }}</div></div>
        <div class="stat-card"><div class="label">未发合计</div><div class="value">{{ data.unshipped_total }}</div></div>
        <div class="stat-card"><div class="label">超发合计</div><div class="value" style="color:#ef4444">{{ data.over_total }}</div></div>
      </div>

      <div class="section-card">
        <h2>最近上报</h2>
        <el-table :data="data.recent" border size="small">
          <el-table-column prop="ship_date" label="日期" width="110" />
          <el-table-column label="时间" width="110">
            <template #default="{ row }">{{ new Date(row.created_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) }}</template>
          </el-table-column>
          <el-table-column prop="user" label="员工" width="100" />
          <el-table-column prop="company" label="公司" width="120" />
          <el-table-column prop="style" label="款式" min-width="130" />
          <el-table-column label="数量" width="80" align="right">
            <template #default="{ row }">{{ row.lines.reduce((s, l) => s + l.quantity, 0) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 'pending_review' ? 'warning' : row.status === 'rejected' ? 'danger' : 'success'">
                {{ statusLabels[row.status] || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="review_reason" label="原因" min-width="160" />
        </el-table>
      </div>
    </template>
  </div>
</template>
