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
      <form method="post" action="/admin/export" target="_blank">
        <el-form label-width="90px">
          <el-form-item label="公司">
            <el-select v-model="company" name="company" style="width:100%">
              <el-option label="全部公司" value="__all__" />
              <el-option v-for="c in companies" :key="c" :label="c" :value="c" />
            </el-select>
          </el-form-item>
          <el-form-item label="导出版本">
            <el-select v-model="template" name="template" style="width:100%">
              <el-option label="客户版" value="customer" />
              <el-option label="内部版" value="internal" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" native-type="submit">导出表格</el-button>
          </el-form-item>
        </el-form>
      </form>
    </div>
  </div>
</template>
