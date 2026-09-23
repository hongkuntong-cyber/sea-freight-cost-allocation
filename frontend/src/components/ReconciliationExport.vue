<script setup lang="ts">
import { computed } from "vue";
import type { Reconciliation } from "../types";
import { exportUrl } from "../api";

const props = defineProps<{
  data: Reconciliation | null;
  sessionId: string;
}>();

function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return Number(v).toFixed(2);
}

const rows = computed(() => {
  const r = props.data;
  if (!r) return [];
  return [
    ["原始海运费（元）", fmt(r.original_sea_freight)],
    ["分摊后海运费（元）", fmt(r.allocated_sea_freight)],
    ["海运费差额（元）", fmt(r.sea_freight_diff)],
    ["原币关税合计（€）", fmt(r.eur_duty_total)],
    ["结算汇率", fmt(r.exchange_rate)],
    ["实际人民币关税（元）", fmt(r.rmb_duty_input)],
    ["已归集关税（元）", fmt(r.allocated_duty)],
    ["待确认关税（元）", fmt(r.pending_duty)],
    ["关税核对差额（元）", fmt(r.duty_diff)],
    ["装箱单总箱数", r.box_count_packing],
    ["海关申报总件数(colli)", r.box_count_customs ?? "—"],
    ["箱数差异", r.box_count_diff ?? "—"],
  ];
});

function download(mode: "final" | "pending") {
  const a = document.createElement("a");
  a.href = exportUrl(props.sessionId, mode);
  a.download = "";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}
</script>

<template>
  <div v-if="data">
    <div class="status" :class="data.unresolved_exceptions ? 'bad' : 'good'">
      <strong>未解决关键异常：</strong>
      {{ data.unresolved_exceptions ? "是（禁止导出最终确认版）" : "否（可导出最终确认版）" }}
    </div>

    <table>
      <thead>
        <tr><th>核对项目</th><th>数值</th></tr>
      </thead>
      <tbody>
        <tr v-for="(row, i) in rows" :key="i">
          <td>{{ row[0] }}</td>
          <td>{{ row[1] }}</td>
        </tr>
      </tbody>
    </table>

    <h4>报关数量差异</h4>
    <table v-if="data.declared_qty_diff.length">
      <thead>
        <tr><th>货件</th><th>税项</th><th>海关数量</th><th>装箱数量</th><th>差异</th></tr>
      </thead>
      <tbody>
        <tr v-for="(d, i) in data.declared_qty_diff" :key="i">
          <td>{{ d.ref_id }}</td>
          <td>{{ d.article }}</td>
          <td>{{ d.customs_qty }}</td>
          <td>{{ d.packing_qty }}</td>
          <td>{{ d.diff }}</td>
        </tr>
      </tbody>
    </table>
    <p v-else class="ok-text">无报关数量差异。</p>

    <h4>HS Code 异常</h4>
    <table v-if="data.hs_anomalies.length">
      <thead>
        <tr><th>货件</th><th>税项</th><th>报关HS</th><th>装箱HS</th><th>说明</th></tr>
      </thead>
      <tbody>
        <tr v-for="(h, i) in data.hs_anomalies" :key="i">
          <td>{{ h.ref_id }}</td>
          <td>{{ h.article }}</td>
          <td>{{ h.customs_hs }}</td>
          <td>{{ (h.packing_hs || []).join("/") }}</td>
          <td>{{ h.note }}</td>
        </tr>
      </tbody>
    </table>
    <p v-else class="ok-text">无 HS Code 异常。</p>

    <h4>尾差处理说明</h4>
    <p class="tail">{{ data.tail_handling }}</p>

    <div class="export-actions">
      <button
        :disabled="data.unresolved_exceptions"
        @click="download('final')"
        title="存在未解决异常时不可用"
      >
        导出最终确认版 Excel
      </button>
      <button class="ghost" @click="download('pending')">
        导出待确认工作版 Excel
      </button>
    </div>
  </div>
  <p v-else class="empty">请先执行"计算"。</p>
</template>

<style scoped>
.status {
  padding: 10px 14px;
  border-radius: 6px;
  margin-bottom: 12px;
  font-size: 14px;
}
.status.good {
  background: #e3f3ea;
  color: var(--ok);
}
.status.bad {
  background: #fbe4e1;
  color: var(--danger);
}
h4 {
  margin: 18px 0 8px;
  color: var(--primary);
}
.ok-text {
  color: var(--ok);
}
.tail {
  color: var(--muted);
  line-height: 1.7;
}
.export-actions {
  display: flex;
  gap: 12px;
  margin-top: 18px;
}
.empty {
  color: var(--muted);
}
</style>
