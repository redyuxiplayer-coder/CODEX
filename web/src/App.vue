<script setup>
import { onMounted } from "vue";
import { useRouter } from "vue-router";
import { me, logout } from "./api";
import { ready, user } from "./store";

const router = useRouter();

onMounted(async () => {
  try {
    user.value = await me();
  } catch (_) {
    user.value = null;
  }
  ready.value = true;
  if (!user.value) router.replace("/login");
});

async function doLogout() {
  try {
    await logout();
  } catch (_) {
    // 即使登出接口失败也继续
  }
  user.value = null;
  router.replace("/login");
}
</script>

<template>
  <div v-if="!ready" class="boot">加载中...</div>
  <router-view v-else-if="!user" />
  <div v-else class="app-shell">
    <header class="topbar">
      <div class="brand">ZY服装发货管理系统</div>
      <nav>
        <router-link to="/dashboard">首页</router-link>
        <router-link to="/orders/new">新增订单</router-link>
        <router-link to="/sales-orders">正式订单</router-link>
        <router-link to="/orders">订单余额</router-link>
        <router-link to="/companies">公司代码</router-link>
        <router-link to="/spus">内部 SPU</router-link>
        <router-link to="/review">待审核</router-link>
        <router-link to="/shipments">发货明细</router-link>
        <router-link to="/daily-stats">每日统计</router-link>
        <router-link to="/logistics">快递记录</router-link>
        <router-link to="/skus">SKU/条码</router-link>
        <router-link to="/work-info">作业信息</router-link>
        <router-link to="/export">导出</router-link>
        <router-link to="/goals">今日目标</router-link>
        <router-link to="/users">账号管理</router-link>
        <router-link to="/logs">操作日志</router-link>
        <span class="user">{{ user.display_name }}</span>
        <el-button size="small" @click="doLogout">退出</el-button>
      </nav>
    </header>
    <main class="page">
      <router-view />
    </main>
  </div>
</template>
