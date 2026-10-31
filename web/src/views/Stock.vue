<script setup>
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { addStockIn, createStockItem, fetchStock, setStockCount } from "../api";

const items = ref([]);
const spus = ref([]);
const movements = ref([]);
const query = ref("");
const loading = ref(false);
const savingId = ref(null);
const edits = reactive({});
const createDialog = ref(false);
const creating = ref(false);
const newItem = reactive({ spu_id: null, color_name: "", color_code: "", size: "" });

function prepareEdits() {
  for (const item of items.value) {
    if (!edits[item.id]) edits[item.id] = { count: item.quantity, countReason: "", inbound: null, inboundReason: "" };
    edits[item.id].count = item.quantity;
  }
}

async function load() {
  loading.value = true;
  try {
    const data = await fetchStock(query.value.trim());
    items.value = data.items;
    spus.value = data.spus;
    movements.value = data.movements;
    prepareEdits();
  } catch (err) {
    ElMessage.error(err.message);
  } finally {
    loading.value = false;
  }
}

async function saveCount(item) {
  savingId.value = `count-${item.id}`;
  try {
    await setStockCount(item.id, edits[item.id].count, edits[item.id].countReason);
    ElMessage.success("盘点已保存");
    await load();
  } catch (err) {
    ElMessage.error(err.message);
  } finally {
    savingId.value = null;
  }
}

async function saveInbound(item) {
  const edit = edits[item.id];
  if (!edit.inbound || edit.inbound < 1) {
    ElMessage.warning("入库数量必须大于 0");
    return;
  }
  savingId.value = `in-${item.id}`;
  try {
    await addStockIn(item.id, edit.inbound, edit.inboundReason);
    ElMessage.success("入库已记录");
    edit.inbound = null;
    edit.inboundReason = "";
    await load();
  } catch (err) {
    ElMessage.error(err.message);
  } finally {
    savingId.value = null;
  }
}

function openCreate() {
  Object.assign(newItem, { spu_id: null, color_name: "", color_code: "", size: "" });
  createDialog.value = true;
}

async function createItem() {
  if (!newItem.spu_id) {
    ElMessage.warning("请选择款式");
    return;
  }
  creating.value = true;
  try {
    await createStockItem({ ...newItem });
    ElMessage.success("已新增库存行");
    createDialog.value = false;
    await load();
  } catch (err) {
    ElMessage.error(err.message);
  } finally {
    creating.value = false;
  }
}

function movementName(type) {
  return { count: "盘点", in: "入库", out: "出库" }[type] || type;
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
}

onMounted(load);
</script>

<template>
  <div>
    <div class="filter-bar">
      <h1 class="page-title" style="margin:0">本地库存</h1>
      <el-input v-model="query" clearable placeholder="按产品、款式、颜色或尺码搜索" style="width:320px" @keyup.enter="load" @clear="load" />
      <el-button type="primary" :loading="loading" @click="load">查询</el-button>
      <el-button type="primary" plain @click="openCreate">新增库存行</el-button>
    </div>

    <el-alert title="“盘点”把数量直接改成实际数；“入库”在现有数量上增加。每次改动都会记录流水。" type="info" :closable="false" show-icon style="margin:14px 0" />

    <div class="section-card">
      <el-table :data="items" v-loading="loading" border>
        <el-table-column prop="product_name" label="产品" min-width="140" />
        <el-table-column prop="style_name" label="款式" min-width="150" />
        <el-table-column prop="color_name" label="颜色" width="100"><template #default="{ row }">{{ row.color_name || "—" }}</template></el-table-column>
        <el-table-column prop="size" label="尺码" width="100"><template #default="{ row }">{{ row.size || "—" }}</template></el-table-column>
        <el-table-column label="现有" width="85" align="right"><template #default="{ row }"><el-tag :type="row.quantity <= 10 ? 'warning' : 'success'">{{ row.quantity }}</el-tag></template></el-table-column>
        <el-table-column label="盘点成" min-width="275">
          <template #default="{ row }">
            <div class="stock-action">
              <el-input-number v-model="edits[row.id].count" :min="0" controls-position="right" style="width:105px" />
              <el-input v-model="edits[row.id].countReason" placeholder="原因（可空）" />
              <el-button type="primary" :loading="savingId === `count-${row.id}`" @click="saveCount(row)">盘点</el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="入库" min-width="285">
          <template #default="{ row }">
            <div class="stock-action">
              <el-input-number v-model="edits[row.id].inbound" :min="1" controls-position="right" placeholder="件数" style="width:105px" />
              <el-input v-model="edits[row.id].inboundReason" placeholder="来源（可空）" />
              <el-button type="success" :loading="savingId === `in-${row.id}`" @click="saveInbound(row)">入库</el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="165"><template #default="{ row }">{{ formatTime(row.updated_at) }}</template></el-table-column>
        <template #empty>还没有库存记录，请先新增库存行。</template>
      </el-table>
    </div>

    <div class="section-card" style="margin-top:16px">
      <h2 style="margin:0 0 12px;font-size:18px">最近 30 笔变动</h2>
      <el-table :data="movements" border size="small">
        <el-table-column label="时间" width="175"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column>
        <el-table-column prop="item_label" label="库存项" min-width="260" />
        <el-table-column label="类型" width="90"><template #default="{ row }">{{ movementName(row.movement_type) }}</template></el-table-column>
        <el-table-column label="变动" width="90" align="right"><template #default="{ row }">{{ row.quantity_delta > 0 ? "+" : "" }}{{ row.quantity_delta }}</template></el-table-column>
        <el-table-column prop="quantity_after" label="变动后" width="90" align="right" />
        <el-table-column prop="reason" label="原因" min-width="160"><template #default="{ row }">{{ row.reason || "—" }}</template></el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="createDialog" title="新增库存行" width="520px">
      <el-form label-width="80px">
        <el-form-item label="款式">
          <el-select v-model="newItem.spu_id" filterable placeholder="选择款式" style="width:100%">
            <el-option v-for="spu in spus" :key="spu.id" :label="`${spu.code} · ${spu.product_name} · ${spu.style_name}`" :value="spu.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="颜色"><el-input v-model="newItem.color_name" placeholder="例如 粉色" /></el-form-item>
        <el-form-item label="颜色码"><el-input v-model="newItem.color_code" placeholder="例如 PINK，可空" /></el-form-item>
        <el-form-item label="尺码"><el-input v-model="newItem.size" placeholder="例如 5-7Y / 不分尺码" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createItem">新增</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.stock-action { display: flex; align-items: center; gap: 8px; }
</style>
