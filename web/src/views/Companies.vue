<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { fetchCompanies, updateCompanyCode } from "../api";

const companies = ref([]);
const loading = ref(false);

async function load() {
  loading.value = true;
  try {
    const data = await fetchCompanies();
    companies.value = data.companies;
  } finally {
    loading.value = false;
  }
}

async function save(row) {
  try {
    const result = await updateCompanyCode(row.id, row.code);
    row.code = result.code;
    ElMessage.success("公司代码已保存");
  } catch (err) {
    ElMessage.error(err.message);
    load();
  }
}

onMounted(load);
</script>

<template>
  <div>
    <h1 class="page-title">公司代码</h1>
    <div class="section-card">
      <p class="muted">公司代码用于生成正式订单号。订单号生成后不会随公司代码修改。</p>
      <el-table :data="companies" v-loading="loading" border>
        <el-table-column prop="name" label="公司" min-width="160" />
        <el-table-column label="公司代码" min-width="180">
          <template #default="{ row }">
            <el-input v-model="row.code" maxlength="40" placeholder="例如 YXF" @change="save(row)" />
          </template>
        </el-table-column>
        <el-table-column prop="next_order_sequence" label="下一订单序号" width="140" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? "启用" : "停用" }}</el-tag></template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>
