<script setup lang="ts">
import { ref, computed } from "vue";
import {
  createSession,
  uploadPacking,
  uploadCustoms,
  compute,
  confirm,
} from "./api";
import type {
  SessionSummary,
  PackingParseResult,
  CustomsParseResult,
  ComputeResult,
} from "./types";
import PackingPreview from "./components/PackingPreview.vue";
import CustomsPreview from "./components/CustomsPreview.vue";
import AllocationResult from "./components/AllocationResult.vue";
import ExceptionHandling from "./components/ExceptionHandling.vue";
import ReconciliationExport from "./components/ReconciliationExport.vue";

const steps = [
  "① 费用输入",
  "② 文件上传",
  "③ 装箱单预览",
  "④ 税项预览",
  "⑤ 分摊计算",
  "⑥ 异常处理",
  "⑦ 最终核对导出",
];
const step = ref(0);

const cabinet = ref({ cabinet_no: "", sea_freight: "", rmb_duty: "", exchange_rate: "8.2", note: "" });
const session = ref<SessionSummary | null>(null);

const packingFile = ref<File | null>(null);
const customsFiles = ref<File[]>([]);
const packing = ref<PackingParseResult | null>(null);
const customs = ref<CustomsParseResult | null>(null);
const result = ref<ComputeResult | null>(null);

const error = ref("");
const busy = ref(false);

const canUpload = computed(() => !!session.value);
const canPreview = computed(() => !!packing.value && !!customs.value);
const canCompute = computed(() => canPreview.value);
const canExceptions = computed(() => !!result.value);
const canExport = computed(() => !!result.value);

function go(i: number) {
  if (i === 1 && !session.value) return;
  if (i >= 2 && !canPreview.value) return;
  if (i === 5 && !result.value) return;
  if (i === 6 && !result.value) return;
  step.value = i;
}

async function createSessionAndNext() {
  error.value = "";
  busy.value = true;
  try {
    const s = await createSession({
      cabinet_no: cabinet.value.cabinet_no,
      sea_freight: Number(cabinet.value.sea_freight),
      rmb_duty: Number(cabinet.value.rmb_duty),
      exchange_rate: Number(cabinet.value.exchange_rate),
      note: cabinet.value.note,
    });
    session.value = s;
    step.value = 1;
  } catch (e: any) {
    error.value = "创建货柜会话失败：" + (e?.message || e);
  } finally {
    busy.value = false;
  }
}

async function uploadAll() {
  if (!session.value) return;
  error.value = "";
  busy.value = true;
  try {
    if (packingFile.value) {
      packing.value = await uploadPacking(session.value.session_id, packingFile.value);
    }
    if (customsFiles.value.length) {
      customs.value = await uploadCustoms(session.value.session_id, customsFiles.value);
    }
    step.value = 2;
  } catch (e: any) {
    error.value = "上传解析失败：" + (e?.message || e);
  } finally {
    busy.value = false;
  }
}

async function runCompute() {
  if (!session.value) return;
  error.value = "";
  busy.value = true;
  try {
    result.value = await compute(session.value.session_id);
    step.value = 5;
  } catch (e: any) {
    error.value = "计算失败：" + (e?.message || e);
  } finally {
    busy.value = false;
  }
}

async function onConfirm(payload: Record<string, string>) {
  if (!session.value) return;
  error.value = "";
  busy.value = true;
  try {
    result.value = await confirm(session.value.session_id, payload);
    await runCompute2();
  } catch (e: any) {
    error.value = "确认失败：" + (e?.message || e);
  } finally {
    busy.value = false;
  }
}

async function runCompute2() {
  if (!session.value) return;
  result.value = await compute(session.value.session_id);
}

