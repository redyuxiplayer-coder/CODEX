<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { fetchWaybills, updateWaybillDate, uploadWaybills } from "../api";

const data = ref({ companies: [], counts: [], photos: [] });
const loading = ref(false);
const uploadCompany = ref("");
const uploadDate = ref(new Date().toISOString().slice(0, 10));
const files = ref([]);

async function load() {
  loading.value = true;
  try {
    data.value = await fetchWaybills();
  } finally {
    loading.value = false;
  }
}

onMounted(load);

async function doUpload() {
  if (!uploadCompany.value || !files.value.length) {
    ElMessage.warning("请选择公司和面单图片");
    return;
  }
  const form = new FormData();
  form.append("company", uploadCompany.value);
  form.append("waybill_date", uploadDate.value);
  files.value.forEach((file) => form.append("files", file));
  try {
    const result = await uploadWaybills(form);
    ElMessage.success(`已上传 ${result.imported} 张，跳过 ${result.skipped} 张`);
    files.value = [];
    load();
  } catch (err) {
    ElMessage.error(err.message);
  }
}

async function saveDate(row) {
  await updateWaybillDate(row.id, row.waybill_date);
  ElMessage.success("面单日期已保存");
}
</script>

<template>
  <div v-loading="loading">
    <h1 class="page-title">快递面单</h1>
    <div class="section-card" style="max-width:640px">
      <h2>手动上传面单</h2>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
        <el-select v-model="uploadCompany" placeholder="选择公司" clearable style="width:160px">
          <el-option v-for="c in data.companies" :key="c" :label="c" :value="c" />
        </el-select>
        <el-date-picker v-model="uploadDate" type="date" value-format="YYYY-MM-DD" style="width:150px" />
        <input type="file" accept=".jpg,.jpeg,.png,.webp" multiple @change="(e) => (files = Array.from(e.target.files || []))" />
        <el-button type="primary" @click="doUpload">上传面单</el-button>
      </div>
    </div>
    <div class="section-card">
      <h2>各公司面单数量</h2>
      <el-table :data="data.counts" border size="small">
        <el-table-column prop="company" label="公司" />
        <el-table-column prop="count" label="数量" width="120" align="right" />
      </el-table>
    </div>
    <div class="section-card">
      <h2>已上传面单</h2>
      <el-table :data="data.photos" border size="small">
        <el-table-column prop="company" label="公司" width="130" />
        <el-table-column prop="display_name" label="当前显示" min-width="180" />
        <el-table-column label="面单日期" width="180">
          <template #default="{ row }">
            <el-date-picker v-model="row.waybill_date" type="date" value-format="YYYY-MM-DD" style="width:140px" @change="saveDate(row)" />
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>
