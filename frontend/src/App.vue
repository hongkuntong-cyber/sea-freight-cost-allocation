<script setup lang="ts">
import { ref, computed } from "vue";
import { analyze, confirm } from "./api";
import type { AnalyzeResult, ComputeResult } from "./types";
import AllocationResult from "./components/AllocationResult.vue";
import ExceptionHandling from "./components/ExceptionHandling.vue";
import ReconciliationExport from "./components/ReconciliationExport.vue";

const form = ref({
  cabinet_no: "",
  sea_freight: "",
  rmb_duty: "",
  exchange_rate: "",
});
const packingFile = ref<File | null>(null);
const customsFiles = ref<File[]>([]);
const result = ref<AnalyzeResult | null>(null);
const error = ref("");
const busy = ref(false);

const canAnalyze = computed(
  () =>
    !!form.value.cabinet_no &&
    !!form.value.sea_freight &&
    !!form.value.rmb_duty &&
    !!packingFile.value &&
    customsFiles.value.length > 0,
);

const v = computed(() => result.value?.verification ?? null);
const pendingCount = computed(() => v.value?.pending_count ?? 0);
const dq = computed(() => v.value?.data_quality ?? null);
const n0 = (x: any) => Number(x ?? 0).toLocaleString("zh-CN");

function _dqOf(r: ComputeResult) {
  return (result.value?.verification as any)?.data_quality ?? null;
}

function recomputeVerification(r: ComputeResult) {
  const rc = r.reconciliation;
  const counts: Record<string, number> = { auto: 0, manual: 0, pending: 0, unmatched: 0 };
  for (const m of r.matches) counts[m.status] = (counts[m.status] ?? 0) + 1;
  return {
    sea_balanced: Math.abs(Number(rc.sea_freight_diff)) < 0.005,
    duty_balanced: Math.abs(Number(rc.duty_diff)) < 0.005,
    match_counts: counts,
    pending_count: (counts.pending ?? 0) + (counts.unmatched ?? 0),
    box_count_diff: rc.box_count_diff,
    qty_diff_count: (rc.declared_qty_diff || []).length,
    unresolved: !!rc.unresolved_exceptions,
    data_quality: _dqOf(r),
  };
}

async function runAnalyze() {
  error.value = "";
  busy.value = true;
  result.value = null;
  try {
    result.value = await analyze(
      {
        cabinet_no: form.value.cabinet_no,
        sea_freight: Number(form.value.sea_freight),
        rmb_duty: Number(form.value.rmb_duty),
        exchange_rate: form.value.exchange_rate
          ? Number(form.value.exchange_rate)
          : undefined,
      },
      packingFile.value!,
      customsFiles.value,
    );
  } catch (e: any) {
    error.value = "分析失败：" + (e?.response?.data?.detail || e?.message || e);
  } finally {
    busy.value = false;
  }
}

async function onConfirm(payload: Record<string, string>) {
  if (!result.value) return;
  error.value = "";
  busy.value = true;
  try {
    const r = await confirm(result.value.session_id, payload);
    result.value = { ...result.value, ...r, verification: recomputeVerification(r) };
  } catch (e: any) {
    error.value = "确认失败：" + (e?.response?.data?.detail || e?.message || e);
  } finally {
    busy.value = false;
  }
}

function onPacking(e: Event) {
  packingFile.value = (e.target as HTMLInputElement).files?.[0] ?? null;
}
function onCustoms(e: Event) {
  customsFiles.value = Array.from((e.target as HTMLInputElement).files ?? []);
}

const n2 = (x: any) => Number(x ?? 0).toFixed(2);
</script>

