<script setup>
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { fetchOrderLine, postForm, postFormData } from "../api";

const route = useRoute();
const router = useRouter();
const detail = ref(null);
const loading = ref(false);

const returnForm = ref({ quantity: 1, reason_type: "退回返工", reason: "", status: "pending_rework" });
const returnPhotos = ref([]);
const adjustForm = ref({ quantity: 1, reason: "盘点" });
const closeForm = ref({ quantity: 1, reason: "" });
const commentText = ref("");
const submitting = ref(false);

const ledgerLabels = { shipped: "发货", returned: "退回/返工", adjusted: "核销/调整", closed: "关闭" };
const returnStatusLabels = { pending_rework: "待返工", reworked: "已返工", scrapped: "已报废" };

async function load() {
  loading.value = true;
  try {
    detail.value = await fetchOrderLine(route.params.id);
  } catch (err) {
    ElMessage.error(err.message);
    router.replace("/orders");
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function onReturnPhotos(event) {
  returnPhotos.value = Array.from(event.target.files || []);
}

async function addReturn() {
  submitting.value = true;
  try {
    const form = new FormData();
    form.set("quantity", returnForm.value.quantity);
    form.set("reason_type", returnForm.value.reason_type);
    form.set("reason", returnForm.value.reason);
    form.set("status", returnForm.value.status);
    returnPhotos.value.forEach((file) => form.append("photos", file));
    detail.value = await postFormData(`/api/v1/order-lines/${route.params.id}/returns`, form);
    returnForm.value = { quantity: 1, reason_type: "退回返工", reason: "", status: "pending_rework" };
    returnPhotos.value = [];
    ElMessage.success("已登记退货/返工");
  } catch (err) {
    ElMessage.error(err.message);
  } finally {
    submitting.value = false;
  }
}

async function changeReturnStatus(record, status) {
  try {
    detail.value = await postForm(`/api/v1/order-lines/${route.params.id}/returns/${record.id}/status`, { status });
    ElMessage.success("状态已更新");
  } catch (err) {
    ElMessage.error(err.message);
  }
}

async function addAdjustment() {
  try {
    detail.value = await postForm(`/api/v1/order-lines/${route.params.id}/adjustments`, adjustForm.value);
    adjustForm.value = { quantity: 1, reason: "盘点" };
    ElMessage.success("已登记调整");
  } catch (err) {
    ElMessage.error(err.message);
  }
}

async function addClose() {
  try {
    detail.value = await postForm(`/api/v1/order-lines/${route.params.id}/closes`, closeForm.value);
    closeForm.value = { quantity: 1, reason: "" };
    ElMessage.success("已关闭余量");
  } catch (err) {
    ElMessage.error(err.message);
  }
}

async function addComment() {
  if (!commentText.value.trim()) return;
  try {
    detail.value = await postForm(`/api/v1/order-lines/${route.params.id}/comments`, { content: commentText.value });
    commentText.value = "";
    ElMessage.success("已添加记录");
  } catch (err) {
    ElMessage.error(err.message);
  }
}
</script>

<template>
  <div v-loading="loading">
    <template v-if="detail">
      <h1 class="page-title">
        {{ detail.order.company }} · {{ detail.order.style }} / {{ detail.order.size }}
        <el-button size="small" style="margin-left:12px" @click="router.push('/orders')">返回订单查询</el-button>
      </h1>

      <div class="section-card">
        <el-descriptions :column="4" border>
          <el-descriptions-item label="公司">{{ detail.order.company }}</el-descriptions-item>
          <el-descriptions-item label="产品">{{ detail.order.product }}</el-descriptions-item>
          <el-descriptions-item label="款式">{{ detail.order.style }}</el-descriptions-item>
          <el-descriptions-item label="尺码">{{ detail.order.size }}</el-descriptions-item>
          <el-descriptions-item label="SKU">{{ detail.order.sku || "—" }}</el-descriptions-item>
          <el-descriptions-item label="下单数量">{{ detail.order.quantity }}</el-descriptions-item>
          <el-descriptions-item label="下单日期">{{ detail.order.order_date || "—" }}</el-descriptions-item>
          <el-descriptions-item label="交期">{{ detail.order.delivery_date || "—" }}</el-descriptions-item>
          <el-descriptions-item label="订单批次">{{ detail.order.batch || "—" }}</el-descriptions-item>
          <el-descriptions-item label="备注" :span="3">{{ detail.order.note || "—" }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <div class="stat-cards">
        <div class="stat-card"><div class="label">下单</div><div class="value">{{ detail.totals.ordered }}</div></div>
        <div class="stat-card"><div class="label">已发</div><div class="value">{{ detail.totals.shipped }}</div></div>
        <div class="stat-card"><div class="label">已退/返工</div><div class="value" style="color:#e6a23c">{{ detail.totals.returned }}</div></div>
        <div class="stat-card"><div class="label">核销/调整</div><div class="value" style="color:#909399">{{ detail.totals.adjusted }}</div></div>
        <div class="stat-card"><div class="label">关闭</div><div class="value" style="color:#909399">{{ detail.totals.closed }}</div></div>
        <div class="stat-card"><div class="label">还差</div><div class="value" :style="{ color: detail.totals.over_shipped ? '#f56c6c' : '#67c23a' }">{{ detail.totals.remaining }}</div></div>
      </div>

      <div class="section-card">
        <h2>已发记录</h2>
        <el-table :data="detail.shipments" border size="small">
          <el-table-column prop="ship_date" label="发货日期" width="120" />
          <el-table-column label="类型" width="120">
            <template #default="{ row }">
              <el-tag v-if="row.bound" size="small" type="success">本单发货</el-tag>
              <el-tag v-else size="small" type="info">历史导入归入</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag size="small" type="success">{{ row.status === "auto_approved" ? "已通过" : "已修改通过" }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="quantity" label="数量" width="80" align="right" />
          <el-table-column prop="waybill_no" label="运单号" width="150">
            <template #default="{ row }"><span class="muted">{{ row.waybill_no || "—" }}</span></template>
          </el-table-column>
          <el-table-column prop="note" label="备注" />
        </el-table>
      </div>

      <div class="section-card">
        <h2>订单流水</h2>
        <el-table :data="detail.ledger" border size="small">
          <el-table-column label="时间" width="150">
            <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column label="类型" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="row.movement_type === 'shipped' ? 'success' : row.movement_type === 'returned' ? 'warning' : 'info'">
                {{ ledgerLabels[row.movement_type] || row.movement_type }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="quantity" label="数量" width="80" align="right" />
          <el-table-column prop="reason" label="原因" />
          <el-table-column prop="creator" label="操作人" width="110" />
        </el-table>
      </div>

      <div class="section-card">
        <h2>退货/返工</h2>
        <el-table v-if="detail.returns.length" :data="detail.returns" border size="small" style="margin-bottom:14px">
          <el-table-column label="时间" width="150">
            <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="quantity" label="数量" width="70" align="right" />
          <el-table-column prop="reason_type" label="类型" width="110" />
          <el-table-column prop="reason" label="原因" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 'scrapped' ? 'danger' : row.status === 'reworked' ? 'success' : 'warning'">
                {{ returnStatusLabels[row.status] || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="照片" width="150">
            <template #default="{ row }">
              <el-image
                v-for="p in row.photos"
                :key="p.id"
                :src="`/photos/return/${p.id}?thumb=1`"
                :preview-src-list="[`/photos/return/${p.id}`]"
                preview-teleported
                fit="cover"
                style="width:42px;height:42px;margin-right:6px;border-radius:4px"
              />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <template v-if="row.status !== 'scrapped'">
                <el-select v-model="row.status" size="small" style="width:88px" @change="changeReturnStatus(row, row.status)">
                  <el-option label="待返工" value="pending_rework" />
                  <el-option label="已返工" value="reworked" />
                  <el-option label="报废" value="scrapped" />
                </el-select>
              </template>
              <span v-else class="muted">已报废</span>
            </template>
          </el-table-column>
        </el-table>
        <p v-else class="muted" style="margin:0 0 14px">还没有退货/返工记录。</p>

        <el-form inline>
          <el-form-item label="数量">
            <el-input-number v-model="returnForm.quantity" :min="1" />
          </el-form-item>
          <el-form-item label="类型">
            <el-select v-model="returnForm.reason_type" style="width:130px">
              <el-option label="退回返工" value="退回返工" />
              <el-option label="质量问题" value="质量问题" />
              <el-option label="其他" value="其他" />
            </el-select>
          </el-form-item>
          <el-form-item label="原因">
            <el-input v-model="returnForm.reason" placeholder="例如：线头未剪" style="width:220px" />
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="returnForm.status" style="width:110px">
              <el-option label="待返工" value="pending_rework" />
              <el-option label="已返工" value="reworked" />
              <el-option label="报废" value="scrapped" />
            </el-select>
          </el-form-item>
          <el-form-item label="照片">
            <input type="file" multiple accept=".jpg,.jpeg,.png,.webp" @change="onReturnPhotos" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="submitting" @click="addReturn">登记退货/返工</el-button>
          </el-form-item>
        </el-form>
      </div>

      <div class="section-card">
        <h2>盘点/调整</h2>
        <el-table v-if="detail.adjustments.length" :data="detail.adjustments" border size="small" style="margin-bottom:14px">
          <el-table-column label="时间" width="150">
            <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="quantity" label="数量" width="80" align="right" />
          <el-table-column prop="reason" label="原因" />
          <el-table-column prop="creator" label="操作人" width="110" />
        </el-table>
        <p v-else class="muted" style="margin:0 0 14px">还没有调整记录。</p>
        <el-form inline>
          <el-form-item label="数量">
            <el-input-number v-model="adjustForm.quantity" />
          </el-form-item>
          <el-form-item label="原因">
            <el-select v-model="adjustForm.reason" style="width:150px">
              <el-option label="盘点" value="盘点" />
              <el-option label="少发核销" value="少发核销" />
              <el-option label="超发核销" value="超发核销" />
              <el-option label="报废" value="报废" />
              <el-option label="其他" value="其他" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="addAdjustment">登记调整</el-button>
          </el-form-item>
        </el-form>
      </div>

      <div class="section-card">
        <h2>关闭（客户不再要）</h2>
        <el-table v-if="detail.closes.length" :data="detail.closes" border size="small" style="margin-bottom:14px">
          <el-table-column label="时间" width="150">
            <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="quantity" label="数量" width="80" align="right" />
          <el-table-column prop="reason" label="原因" />
          <el-table-column prop="creator" label="操作人" width="110" />
        </el-table>
        <p v-else class="muted" style="margin:0 0 14px">还没有关闭记录。</p>
        <el-form inline>
          <el-form-item label="数量">
            <el-input-number v-model="closeForm.quantity" :min="1" />
          </el-form-item>
          <el-form-item label="原因">
            <el-input v-model="closeForm.reason" placeholder="例如：客户说不要了" style="width:220px" />
          </el-form-item>
          <el-form-item>
            <el-button type="danger" plain @click="addClose">关闭余量</el-button>
          </el-form-item>
        </el-form>
      </div>

      <div class="section-card">
        <h2>沟通记录</h2>
        <el-table v-if="detail.comments.length" :data="detail.comments" border size="small" style="margin-bottom:14px">
          <el-table-column label="时间" width="150">
            <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="user" label="人" width="110" />
          <el-table-column prop="content" label="内容" />
        </el-table>
        <p v-else class="muted" style="margin:0 0 14px">还没有沟通记录。</p>
        <el-input v-model="commentText" type="textarea" :rows="2" placeholder="例如：客户说这单先不补了" style="margin-bottom:10px" />
        <el-button type="primary" @click="addComment">添加记录</el-button>
      </div>
    </template>
  </div>
</template>
