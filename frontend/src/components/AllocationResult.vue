<script setup lang="ts">
import type { ComputeResult } from "../types";

const props = defineProps<{ data: ComputeResult | null }>();

function refName(refId: string): string {
  return refId;
}
</script>

<template>
  <div v-if="data">
    <h4>海运费分摊（按体积占比，最大余数法对平）</h4>
    <table>
      <thead>
        <tr>
          <th>Reference ID</th>
          <th>体积(m³)</th>
          <th>海运费(元)</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in data.refs" :key="r.ref_id">
          <td>{{ r.ref_id }}</td>
          <td>{{ r.volume_m3.toFixed(6) }}</td>
          <td>{{ (data.sea_freight_alloc[r.ref_id] ?? 0).toFixed(2) }}</td>
        </tr>
        <tr class="total-row">
          <td>合计</td>
          <td></td>
          <td>
            {{ Object.values(data.sea_freight_alloc).reduce((s, v) => s + v, 0).toFixed(2) }}
          </td>
        </tr>
      </tbody>
    </table>

    <h4>关税归集（按各税项原币比例分摊人民币关税）</h4>
    <table>
      <thead>
        <tr>
          <th>Reference ID</th>
          <th>关税(元)</th>
          <th>匹配状态</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="m in data.matches" :key="m.article_key">
          <td>
            <span v-if="m.status === 'pending' || m.status === 'unmatched'">
              待确认 → {{ m.candidate_refs.join("/") || "无候选" }}
            </span>
            <span v-else-if="!m.ref_id && m.candidate_refs.length">
              合并拆分 → {{ m.candidate_refs.join(" / ") }}
            </span>
            <span v-else>{{ m.ref_id }}</span>
          </td>
          <td>
            <span v-if="m.ref_id && data.duty_alloc[m.ref_id] !== undefined">
              {{ data.duty_alloc[m.ref_id].toFixed(2) }}
            </span>
            <span v-else-if="m.status === 'pending' || m.status === 'unmatched'">
              {{ (data.article_rmb[m.article_key] ?? 0).toFixed(2) }}（待确认）
            </span>
            <span v-else-if="!m.ref_id && m.candidate_refs.length">
              {{ (data.article_rmb[m.article_key] ?? 0).toFixed(2) }}（按数量比例拆分）
            </span>
            <span v-else>0.00</span>
          </td>
          <td>
            <span :class="'badge ' + m.status">{{ m.status }}</span>
          </td>
        </tr>
        <tr class="total-row">
          <td>待确认关税</td>
          <td>{{ Number(data.pending_duty).toFixed(2) }}</td>
          <td></td>
        </tr>
      </tbody>
    </table>
  </div>
  <p v-else class="empty">请先执行"计算"生成分摊结果。</p>
</template>

<style scoped>
h4 {
  margin: 18px 0 8px;
  color: var(--primary);
}
.total-row td {
  font-weight: 700;
  background: #f0f4f8;
}
.empty {
  color: var(--muted);
}
</style>
