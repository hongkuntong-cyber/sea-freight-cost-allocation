<script setup lang="ts">
import { reactive, watch } from "vue";
import type { ComputeResult, MatchResult } from "../types";

const props = defineProps<{ data: ComputeResult | null }>();
const emit = defineEmits<{ (e: "confirm", payload: Record<string, string>): void }>();

const selections = reactive<Record<string, string>>({});

// 初始化默认勾选第一个候选货件
watch(
  () => props.data,
  (val) => {
    if (!val) return;
    for (const m of val.matches) {
      if (m.status === "pending" && m.candidate_refs.length) {
        if (!selections[m.article_key]) {
          selections[m.article_key] = m.candidate_refs[0];
        }
      }
    }
  },
  { immediate: true },
);

const pendingMatches = (): MatchResult[] =>
  (props.data?.matches ?? []).filter(
    (m) => m.status === "pending" || m.status === "unmatched",
  );

function submit() {
  emit("confirm", { ...selections });
}
</script>

<template>
  <div v-if="data">
    <p class="hint">
      以下税项无法自动唯一确认（多个货件并列 / 名称或数量不一致 / 无对应货件）。
      HS Code 以实际海关税金单为准，装箱单为初始版本，HS 不一致不再作为待确认条件。
      请人工指定归属后提交；系统将记录审计轨迹，且<strong>绝不强行归集</strong>。
    </p>

    <table v-if="pendingMatches().length">
      <thead>
        <tr>
          <th>税项</th>
          <th>商品 / HS</th>
          <th>申报数量</th>
          <th>人民币关税</th>
          <th>原因</th>
          <th>指定归属货件</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="m in pendingMatches()" :key="m.article_key">
          <td>{{ m.article_no }}</td>
          <td>{{ m.description }} / {{ m.hs_code }}</td>
          <td>{{ m.declared_qty ?? "—" }}</td>
          <td>{{ (data!.article_rmb[m.article_key] ?? 0).toFixed(2) }}</td>
          <td>{{ m.reason }}</td>
          <td>
            <select
              v-if="m.candidate_refs.length"
              v-model="selections[m.article_key]"
            >
              <option v-for="c in m.candidate_refs" :key="c" :value="c">
                {{ c }}
              </option>
            </select>
            <span v-else class="badge unmatched">无可匹配货件</span>
          </td>
        </tr>
      </tbody>
    </table>

    <p v-else class="ok-text">✓ 当前没有待确认/无法匹配的税项。</p>

    <button
      v-if="pendingMatches().length"
      :disabled="pendingMatches().some((m) => m.candidate_refs.length && !selections[m.article_key])"
      @click="submit"
    >
      提交人工确认
    </button>
  </div>
  <p v-else class="empty">请先执行"计算"。</p>
</template>

<style scoped>
.hint {
  color: var(--muted);
  line-height: 1.6;
}
.ok-text {
  color: var(--ok);
}
.empty {
  color: var(--muted);
}
</style>
