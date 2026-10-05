<template>
  <div>
    <div class="card">
      <div class="section-title">
        <h2>待办 — 需要优先处理的包裹</h2>
        <div class="form-row" style="margin:0">
          <label>未签收超过</label>
          <input type="number" v-model.number="days" min="0" style="width:70px" />
          <label>天</label>
          <button class="sm" @click="load">刷新</button>
        </div>
      </div>
      <div v-if="error" class="error-banner">{{ error }}</div>
      <div v-if="!loading && todos.length === 0" class="empty">
        🎉 没有待处理事项: 所有包裹均已按时签收且数量一致
      </div>
      <table v-else-if="todos.length">
        <thead>
          <tr>
            <th>类型</th><th>包裹 / 运单号</th><th>作者</th><th>图书 · 版次</th>
            <th>包裹实收</th><th>任务应寄/实收</th><th>已出库</th><th>原因</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in todos" :key="t.package_id">
            <td>
              <span class="badge" :class="t.kind === 'mismatch' ? 'red' : 'orange'">
                {{ t.kind === 'mismatch' ? '数量不一致' : '长时间未签收' }}
              </span>
            </td>
            <td>{{ t.package_no }}<br /><span class="muted">{{ t.tracking_no }}</span></td>
            <td>{{ t.author_name }}</td>
            <td>{{ t.book_title }} · {{ t.edition_no }}</td>
            <td>{{ t.received_qty }}/{{ t.quantity }}</td>
            <td>{{ t.task_due }}/{{ t.task_received }}</td>
            <td>{{ t.age_days }} 天</td>
            <td>{{ t.reason }}</td>
            <td>
              <RouterLink :to="`/tasks/${t.task_id}`"><button class="sm">去处理</button></RouterLink>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const todos = ref([])
const days = ref(7)
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    todos.value = await api.get(`/api/todos?unsigned_days=${days.value}`)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>
