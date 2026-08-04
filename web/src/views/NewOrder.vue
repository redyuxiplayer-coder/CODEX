<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { createOrders, fetchOrdersOptions } from "../api";

const options = ref({ companies: [], choices: {} });
const form = ref({
  company_name: "",
  product_name: "",
  style_name: "",
  order_date: new Date().toISOString().slice(0, 10),
  delivery_date: "",
  accessories: "",
  material: "",
  spec_size: "",
  note: "",
  sizes: ["S", "M", "L", "XL", "XXL", "均码"],
  quantities: ["0", "0", "0", "0", "0", "0"],
});
const submitting = ref(false);

onMounted(async () => {
  options.value = await fetchOrdersOptions();
});

function products() {
  return Object.keys((options.value.choices[form.value.company_name] || {}));
}

function styles() {
  return Object.keys(((options.value.choices[form.value.company_name] || {})[form.value.product_name]) || {});
}

function sizesFor() {
  const sizes = (((options.value.choices[form.value.company_name] || {})[form.value.product_name] || {})[form.value.style_name]) || [];
  if (sizes.length) return sizes;
  return ["S", "M", "L", "XL", "XXL", "均码"];
}

async function submit() {
  submitting.value = true;
  try {
    const data = await createOrders({ ...form.value, confirm_duplicate: "0" });
    if (data.duplicates && data.duplicates.length) {
      const lines = data.duplicates.map((d) => `${d.company} / ${d.product} / ${d.style} / ${d.size} / ${d.quantity}件 / ${d.order_date}`).join("\n");
      await ElMessageBox.confirm(`同公司、同产品、同款式、同下单日期、同尺码已存在订单：\n\n${lines}\n\n确认不是重复后再保存。`, "可能重复", {
        confirmButtonText: "确认不是重复，保存",
        cancelButtonText: "取消",
        type: "warning",
      });
      const confirmed = await createOrders({ ...form.value, confirm_duplicate: "1" });
      ElMessage.success(`已保存 ${confirmed.created} 个尺码，共 ${confirmed.total} 件`);
    } else {
      ElMessage.success(`已保存 ${data.created} 个尺码，共 ${data.total} 件`);
    }
    form.value.quantities = form.value.quantities.map(() => "0");
  } catch (err) {
    if (err !== "cancel" && err !== "close") ElMessage.error(err.message || "保存失败");
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div>
    <h1 class="page-title">新增订单</h1>
    <div class="section-card" style="max-width:860px">
      <el-form label-width="90px" label-position="right">
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="公司">
              <el-select v-model="form.company_name" filterable allow-create placeholder="选择或输入公司" style="width:100%">
                <el-option v-for="c in options.companies" :key="c" :label="c" :value="c" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="产品">
              <el-select v-model="form.product_name" filterable allow-create placeholder="产品" style="width:100%">
                <el-option v-for="p in products()" :key="p" :label="p" :value="p" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="款式">
              <el-select v-model="form.style_name" filterable allow-create placeholder="款式" style="width:100%">
                <el-option v-for="s in styles()" :key="s" :label="s" :value="s" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="下单日期">
              <el-date-picker v-model="form.order_date" type="date" value-format="YYYY-MM-DD" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="交货日期">
              <el-input v-model="form.delivery_date" placeholder="例如 7月底 / 20天内 / 等通知" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="尺码数量">
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <div v-for="(size, index) in form.sizes" :key="index" style="display:flex;gap:6px;align-items:center">
              <el-input v-model="form.sizes[index]" style="width:76px" placeholder="尺码" />
              <el-input-number v-model="form.quantities[index]" :min="0" controls-position="right" style="width:110px" />
            </div>
          </div>
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="配件">
              <el-input v-model="form.accessories" placeholder="例如 帽子*1-眼镜*1" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="材质">
              <el-input v-model="form.material" placeholder="例如 涤纶" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="尺寸">
              <el-input v-model="form.spec_size" placeholder="例如 110*160CM" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="特殊备注">
          <el-input v-model="form.note" type="textarea" :rows="2" placeholder="其他说明" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="submitting" @click="submit">保存订单</el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>