<template>
  <div class="page">
    <header>
      <h1>海运费用归集与关税分摊</h1>
      <p class="sub">
        填写柜号 / 海运费 / 关税总额，上传装箱单与海关税单，点一次「开始分析」——
        系统自动解析、匹配、分摊并完成自核，结果直接呈现。
      </p>
    </header>

    <section class="card">
      <div class="grid">
        <div>
          <label>货柜号 *</label>
          <input v-model="form.cabinet_no" placeholder="如 008" />
        </div>
        <div>
          <label>整柜海运费（元）*</label>
          <input v-model="form.sea_freight" type="number" placeholder="54485.80" />
        </div>
        <div>
          <label>关税总额（元）*</label>
          <input v-model="form.rmb_duty" type="number" placeholder="7486.68" />
        </div>
        <div>
          <label>汇率 €→¥（可留空）</label>
          <input v-model="form.exchange_rate" type="number" step="0.01" placeholder="留空自动推算" />
        </div>
        <div class="full">
          <label>装箱单 Excel *</label>
          <input type="file" accept=".xlsx,.xls" @change="onPacking" />
        </div>
        <div class="full">
          <label>海关税金单（PDF 或 ZIP，可多选）*</label>
          <input type="file" accept=".pdf,.zip" multiple @change="onCustoms" />
        </div>
      </div>
      <button class="primary" :disabled="busy || !canAnalyze" @click="runAnalyze">
        {{ busy ? "分析中…" : "开始分析" }}
      </button>
    </section>

    <p v-if="error" class="error">{{ error }}</p>

    <template v-if="result && v">
      <!-- 数据来源体检：解析到多少、缺什么，一眼可见 -->
      <section class="card" v-if="dq">
        <h2>数据来源体检</h2>
        <div class="dq-grid">
          <div class="dq-item">
            <span class="dq-k">装箱单</span>
            <span class="dq-v">货件 {{ dq.ref_count }} · SKU/箱型行 {{ dq.sku_count }}</span>
          </div>
          <div class="dq-item">
            <span class="dq-k">总箱数 / 总体积</span>
            <span class="dq-v">{{ n0(dq.total_box) }} 箱 · {{ Number(dq.total_volume).toFixed(4) }} m³</span>
          </div>
          <div class="dq-item">
            <span class="dq-k">海关税项</span>
            <span class="dq-v">{{ dq.article_count }} 条 · MRN {{ dq.mrn || "缺" }} · 申报件数
              {{ dq.customs_colli ?? "缺" }}</span>
          </div>
          <div class="dq-item">
            <span class="dq-k">原币关税 / 汇率</span>
            <span class="dq-v">€{{ n2(dq.eur_duty_total) }} · {{ Number(dq.exchange_rate).toFixed(4) }}</span>
          </div>
        </div>
        <p v-if="dq.warnings.length" class="dq-warn">
          ⚠ 数据缺失 {{ dq.warnings.length }} 项：{{ dq.warnings.join("；") }}
        </p>
        <p v-else class="dq-ok">✓ 装箱单、海关税单关键字段齐全，导出表不会缺列。</p>
        <ul v-if="dq.notes && dq.notes.length" class="dq-notes">
          <li v-for="n in dq.notes" :key="n">说明：{{ n }}</li>
        </ul>
      </section>

      <!-- 自核结论 -->
      <section class="card">
        <h2>自核结论</h2>
        <div class="checks">
          <span class="check" :class="v.sea_balanced ? 'ok' : 'bad'">
            {{ v.sea_balanced ? "✓" : "✗" }} 海运费对平
            <b>{{ n2(result.reconciliation.allocated_sea_freight) }}</b>
            / 输入 {{ n2(result.reconciliation.original_sea_freight) }}
          </span>
          <span class="check" :class="v.duty_balanced ? 'ok' : 'bad'">
            {{ v.duty_balanced ? "✓" : "✗" }} 关税对平
            <b>{{ n2(Number(result.reconciliation.allocated_duty) + Number(result.reconciliation.pending_duty)) }}</b>
            / 输入 {{ n2(result.reconciliation.rmb_duty_input) }}
          </span>
          <span class="check" :class="pendingCount ? 'warn' : 'ok'">
            匹配：自动 {{ v.match_counts.auto }} · 人工 {{ v.match_counts.manual }} ·
            待确认 {{ v.match_counts.pending }} · 无匹配 {{ v.match_counts.unmatched }}
          </span>
          <span class="check" :class="v.qty_diff_count ? 'warn' : 'ok'">
            报关数量差异 {{ v.qty_diff_count }} 项
          </span>
          <span class="check" :class="v.box_count_diff ? 'warn' : 'ok'">
            箱数差异 {{ v.box_count_diff ?? "—" }}
          </span>
        </div>
        <p class="conclusion" :class="v.unresolved ? 'bad' : 'ok'">
          <template v-if="v.unresolved">
            有 {{ pendingCount }} 项需你确认归属（系统已预选推荐货件，点一次即可确认）；
            确认前「最终版」导出会被拦截，可先导出待确认工作版。
          </template>
          <template v-else>
            ✓ 全部核实通过：海运费与关税均已对平，无待确认项，可直接导出最终版。
          </template>
        </p>
      </section>

      <section class="card">
        <h2>分摊明细</h2>
        <AllocationResult :data="result" />
      </section>

      <section class="card" v-if="pendingCount">
        <h2>待你确认（{{ pendingCount }} 项）</h2>
        <ExceptionHandling :data="result" @confirm="onConfirm" />
      </section>

      <section class="card">
        <h2>对账与导出</h2>
        <ReconciliationExport
          :data="result.reconciliation"
          :session-id="result.session_id"
        />
      </section>
    </template>
  </div>
