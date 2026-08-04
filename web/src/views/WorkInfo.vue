<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { fetchOrdersOptions, fetchWorkInfo, saveWorkInfo } from "../api";

const options = ref({ companies: [], choices: {} });
const company = ref("");
const product = ref("");
const style = ref("");
const rows = ref([]);
const loading = ref(false);

onMounted(async () => {
  options.value = await fetchOrdersOptions();
});

function products() {
  return Object.keys((options.value.choices[company.value] || {}));
}

function styles() {
  return Object.keys(((options.value.choices[company.value] || {})[product.value]) || {});
}

async function load() {
  if (!company.value || !product.value || !style.value) {
    ElMessage.warning("请先选择公司、产品、款式");
    return;
  }
  loading.value = true;
  try {
    const data = await fetchWorkInfo(company.value, product.value, style.value);
    rows.value = data.rows.map((row) => ({
      section_key: row.section_key,
      section_title: row.section_title,
      content: row.content,
      photo_path: row.photo_path,
      original_name: row.original_name,
      is_custom: row.is_custom,
      file: null,
    }));
  } finally {
    loading.value = false;
  }
}

function addRow() {
  rows.value.push({
    section_key: "custom",
    section_title: "自定义信息",
    content: "",
    photo_path: "",
    original_name: "",
    is_custom: true,
    file: null,
  });
}

async function save() {
  const form = new FormData();
  form.append("company_name", company.value);
  form.append("product_name", product.value);
  form.append("style_name", style.value);
  rows.value.forEach((row) => {
    form.append("section_key", row.section_key);
    form.append("section_title", row.section_title || "自定义信息");
    form.append("content", row.content || "");
    form.append("existing_photo_path", row.photo_path || "");
    form.append("existing_original_name", row.original_name || "");
    form.append("remove_photo", row.remove_photo ? "1" : "0");
    if (row.file) {
      if (row.section_key === "accessories") form.append("photo_accessories", row.file);
      else if (row.section_key === "bag") form.append("photo_bag", row.file);
      else if (row.section_key === "wash_label") form.append("photo_wash_label", row.file);
      else if (row.section_key === "sticker") form.append("photo_sticker", row.file);
      else form.append("custom_photos", row.file);
    }
  });
  try {
    await saveWorkInfo(form);
    ElMessage.success("已保存");
    load();
  } catch (err) {
    ElMessage.error(err.message);
  }
}

function photoUrl(row) {
  return row.photo_path ? `/photos/work-info/${row.id}` : "";
}
</script>

<template>
  <div>
    <h1 class="page-title">包装/贴标信息</h1>
    <div class="section-card">
      <div class="filter-bar">
        <el-select v-model="company" filterable allow-create placeholder="公司" style="width:160px">
          <el-option v-for="c in options.companies" :key="c" :label="c" :value="c" />
        </el-select>
        <el-select v-model="product" filterable allow-create placeholder="产品" style="width:160px">
          <el-option v-for="p in products()" :key="p" :label="p" :value="p" />
        </el-select>
        <el-select v-model="style" filterable allow-create placeholder="款式" style="width:160px">
          <el-option v-for="s in styles()" :key="s" :label="s" :value="s" />
        </el-select>
        <el-button type="primary" :loading="loading" @click="load">加载</el-button>
      </div>
    </div>

    <div v-if="rows.length" class="section-card">
      <div v-for="(row, index) in rows" :key="index" class="work-info-row">
        <div style="width:180px">
          <el-input v-model="row.section_title" :readonly="!row.is_custom" placeholder="栏目名" />
        </div>
        <div style="flex:1;display:grid;gap:8px">
          <el-input v-model="row.content" type="textarea" :rows="3" :placeholder="`填写${row.section_title}`" />
          <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
            <el-image
              v-if="row.photo_path && !row.remove_photo"
              :src="photoUrl(row)"
              fit="cover"
              style="width:80px;height:80px;border-radius:6px"
            />
            <el-checkbox v-if="row.photo_path" v-model="row.remove_photo">删除这张图片</el-checkbox>
            <label class="muted" style="cursor:pointer">
              <input type="file" accept=".jpg,.jpeg,.png,.webp" @change="(e) => (row.file = e.target.files[0])" />
            </label>
          </div>
        </div>
      </div>
      <div style="display:flex;gap:10px;margin-top:14px">
        <el-button @click="addRow">新增自定义行</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.work-info-row {
  display: flex;
  gap: 14px;
  padding: 12px 0;
  border-bottom: 1px solid #f0f2f4;
}
.work-info-row:last-of-type {
  border-bottom: none;
}
</style>
