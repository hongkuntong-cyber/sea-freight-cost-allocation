<script setup lang="ts">
import { reactive, computed, watch } from "vue";
import type { ComputeResult, MatchResult } from "../types";

const props = defineProps<{ data: ComputeResult | null }>();
const emit = defineEmits<{ (e: "confirm", payload: Record<string, string>): void }>();

const selections = reactive<Record<string, string>>({});

// 只有"装箱单里完全找不到"的税项才进入这里
const needAssign = computed<MatchResult[]>(() =>
  (props.data?.matches ?? []).filter(
    (m) => m.status === "pending" || m.status === "unmatched",
  ),
);

const allRefs = computed<string[]>(() =>
  (props.data?.refs ?? []).map((r) => r.ref_id),
);

const canSubmit = computed(
  () =>
    needAssign.value.length > 0 &&
    needAssign.value.every((m) => !!selections[m.article_key]),
);

// 重置：新一轮分析结果到达时清掉旧选择
watch(
  () => props.data?.session_id,
  () => {
    for (const k of Object.keys(selections)) delete selections[k];
  },
);

function submit() {
  const payload: Record<string, string> = {};
  for (const m of needAssign.value) {
    if (selections[m.article_key]) payload[m.article_key] = selections[m.article_key];
  }
  emit("confirm", payload);
}
</script>

<template>
  <div v-if="data">
    <p class="hint">
      只有<strong>装箱单里找不到的商品</strong>（比如加装进了某个货件）才需要你指定归属。
      数量对不上（漏装 / 装不下 / 加装）、商品名称写法不同这类正常差异，
      系统已经自动归属，并在「核对与异常」里记了差异账，不用在这里处理。
    </p>

    <table v-if="needAssign.length">
      <thead>
        <tr>
          <th>税项</th>
          <th>商品 / HS</th>
          <th>海关申报数量</th>
          <th>人民币关税</th>
          <th>情况</th>
          <th>归属到哪个货件</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="m in needAssign" :key="m.article_key">
          <td>{{ m.article_no }}</td>
          <td>{{ m.description }} / {{ m.hs_code || "—" }}</td>
          <td>{{ m.declared_qty ?? "—" }}</td>
          <td>{{ (data!.article_rmb[m.article_key] ?? 0).toFixed(2) }}</td>
          <td class="why">{{ m.reason }}</td>
          <td>
            <select v-model="selections[m.article_key]">
              <option value="" disabled>— 请选择货件 —</option>
              <option v-for="r in allRefs" :key="r" :value="r">{{ r }}</option>
            </select>
          </td>
        </tr>
      </tbody>
    </table>

    <p v-else class="ok-text">
      ✓ 没有需要你指定的税项：所有税项都已自动归属（数量差异已记录在核对页）。
    </p>

    <button v-if="needAssign.length" :disabled="!canSubmit" @click="submit">
      提交确认（{{ needAssign.length }} 项）
    </button>
  </div>
  <p v-else class="empty">请先执行"计算"。</p>
</template>

<style scoped>
.hint {
  color: var(--muted);
  line-height: 1.7;
  margin: 0 0 12px;
}
.why {
  color: var(--muted);
  font-size: 12.5px;
}
.ok-text {
  color: var(--ok);
  margin: 0;
}
.empty {
  color: var(--muted);
}
select {
  min-width: 220px;
}
</style>
