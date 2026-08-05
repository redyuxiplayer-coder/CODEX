<script setup>
import { onMounted, ref } from "vue";
import { fetchBalances } from "../api";

const companies = ref([]);
const company = ref("__all__");
const template = ref("customer");

onMounted(async () => {
  const data = await fetchBalances();
  companies.value = data.companies;
});
</script>

<template>
  <div>
    <h1 class="page-title">导出 Excel</h1>
    <div class="section-card" style="max-width:520px">
      <form method="post" action="/admin/export" class="export-form">
        <label class="muted">公司</label>
        <select name="company" v-model="company">
          <option value="__all__">全部公司</option>
          <option v-for="c in companies" :key="c" :value="c">{{ c }}</option>
        </select>
        <label class="muted">导出版本</label>
        <select name="template" v-model="template">
          <option value="customer">客户版</option>
          <option value="internal">内部版</option>
        </select>
        <button type="submit">导出表格</button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.export-form {
  display: grid;
  gap: 10px;
  max-width: 420px;
}
.export-form select {
  padding: 10px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 15px;
  background: #fafbfc;
}
.export-form button {
  margin-top: 6px;
  padding: 11px 14px;
  border: none;
  border-radius: 8px;
  background: #2563eb;
  color: #fff;
  font-size: 15px;
  cursor: pointer;
}
</style>
