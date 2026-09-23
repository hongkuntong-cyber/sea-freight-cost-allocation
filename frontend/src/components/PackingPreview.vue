<script setup lang="ts">
import type { PackingParseResult } from "../types";

defineProps<{ data: PackingParseResult | null }>();
</script>

<template>
  <div v-if="data">
    <div class="summary">
      <span>总箱数：<b>{{ data.total_box_count }}</b></span>
      <span>货件数：<b>{{ data.refs.length }}</b></span>
      <span v-if="data.warnings.length" class="warn-text">
        文件级提示：{{ data.warnings.join("；") }}
      </span>
    </div>

    <table>
      <thead>
        <tr>
          <th>Reference ID</th>
          <th>箱数</th>
          <th>总体积(m³)</th>
          <th>HS Code</th>
          <th>商品</th>
          <th>告警</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in data.refs" :key="r.ref_id">
          <td>{{ r.ref_id }}</td>
          <td>{{ r.total_box_count }}</td>
          <td>{{ r.volume_m3.toFixed(6) }}</td>
          <td>{{ r.items.map((i) => i.hs_code).filter(Boolean).join("/") }}</td>
          <td>
            {{ r.items.map((i) => i.cn_name || i.en_name).filter(Boolean).join("、") }}
          </td>
          <td>
            <span v-if="r.warnings.length" class="badge warn">
              {{ r.warnings.join("；") }}
            </span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <p v-else class="empty">暂无装箱单数据，请先上传。</p>
</template>

<style scoped>
.summary {
  display: flex;
  gap: 18px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.warn-text {
  color: var(--warn);
}
.empty {
  color: var(--muted);
}
</style>
