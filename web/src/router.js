import { createRouter, createWebHashHistory } from "vue-router";
import Dashboard from "./views/Dashboard.vue";
import Login from "./views/Login.vue";
import NewOrder from "./views/NewOrder.vue";
import Orders from "./views/Orders.vue";
import OrderLine from "./views/OrderLine.vue";
import Review from "./views/Review.vue";
import Shipments from "./views/Shipments.vue";
import Skus from "./views/Skus.vue";
import DailyStats from "./views/DailyStats.vue";
import Export from "./views/Export.vue";
import Goals from "./views/Goals.vue";
import Users from "./views/Users.vue";
import Logs from "./views/Logs.vue";
import Waybills from "./views/Waybills.vue";
import WorkInfo from "./views/WorkInfo.vue";

const routes = [
  { path: "/", redirect: "/dashboard" },
  { path: "/login", component: Login },
  { path: "/dashboard", component: Dashboard },
  { path: "/orders", component: Orders },
  { path: "/order-lines/:id", component: OrderLine, props: true },
  { path: "/orders/new", component: NewOrder },
  { path: "/review", component: Review },
  { path: "/shipments", component: Shipments },
  { path: "/skus", component: Skus },
  { path: "/daily-stats", component: DailyStats },
  { path: "/export", component: Export },
  { path: "/goals", component: Goals },
  { path: "/users", component: Users },
  { path: "/logs", component: Logs },
  { path: "/waybills", component: Waybills },
  { path: "/work-info", component: WorkInfo },
];

export default createRouter({
  history: createWebHashHistory(),
  routes,
});
