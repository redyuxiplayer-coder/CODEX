<script setup>
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { createSalesOrder, fetchCompanies, fetchSpus } from "../api";

const companies = ref([]);
const spus = ref([]);
const submitting = ref(false);
const createdOrder = ref(null);
const form = ref({
  company_id: "",
  spu_id: "",
  color_name: "",
  color_code: "",
  order_date: new Date().toISOString().slice(0, 10),
  customer_order_no: "",
  delivery_date: "",
  note: "",
  lines: [
    { size: "S", quantity: 0, customer_sku: "" },
    { size: "M", quantity: 0, customer_sku: "" },
    { size: "L", quantity: 0, customer_sku: "" },
    { size: "XL", quantity: 0, customer_sku: "" },
  ],
});

const selectedSpu = computed(() => spus.value.find((item) => item.id === form.value.spu_id));

onMounted(async () => {
  const [companyData, spuData] = await Promise.all([fetchCompanies(), fetchSpus()]);
  companies.value = companyData.companies.filter((item) => item.is_active);
  spus.value = spuData.spus.filter((item) => item.is_active);
});

function addLine() {
  form.value.lines.push({ size: "", quantity: 0, customer_sku: "" });
}

function removeLine(index) {
  form.value.lines.splice(index, 1);
}

async function submit() {
  const lines = form.value.lines.filter((line) => line.size.trim() && Number(line.quantity) > 0);
  if (!form.value.company_id || !form.value.spu_id || !form.value.order_date || !lines.length) {
    ElMessage.warning("请选择公司和 SPU，并填写下单日期及尺码数量");
    return;
  }
  submitting.value = true;
  try {
    createdOrder.value = await createSalesOrder({ ...form.value, lines });
    ElMessage.success(`订单 ${createdOrder.value.system_order_no} 已创建`);
  } catch (err) {
    ElMessage.error(err.message);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div>
    <h1 class="page-title">新增正式订单</h1>
    <el-alert v-if="createdOrder" type="success" :closable="false" show-icon style="margin-bottom:16px">
      <template #title>系统订单号：{{ createdOrder.system_order_no }}</template>
      <el-button type="primary" link @click="$router.push(`/sales-orders/${createdOrder.id}`)">查看订单详情</el-button>
    </el-alert>
    <div class="section-card" style="max-width:980px">
      <el-form label-width="100px">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="公司">
              <el-select v-model="form.company_id" filterable placeholder="选择公司" style="width:100%">
                <el-option v-for="c in companies" :key="c.id" :label="`${c.name}${c.code ? ` (${c.code})` : '（未设代码）'}`" :value="c.id" :disabled="!c.code" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="内部 SPU">
              <el-select v-model="form.spu_id" filterable placeholder="选择 SPU" style="width:100%">
                <el-option v-for="s in spus" :key="s.id" :label="`${s.code} / ${s.product_name} / ${s.style_name}`" :value="s.id" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row v-if="selectedSpu" :gutter="16">
          <el-col :span="12"><el-form-item label="产品"><el-input :model-value="selectedSpu.product_name" disabled /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="款式"><el-input :model-value="selectedSpu.style_name" disabled /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="8"><el-form-item label="颜色"><el-input v-model="form.color_name" placeholder="无颜色可留空" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="颜色编码"><el-input v-model="form.color_code" placeholder="例如 RED；无颜色留空" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="下单日期"><el-date-picker v-model="form.order_date" type="date" value-format="YYYY-MM-DD" style="width:100%" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="客户订单号"><el-input v-model="form.customer_order_no" placeholder="客户没有则留空" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="交期"><el-input v-model="form.delivery_date" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="尺码明细">
          <div style="width:100%">
            <div v-for="(line, index) in form.lines" :key="index" style="display:grid;grid-template-columns:110px 150px 1fr 70px;gap:8px;margin-bottom:8px">
              <el-input v-model="line.size" placeholder="尺码" />
              <el-input-number v-model="line.quantity" :min="0" style="width:150px" />
              <el-input v-model="line.customer_sku" placeholder="客户 SKU（客户提供才填）" />
              <el-button type="danger" link @click="removeLine(index)">删除</el-button>
            </div>
            <el-button @click="addLine">增加尺码</el-button>
          </div>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="form.note" type="textarea" :rows="3" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="submitting" @click="submit">保存并生成订单号</el-button></el-form-item>
      </el-form>
    </div>
  </div>
</template>
