<script setup>
import { onMounted, ref } from "vue";
import { fetchLogs } from "../api";

const data = ref({ logs: [] });
const loading = ref(false);

onMounted(async () => {
  loading.value = true;
  try {
    data.value = await fetchLogs();
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div>
    <h1 class="page-title">操作日志</h1>
    <div class="section-card">
      <el-table :data="data.logs" v-loading="loading" border size="small">
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column prop="actor" label="操作人" width="100" />
        <el-table-column prop="action" label="动作" width="170" />
        <el-table-column prop="target" label="对象" width="140" />
        <el-table-column prop="detail" label="详情" min-width="220" />
      </el-table>
    </div>
  </div>
</template>
