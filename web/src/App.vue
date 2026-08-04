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
        <router-link to="/orders">订单查询</router-link>
        <a href="/admin/orders/new" target="_blank">新增订单</a>
        <a href="/admin/review" target="_blank">待审核</a>
        <a href="/admin/shipments" target="_blank">发货明细</a>
        <a href="/admin/skus" target="_blank">SKU/条码</a>
        <span class="user">{{ user.display_name }}</span>
        <el-button size="small" @click="doLogout">退出</el-button>
      </nav>
    </header>
    <main class="page">
      <router-view />
    </main>
  </div>
</template>
