<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { fetchSkus, importSkus, updateSku } from "../api";

const data = ref({ mappings: [] });
const q = ref("");
const loading = ref(false);
const importFile = ref(null);

async function load() {
  loading.value = true;
  try {
    data.value = await fetchSkus(q.value);
  } finally {
    loading.value = false;
  }
}

onMounted(load);

async function save(row) {
  await updateSku(row.id, {
    company_name: row.company,
    product_name: row.product,
    style_name: row.style,
    size: row.size,
    sku: row.sku,
    barcode: row.barcode,
  });
  ElMessage.success("已保存");
}

async function doImport() {
  if (!importFile.value) return;
  const form = new FormData();
  form.append("file", importFile.value);
  try {
    const result = await importSkus(form);
    ElMessage.success(`已导入 ${result.imported} 条，跳过 ${result.skipped} 条`);
    load();
  } catch (err) {
    ElMessage.error(err.message);
  }
}
</script>

<template>
  <div>
    <h1 class="page-title">SKU/条码管理</h1>
    <div class="section-card">
      <div class="filter-bar">
        <el-input v-model="q" placeholder="按公司/产品/款式/尺码/SKU/条码搜索" clearable style="width:280px" @keyup.enter="load" />
        <el-button type="primary" :loading="loading" @click="load">搜索</el-button>
      </div>
      <el-table :data="data.mappings" v-loading="loading" border size="small">
        <el-table-column prop="company" label="公司" min-width="110" />
        <el-table-column prop="product" label="产品" min-width="110" />
        <el-table-column prop="style" label="款式" min-width="120" />
        <el-table-column prop="size" label="尺码" width="80" />
        <el-table-column label="SKU" min-width="140">
          <template #default="{ row }"><el-input v-model="row.sku" size="small" placeholder="SKU" /></template>
        </el-table-column>
        <el-table-column label="条码" min-width="150">
          <template #default="{ row }"><el-input v-model="row.barcode" size="small" placeholder="条码" /></template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="save(row)">保存</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <div class="section-card" style="max-width:520px">
      <h2>导入 SKU 表</h2>
      <p class="muted">Excel 表头需要包含：公司、产品、款式、尺码、SKU。</p>
      <div style="display:flex;gap:10px;align-items:center">
        <input type="file" accept=".xlsx" @change="(e) => (importFile = e.target.files[0])" />
        <el-button type="primary" @click="doImport">导入 SKU</el-button>
      </div>
    </div>
  </div>
</template>