function onCustomsChange(e: Event) {
  const input = e.target as HTMLInputElement;
  customsFiles.value = input.files ? Array.from(input.files) : [];
}
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <h1>海运费用<br />归集与关税分摊</h1>
      <nav>
        <button
          v-for="(s, i) in steps"
          :key="i"
          class="step"
          :class="{ active: step === i, disabled: (i === 1 && !session) || (i >= 2 && !canPreview) || (i >= 5 && !result) }"
          @click="go(i)"
        >
          {{ s }}
        </button>
      </nav>
      <div class="meta" v-if="session">
        <div>当前货柜：{{ session.cabinet_no }}</div>
        <div class="sid">会话：{{ session.session_id.slice(0, 8) }}</div>
      </div>
    </aside>

    <main class="content">
      <p v-if="error" class="error">{{ error }}</p>

      <!-- ① 费用输入 -->
      <section v-show="step === 0">
        <h2>① 费用输入（一个货柜一次核算）</h2>
        <div class="form-grid">
          <div><label>货柜号 *</label><input v-model="cabinet.cabinet_no" placeholder="如 008" /></div>
          <div><label>整柜海运费（元）*</label><input v-model="cabinet.sea_freight" type="number" placeholder="54485.80" /></div>
          <div><label>实际人民币关税（元）*</label><input v-model="cabinet.rmb_duty" type="number" placeholder="7486.68" /></div>
          <div><label>结算汇率（€→¥）</label><input v-model="cabinet.exchange_rate" type="number" step="0.01" placeholder="8.2" /></div>
          <div class="full"><label>备注</label><input v-model="cabinet.note" placeholder="可选" /></div>
        </div>
        <button :disabled="busy || !cabinet.cabinet_no || !cabinet.sea_freight || !cabinet.rmb_duty" @click="createSessionAndNext">
          {{ busy ? "处理中…" : "创建货柜会话并下一步" }}
        </button>
      </section>

      <!-- ② 文件上传 -->
      <section v-show="step === 1">
        <h2>② 文件上传</h2>
        <div class="form-grid">
          <div class="full">
            <label>装箱单 Excel（货件编号 / 箱号 / 尺寸 / HS Code）</label>
            <input type="file" accept=".xlsx,.xls" @change="e => packingFile = (e.target as HTMLInputElement).files?.[0] ?? null" />
          </div>
          <div class="full">
            <label>海关税单（PDF 或 ZIP 多个 PDF，可多选）</label>
            <input type="file" accept=".pdf,.zip" multiple @change="onCustomsChange" />
          </div>
        </div>
        <p class="hint">支持荷兰海关缴税通知（UITNODIGING）、放行单（TOESTEMMING）等；VAT 不计入关税分摊。</p>
        <button :disabled="busy || !packingFile || !customsFiles.length" @click="uploadAll">
          {{ busy ? "解析中…" : "上传并解析" }}
        </button>
      </section>

      <!-- ③ 装箱单预览 -->
      <section v-show="step === 2">
        <h2>③ 装箱单预览</h2>
        <PackingPreview :data="packing" />
        <button class="ghost" @click="step = 3">下一步：税项预览</button>
      </section>

      <!-- ④ 税项预览 -->
      <section v-show="step === 3">
        <h2>④ 海关税项预览</h2>
        <CustomsPreview :data="customs" />
        <button class="ghost" @click="step = 4">下一步：分摊计算</button>
      </section>

      <!-- ⑤ 分摊计算 -->
      <section v-show="step === 4">
        <h2>⑤ 分摊计算</h2>
        <p class="hint">按体积占比分摊海运费，按各税项原币关税比例分摊人民币关税；均用最大余数法严格对平。</p>
        <button :disabled="busy" @click="runCompute">{{ busy ? "计算中…" : "执行计算" }}</button>
        <AllocationResult :data="result" />
      </section>

      <!-- ⑥ 异常处理 -->
      <section v-show="step === 5">
        <h2>⑥ 异常处理（人工确认归属）</h2>
        <ExceptionHandling :data="result" @confirm="onConfirm" />
        <button class="ghost" @click="step = 6">下一步：核对与导出</button>
      </section>

      <!-- ⑦ 最终核对导出 -->
      <section v-show="step === 6">
        <h2>⑦ 最终核对与导出</h2>
        <ReconciliationExport :data="result?.reconciliation ?? null" :session-id="session?.session_id ?? ''" />
      </section>
    </main>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  min-height: 100vh;
}
.sidebar {
  width: 240px;
  background: var(--primary);
  color: #fff;
  padding: 20px 14px;
  flex-shrink: 0;
}
.sidebar h1 {
  font-size: 18px;
  line-height: 1.4;
  margin: 0 0 18px;
}
.sidebar nav {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.step {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
  text-align: left;
  padding: 8px 10px;
  font-size: 13px;
}
.step.active {
  background: #fff;
  color: var(--primary);
  font-weight: 700;
}
.step.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.meta {
  margin-top: 20px;
  font-size: 12px;
  opacity: 0.85;
}
.meta .sid {
  opacity: 0.7;
}
.content {
  flex: 1;
  padding: 28px 36px;
  max-width: 1100px;
}
.content h2 {
  color: var(--primary);
  margin-top: 0;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 16px;
}
.form-grid .full {
  grid-column: 1 / -1;
}
.hint {
  color: var(--muted);
  font-size: 13px;
  line-height: 1.7;
}
.error {
  background: #fbe4e1;
  color: var(--danger);
  padding: 10px 14px;
  border-radius: 6px;
}
section {
  margin-bottom: 20px;
}
</style>
