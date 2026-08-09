<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { createSpu, fetchSpus, updateSpu } from "../api";

const spus = ref([]);
const q = ref("");
const loading = ref(false);
const dialog = ref(false);
const editingId = ref(null);
const form = ref({ code: "", product_name: "", style_name: "", note: "", is_active: true });

async function load() {
  loading.value = true;
  try {
    spus.value = (await fetchSpus(q.value)).spus;
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editingId.value = null;
  form.value = { code: "", product_name: "", style_name: "", note: "", is_active: true };
  dialog.value = true;
}

function openEdit(row) {
  editingId.value = row.id;
  form.value = { ...row };
  dialog.value = true;
}

async function save() {
  try {
    if (editingId.value) await updateSpu(editingId.value, form.value);
    else await createSpu(form.value);
    ElMessage.success(editingId.value ? "SPU 已更新" : "SPU 已创建");
    dialog.value = false;
    load();
  } catch (err) {
    ElMessage.error(err.message);
  }
}

onMounted(load);
</script>

<template>
  <div>
    <h1 class="page-title">内部 SPU</h1>
    <div class="section-card">
      <div class="filter-bar">
        <el-input v-model="q" placeholder="搜索 SPU、产品或款式" clearable style="width:260px" @keyup.enter="load" />
        <el-button type="primary" @click="load">查询</el-button>
        <el-button @click="openCreate">新增 SPU</el-button>
      </div>
      <el-table :data="spus" v-loading="loading" border>
        <el-table-column prop="code" label="SPU 编码" width="150" />
        <el-table-column prop="product_name" label="产品" min-width="150" />
        <el-table-column prop="style_name" label="款式" min-width="180" />
        <el-table-column prop="note" label="备注" min-width="180" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? "启用" : "停用" }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }"><el-button type="primary" link @click="openEdit(row)">编辑</el-button></template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialog" :title="editingId ? '编辑 SPU' : '新增 SPU'" width="520px">
      <el-form label-width="90px">
        <el-form-item label="SPU 编码"><el-input v-model="form.code" placeholder="留空自动生成" /></el-form-item>
        <el-form-item label="产品"><el-input v-model="form.product_name" /></el-form-item>
        <el-form-item label="款式"><el-input v-model="form.style_name" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.note" type="textarea" /></el-form-item>
        <el-form-item v-if="editingId" label="启用"><el-switch v-model="form.is_active" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialog = false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template>
    </el-dialog>
  </div>
</template>
