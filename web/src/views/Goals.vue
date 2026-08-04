<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { fetchGoals, saveGoals } from "../api";

const goalDate = ref(new Date().toISOString().slice(0, 10));
const goalText = ref("");
const loading = ref(false);

async function load() {
  loading.value = true;
  try {
    const data = await fetchGoals(goalDate.value);
    goalText.value = data.goal_text;
  } finally {
    loading.value = false;
  }
}

onMounted(load);

async function save() {
  await saveGoals(goalDate.value, goalText.value);
  ElMessage.success("今日目标已保存");
}
</script>

<template>
  <div>
    <h1 class="page-title">今日目标</h1>
    <div class="section-card" style="max-width:640px">
      <div class="filter-bar">
        <el-date-picker v-model="goalDate" type="date" value-format="YYYY-MM-DD" style="width:160px" @change="load" />
        <el-button type="primary" :loading="loading" @click="load">查看日期</el-button>
      </div>
      <el-form label-position="top">
        <el-form-item label="当日优先完成目标（一行一个）">
          <el-input v-model="goalText" type="textarea" :rows="10" placeholder="优先完成福建小偷女款&#10;源兴发小红帽先补 M/L&#10;张鹏囚服今天清点" />
        </el-form-item>
        <el-button type="primary" @click="save">保存今日目标</el-button>
      </el-form>
    </div>
  </div>
</template>
