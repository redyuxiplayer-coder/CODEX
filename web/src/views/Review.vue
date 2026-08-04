<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { fetchReviewPending, reviewApprove, reviewReject, workInfoProposalApprove, workInfoProposalReject } from "../api";

const data = ref({ reports: [], work_info_proposals: [] });
const loading = ref(false);
const note = ref("");

async function load() {
  loading.value = true;
  try {
    data.value = await fetchReviewPending();
  } finally {
    loading.value = false;
  }
}

onMounted(load);

async function approve(reportId) {
  await reviewApprove(reportId, note.value);
  note.value = "";
  ElMessage.success("已通过");
  load();
}

async function reject(reportId) {
  const reason = window.prompt("驳回原因（可选）");
  if (reason === null) return;
  await reviewReject(reportId, reason);
  ElMessage.success("已驳回");
  load();
}

async function approveProposal(proposalId) {
  await workInfoProposalApprove(proposalId, note.value);
  ElMessage.success("作业信息已通过并生效");
  load();
}

async function rejectProposal(proposalId) {
  const reason = window.prompt("驳回原因（可选）");
  if (reason === null) return;
  await workInfoProposalReject(proposalId, reason);
  ElMessage.success("已驳回");
  load();
}
</script>

<template>
  <div v-loading="loading">
    <h1 class="page-title">待审核</h1>
    <div class="section-card">
      <h2>发货上报待审核（{{ data.reports.length }}）</h2>
      <el-table :data="data.reports" border size="small">
        <el-table-column label="时间" width="110">
          <template #default="{ row }">{{ new Date(row.created_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) }}</template>
        </el-table-column>
        <el-table-column prop="user" label="员工" width="90" />
        <el-table-column prop="company" label="公司" width="110" />
        <el-table-column prop="style" label="款式" min-width="120" />
        <el-table-column label="尺码数量" min-width="120">
          <template #default="{ row }">
            <div v-for="l in row.lines" :key="l.size">{{ l.size }} {{ l.quantity }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="review_reason" label="原因" min-width="160" />
        <el-table-column label="照片" width="130">
          <template #default="{ row }">
            <div v-if="row.photos.length" style="display:flex;gap:4px;flex-wrap:wrap">
              <el-image
                v-for="p in row.photos"
                :key="p.id"
                :src="`/photos/shipment/${p.id}?thumb=1`"
                :preview-src-list="[`/photos/shipment/${p.id}`]"
                preview-teleported
                fit="cover"
                style="width:40px;height:40px;border-radius:4px"
              />
            </div>
            <span v-else class="muted">0 张</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="approve(row.id)">通过</el-button>
            <el-button size="small" type="danger" plain @click="reject(row.id)">驳回</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="section-card">
      <h2>作业信息待审核（{{ data.work_info_proposals.length }}）</h2>
      <el-table :data="data.work_info_proposals" border size="small">
        <el-table-column label="时间" width="110">
          <template #default="{ row }">{{ new Date(row.created_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) }}</template>
        </el-table-column>
        <el-table-column prop="user" label="员工" width="90" />
        <el-table-column prop="company" label="公司" width="110" />
        <el-table-column prop="product" label="产品" min-width="100" />
        <el-table-column prop="style" label="款式" min-width="110" />
        <el-table-column label="提交内容" min-width="200">
          <template #default="{ row }">
            <div v-for="r in row.rows" :key="r.row_index" style="margin-bottom:4px">
              <b>{{ r.section_title }}</b>：{{ r.content }}
              <el-image
                v-if="r.has_photo"
                :src="`/photos/work-info/proposal/${row.id}/${r.row_index}?thumb=1`"
                :preview-src-list="[`/photos/work-info/proposal/${row.id}/${r.row_index}`]"
                preview-teleported
                fit="cover"
                style="width:40px;height:40px;border-radius:4px;margin-left:6px;vertical-align:middle"
              />
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="approveProposal(row.id)">通过并生效</el-button>
            <el-button size="small" type="danger" plain @click="rejectProposal(row.id)">驳回</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>
