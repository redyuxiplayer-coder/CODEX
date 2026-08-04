import { createRouter, createWebHashHistory } from "vue-router";
import Login from "./views/Login.vue";
import Orders from "./views/Orders.vue";
import OrderLine from "./views/OrderLine.vue";

const routes = [
  { path: "/", redirect: "/orders" },
  { path: "/login", component: Login },
  { path: "/orders", component: Orders },
  { path: "/order-lines/:id", component: OrderLine, props: true },
];

export default createRouter({
  history: createWebHashHistory(),
  routes,
});
