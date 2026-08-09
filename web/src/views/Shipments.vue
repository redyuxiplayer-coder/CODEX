<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { fetchShipments, updateShipmentWaybill, uploadShipmentPhotos } from "../api";

const data = ref({ reports: [], companies: [], page: 1, total_pages: 1, total: 0 });
const company = ref("");
const waybill = ref("");
const page = ref(1);
const loading = ref(false);

const statusLabels = { pending_review: "待审核", auto_approved: "已通过", approved_after_edit: "已修改通过", rejected: "已驳回" };

async function load() {
  loading.value = true;
  try {
    data.value = await fetchShipments({ company: company.value, waybill: waybill.value, page: page.value });
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function changePage(next) {
  page.value = next;
  load();
}

async function saveWaybill(row) {
  await updateShipmentWaybill(row.id, row.waybill_no);
  ElMessage.success("运单号已保存");
}

async function uploadPhotos(row, event) {
  const files = Array.from(event.target.files || []);
  if (!files.length) return;
  const form = new FormData();
  files.forEach((file) => form.append("photos", file));
  try {
    const result = await uploadShipmentPhotos(row.id, form);
    ElMessage.success(`已上传 ${result.uploaded} 张`);
    load();
  } catch (err) {
    ElMessage.error(err.message);
  }
  event.target.value = "";
}
</script>

<template>
  <div>
    <h1 class="page-title">发货明细</h1>
    <div class="section-card">
      <div class="filter-bar">
        <el-select v-model="company" placeholder="全部公司" clearable style="width:180px" @change="page = 1; load()">
          <el-option v-for="c in data.companies" :key="c" :label="c" :value="c" />
        </el-select>
        <el-input v-model="waybill" placeholder="运单号搜索" clearable style="width:200px" @keyup.enter="page = 1; load()" />
        <el-button type="primary" :loading="loading" @click="page = 1; load()">查询</el-button>
      </div>

      <el-table :data="data.reports" v-loading="loading" border size="small">
        <el-table-column prop="ship_date" label="日期" width="105" />
        <el-table-column label="时间" width="100">
          <template #default="{ row }">{{ new Date(row.created_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) }}</template>
        </el-table-column>
        <el-table-column prop="user" label="员工" width="85" />
        <el-table-column label="订单" min-width="180">
          <template #default="{ row }">
            <b>{{ row.system_order_no || "历史未绑定" }}</b>
            <div class="muted" v-if="row.order_date">下单 {{ row.order_date }}</div>
            <div class="muted" v-if="row.customer_order_no">客户单号 {{ row.customer_order_no }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="company" label="公司" width="105" />
        <el-table-column prop="product" label="产品" min-width="100" />
        <el-table-column label="款式/颜色" min-width="130">
          <template #default="{ row }">{{ row.style }}<div class="muted" v-if="row.color_name">{{ row.color_name }} · {{ row.spu_code }}</div></template>
        </el-table-column>
        <el-table-column label="尺码数量/客户SKU" min-width="170">
          <template #default="{ row }">
            <div v-for="l in row.lines" :key="`${l.size}-${l.system_order_no}`">
              {{ l.size }} {{ l.quantity }}<span class="muted" v-if="l.customer_sku"> · {{ l.customer_sku }}</span>
              <div class="muted" v-if="row.has_multiple_orders && l.system_order_no">{{ l.system_order_no }} · 下单 {{ l.order_date }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="运单号" width="150">
          <template #default="{ row }">
            <el-input v-model="row.waybill_no" size="small" placeholder="运单号" style="width:110px" @change="saveWaybill(row)" />
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'pending_review' ? 'warning' : row.status === 'rejected' ? 'danger' : 'success'">
              {{ statusLabels[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="review_reason" label="原因/处理" min-width="140" />
        <el-table-column label="照片" width="160">
          <template #default="{ row }">
            <div v-if="row.photos.length" style="display:flex;gap:3px;flex-wrap:wrap">
              <el-image
                v-for="p in row.photos"
                :key="p.id"
                :src="`/photos/shipment/${p.id}?thumb=1`"
                :preview-src-list="[`/photos/shipment/${p.id}`]"
                preview-teleported
                fit="cover"
                style="width:34px;height:34px;border-radius:4px"
              />
            </div>
            <span v-else class="muted">0 张</span>
            <div style="margin-top:4px">
              <input type="file" accept=".jpg,.jpeg,.png,.webp" multiple style="font-size:12px;width:150px" @change="uploadPhotos(row, $event)" />
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="120" />
      </el-table>

      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:14px">
        <span class="muted">共 {{ data.total }} 条，第 {{ data.page }} / {{ data.total_pages }} 页</span>
        <div>
          <el-button size="small" :disabled="data.page <= 1" @click="changePage(data.page - 1)">上一页</el-button>
          <el-button size="small" :disabled="data.page >= data.total_pages" @click="changePage(data.page + 1)">下一页</el-button>
        </div>
      </div>
    </div>
  </div>
</template>
