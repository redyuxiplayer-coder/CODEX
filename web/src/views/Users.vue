<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { createUser, fetchUsers, setUserPassword, updateUser } from "../api";

const data = ref({ users: [] });
const loading = ref(false);
const newForm = ref({ username: "", display_name: "", password: "" });

async function load() {
  loading.value = true;
  try {
    data.value = await fetchUsers();
  } finally {
    loading.value = false;
  }
}

onMounted(load);

async function save(row) {
  try {
    await updateUser(row.id, {
      username: row.username,
      display_name: row.display_name,
      role: row.role,
      is_active: row.is_active ? "1" : "0",
    });
    ElMessage.success("账号资料已保存");
  } catch (err) {
    ElMessage.error(err.message);
  }
}

async function changePassword(row) {
  const password = window.prompt(`给 ${row.display_name} 设置新密码`);
  if (!password) return;
  try {
    await setUserPassword(row.id, password);
    ElMessage.success("密码已修改");
  } catch (err) {
    ElMessage.error(err.message);
  }
}

async function addUser() {
  if (!newForm.value.username || !newForm.value.display_name || !newForm.value.password) {
    ElMessage.warning("请填写账号、姓名和初始密码");
    return;
  }
  try {
    await createUser({ ...newForm.value });
    ElMessage.success("账号已新增");
    newForm.value = { username: "", display_name: "", password: "" };
    load();
  } catch (err) {
    ElMessage.error(err.message);
  }
}
</script>

<template>
  <div>
    <h1 class="page-title">账号管理</h1>
    <div class="section-card">
      <el-table :data="data.users" v-loading="loading" border size="small">
        <el-table-column label="账号资料" min-width="360">
          <template #default="{ row }">
            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
              <el-input v-model="row.username" size="small" style="width:120px" placeholder="登录账号" />
              <el-input v-model="row.display_name" size="small" style="width:110px" placeholder="姓名" />
              <el-select v-model="row.role" size="small" style="width:120px">
                <el-option label="仓库员工" value="worker" />
                <el-option label="老板/管理员" value="admin" />
              </el-select>
              <el-switch v-model="row.is_active" active-text="启用" inactive-text="停用" />
              <el-button size="small" type="primary" @click="save(row)">保存资料</el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="修改密码" width="160">
          <template #default="{ row }">
            <el-button size="small" @click="changePassword(row)">修改密码</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <div class="section-card" style="max-width:640px">
      <h2>新增仓库账号</h2>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
        <el-input v-model="newForm.username" placeholder="登录账号，例如 ck02" style="width:160px" />
        <el-input v-model="newForm.display_name" placeholder="员工姓名，例如 仓库02" style="width:160px" />
        <el-input v-model="newForm.password" type="password" show-password placeholder="初始密码" style="width:150px" />
        <el-button type="primary" @click="addUser">新增账号</el-button>
      </div>
    </div>
  </div>
</template>