</template>

<style scoped>
.page {
  max-width: 1080px;
  margin: 0 auto;
  padding: 26px 24px 60px;
}
header h1 {
  margin: 0 0 6px;
  color: var(--primary);
  font-size: 22px;
}
.sub {
  margin: 0 0 18px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.7;
}
.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 18px 20px;
  margin-bottom: 16px;
}
.card h2 {
  margin: 0 0 12px;
  color: var(--primary);
  font-size: 15px;
}
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 16px;
}
.grid .full {
  grid-column: 1 / -1;
}
button.primary {
  padding: 10px 22px;
  font-size: 14px;
}
.checks {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.check {
  padding: 6px 12px;
  border-radius: 14px;
  font-size: 12.5px;
  border: 1px solid var(--border);
  background: #f7f9fc;
  color: var(--text);
}
.check.ok {
  background: #e3f3ea;
  color: var(--ok);
  border-color: #bfe0cd;
}
.check.warn {
  background: #fcf1dd;
  color: var(--warn);
  border-color: #f0dcb4;
}
.check.bad {
  background: #fbe4e1;
  color: var(--danger);
  border-color: #f0c4bd;
}
.conclusion {
  margin: 0;
  padding: 10px 14px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.7;
}
.conclusion.ok {
  background: #e3f3ea;
  color: var(--ok);
}
.conclusion.bad {
  background: #fcf1dd;
  color: var(--warn);
}
.dq-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px 18px;
  margin-bottom: 10px;
}
.dq-item {
  display: flex;
  gap: 8px;
  font-size: 12.5px;
  padding: 6px 10px;
  background: #f7f9fc;
  border: 1px solid var(--border);
  border-radius: 5px;
}
.dq-k {
  color: var(--muted);
  min-width: 96px;
}
.dq-v {
  color: var(--text);
}
.dq-warn {
  margin: 6px 0 0;
  padding: 8px 12px;
  border-radius: 5px;
  background: #fbe4e1;
  color: var(--danger);
  font-size: 12.5px;
  line-height: 1.7;
}
.dq-ok {
  margin: 6px 0 0;
  padding: 8px 12px;
  border-radius: 5px;
  background: #e3f3ea;
  color: var(--ok);
  font-size: 12.5px;
}
.dq-notes {
  margin: 8px 0 0;
  padding-left: 18px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.7;
}
.error {
  background: #fbe4e1;
  color: var(--danger);
  padding: 10px 14px;
  border-radius: 6px;
  font-size: 13px;
}
</style>
