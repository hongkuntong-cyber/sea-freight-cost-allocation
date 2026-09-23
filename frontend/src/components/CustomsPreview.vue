<script setup lang="ts">
import type { CustomsParseResult } from "../types";

defineProps<{ data: CustomsParseResult | null }>();
</script>

<template>
  <div v-if="data">
    <div class="summary">
      <span>文件类型：<b>{{ data.file_type }}</b></span>
      <span>MRN：<b>{{ data.mrn || "—" }}</b></span>
      <span>报关单号：<b>{{ data.declaration_no || "—" }}</b></span>
      <span>柜号：<b>{{ data.container || "—" }}</b></span>
      <span>申报总件数(colli)：<b>{{ data.total_colli ?? "—" }}</b></span>
      <span>税项笔数：<b>{{ data.articles.length }}</b></span>
    </div>

    <table>
      <thead>
        <tr>
          <th>税项</th>
          <th>商品</th>
          <th>HS Code</th>
          <th>申报数量</th>
          <th>关税(€)</th>
          <th>VAT(€)</th>
          <th>遮盖</th>
          <th>可靠</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="a in data.articles" :key="a.article_no">
          <td>{{ a.article_no }}</td>
          <td>{{ a.description }}</td>
          <td>{{ a.hs_code }}</td>
          <td>{{ a.declared_qty ?? "—" }}</td>
          <td>{{ a.duty_eur.toFixed(2) }}</td>
          <td>{{ a.vat_eur.toFixed(2) }}</td>
          <td>
            <span v-if="a.masked" class="badge warn">已遮盖</span>
            <span v-else>—</span>
          </td>
          <td>
            <span :class="a.reliable ? 'badge auto' : 'badge unmatched'">
              {{ a.reliable ? "可解析" : "需人工" }}
            </span>
          </td>
        </tr>
      </tbody>
    </table>

    <p v-if="data.warnings.length" class="warn-text">
      提示：{{ data.warnings.join("；") }}
    </p>
  </div>
  <p v-else class="empty">暂无海关税单数据，请先上传。</p>
</template>

<style scoped>
.summary {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.warn-text {
  color: var(--warn);
}
.empty {
  color: var(--muted);
}
</style>
