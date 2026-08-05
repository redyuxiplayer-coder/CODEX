<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  createLogistics,
  deleteLogistics,
  fetchLogistics,
  fetchLogisticsCandidates,
  fetchLogisticsDetail,
  linkLogisticsReports,
  unlinkLogisticsReport,
  updateLogistics,
} from "../api";

const records = ref([]);
const loading = ref(false);
const filterCompany = ref("");
const filterDate = ref("");

const formDialog = ref(false);
const editing = ref(false);
const editingId = ref(null);
const form = ref({ company_name: "", ship_date: "", waybill_no: "", weight_kg: "", package_count: "", note: "" });
const saving = ref(false);

const detailDialog = ref(false);
const detail = ref(null);
const candidates = ref([]);
const selectedCandidates = ref([]);

async function load() {
  loading.value = true;
  try {
    records.value = (await fetchLogistics({ company: filterCompany.value, ship_date: filterDate.value })).records;
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function openCreate() {
  editing.value = false;
  editingId.value = null;
  form.value = { company_name: filterCompany.value || "", ship_date: new Date().toISOString().slice(0, 10), waybill_no: "", weight_kg: "", package_count: "", note: "" };
  formDialog.value = true;
}

async function openEdit(record) {
  editing.value = true;
  editingId.value = record.id;
  form.value = {
    company_name: record.company_name,
    ship_date: record.ship_date,
    waybill_no: record.waybill_no,
    weight_kg: record.weight_kg,
    package_count: record.package_count,
    note: record.note,
  };
  formDialog.value = true;
}

async function save() {
  if (!form.value.company_name || !form.value.ship_date || !form.value.waybill_no) {
    ElMessage.warning("请填写公司、发货日期和快递单号");
    return;
  }
  saving.value = true;
  try {
    if (editing.value) {
      await updateLogistics(editingId.value, { ...form.value, weight_kg: form.value.weight_kg || 0, package_count: form.value.package_count || 0 });
      ElMessage.success("快递单已更新");
    } else {
      await createLogistics({ ...form.value, weight_kg: form.value.weight_kg || 0, package_count: form.value.package_count || 0 });
      ElMessage.success("快递单已保存");
    }
    formDialog.value = false;
    load();
  } catch (err) {
    ElMessage.error(err.message);
  } finally {
    saving.value = false;
  }
}

async function remove(record) {
  try {
    await ElMessageBox.confirm(`确认删除快递单 ${record.waybill_no}？已关联的发货会解除关联。`, "删除", { type: "warning" });
  } catch (_) {
    return;
  }
  try {
    await deleteLogistics(record.id);
    ElMessage.success("已删除");
    load();
  } catch (err) {
    ElMessage.error(err.message);
  }
}

async function openDetail(record) {
  detailDialog.value = true;
  detail.value = await fetchLogisticsDetail(record.id);
  await loadCandidates();
}

async function loadCandidates() {
  if (!detail.value) return;
  candidates.value = (await fetchLogisticsCandidates(detail.value.company_name, detail.value.ship_date)).reports;
  selectedCandidates.value = [];
}

async function addCandidates() {
  if (!selectedCandidates.value.length) {
    ElMessage.warning("请先勾选要加入的发货明细");
    return;
  }
  try {
    detail.value = await linkLogisticsReports(detail.value.id, selectedCandidates.value);
    ElMessage.success("已加入快递单");
    loadCandidates();
    load();
  } catch (err) {
    ElMessage.error(err.message);
  }
}

async function removeReport(report) {
  try {
    detail.value = await unlinkLogisticsReport(detail.value.id, report.id);
    ElMessage.success("已移除");
    loadCandidates();
    load();
  } catch (err) {
    ElMessage.error(err.message);
  }
}

function reportLineText(report) {
  return report.lines.map((line) => `${line.size} ${line.quantity}`).join("、");
}

function reportQty(report) {
  return report.lines.reduce((sum, line) => sum + line.quantity, 0);
}
</script>

<template>
  <div>
    <h1 class="page-title">快递记录</h1>

    <div class="section-card">
      <div class="filter-bar">
        <el-input v-model="filterCompany" placeholder="公司筛选" clearable style="width:180px" @keyup.enter="load" />
        <el-date-picker v-model="filterDate" type="date" value-format="YYYY-MM-DD" placeholder="日期筛选" style="width:160px" @change="load" />
        <el-button type="primary" :loading="loading" @click="load">查询</el-button>
        <el-button type="primary" plain @click="openCreate">新增快递单</el-button>
      </div>

      <el-table :data="records" v-loading="loading" border size="small">
        <el-table-column prop="ship_date" label="发货日期" width="110" />
        <el-table-column prop="company_name" label="公司" width="130" />
        <el-table-column prop="waybill_no" label="快递单号" min-width="150" />
        <el-table-column label="重量(kg)" width="100" align="right">
          <template #default="{ row }">{{ row.weight_kg }}</template>
        </el-table-column>
        <el-table-column label="件数" width="80" align="right">
          <template #default="{ row }">{{ row.package_count }}</template>
        </el-table-column>
        <el-table-column label="关联发货" width="130" align="right">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ row.linked_count }} 笔 / {{ row.linked_qty }} 件</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="120" />
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="openDetail(row)">查看</el-button>
            <el-button size="small" link @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" link @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="formDialog" :title="editing ? '编辑快递单' : '新增快递单'" width="520px">
      <el-form label-width="90px">
        <el-form-item label="公司">
          <el-input v-model="form.company_name" placeholder="例如 广东茉莉" />
        </el-form-item>
        <el-form-item label="发货日期">
          <el-date-picker v-model="form.ship_date" type="date" value-format="YYYY-MM-DD" style="width:100%" />
        </el-form-item>
        <el-form-item label="快递单号">
          <el-input v-model="form.waybill_no" placeholder="例如 800209579798" />
        </el-form-item>
        <el-form-item label="重量(kg)">
          <el-input-number v-model="form.weight_kg" :min="0" :precision="1" :step="0.1" style="width:100%" />
        </el-form-item>
        <el-form-item label="件数">
          <el-input-number v-model="form.package_count" :min="0" style="width:100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailDialog" :title="`快递单 ${detail ? detail.waybill_no : ''}`" width="860px" top="5vh">
      <template v-if="detail">
        <div class="stat-cards" style="margin-bottom:14px">
          <div class="stat-card"><div class="label">公司</div><div class="value" style="font-size:18px">{{ detail.company_name }}</div></div>
          <div class="stat-card"><div class="label">发货日期</div><div class="value" style="font-size:18px">{{ detail.ship_date }}</div></div>
          <div class="stat-card"><div class="label">重量</div><div class="value" style="font-size:18px">{{ detail.weight_kg }} kg</div></div>
          <div class="stat-card"><div class="label">件数</div><div class="value" style="font-size:18px">{{ detail.package_count }} 包</div></div>
          <div class="stat-card"><div class="label">关联发货</div><div class="value" style="font-size:18px">{{ detail.linked_count }} 笔 / {{ detail.linked_qty }} 件</div></div>
        </div>

        <h2 style="margin:0 0 10px;font-size:15px">这笔快递装的货</h2>
        <el-table :data="detail.reports" border size="small" max-height="280">
          <el-table-column prop="ship_date" label="发货日期" width="110" />
          <el-table-column prop="company" label="公司" width="120" />
          <el-table-column prop="style" label="款式" min-width="150" />
          <el-table-column label="尺码数量" min-width="140">
            <template #default="{ row }">{{ reportLineText(row) }}</template>
          </el-table-column>
          <el-table-column label="数量" width="90" align="right">
            <template #default="{ row }"><b>{{ reportQty(row) }}</b></template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
              <el-button size="small" type="danger" link @click="removeReport(row)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <p class="muted" v-if="!detail.reports.length" style="margin:10px 0">还没有关联发货明细。</p>

        <div style="border-top:1px solid #f0f2f4;margin-top:14px;padding-top:14px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <b style="font-size:14px">添加更多发货（{{ detail.company_name }} · {{ detail.ship_date }} 未关联的）</b>
            <el-button size="small" type="primary" @click="loadCandidates">刷新</el-button>
          </div>
          <el-table :data="candidates" border size="small" max-height="220" @selection-change="(rows) => (selectedCandidates = rows.map((r) => r.id))">
            <el-table-column type="selection" width="45" />
            <el-table-column prop="style" label="款式" min-width="150" />
            <el-table-column label="尺码数量" min-width="140">
              <template #default="{ row }">{{ reportLineText(row) }}</template>
            </el-table-column>
            <el-table-column label="数量" width="90" align="right">
              <template #default="{ row }">{{ reportQty(row) }}</template>
            </el-table-column>
          </el-table>
          <el-button size="small" type="primary" style="margin-top:10px" @click="addCandidates">加入这笔快递</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>
