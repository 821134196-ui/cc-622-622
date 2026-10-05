<template>
  <div>
    <div class="card">
      <h2>新建寄送任务</h2>
      <div v-if="formError" class="error-banner">{{ formError }}</div>
      <div class="form-row">
        <label>作者</label>
        <select v-model.number="form.author_id">
          <option :value="0" disabled>选择作者</option>
          <option v-for="a in authors" :key="a.id" :value="a.id">
            {{ a.name }}{{ a.current_address ? '' : '（无已确认地址）' }}
          </option>
        </select>
        <label>图书 · 版次</label>
        <select v-model.number="form.edition_id">
          <option :value="0" disabled>选择版次</option>
          <option v-for="e in editions" :key="e.id" :value="e.id">
            {{ e.book_title }} · {{ e.edition_no }}
          </option>
        </select>
        <label>应寄数量</label>
        <input type="number" v-model.number="form.quantity_due" min="1" style="width:90px" />
        <label>编辑</label>
        <input v-model="form.created_by" style="width:110px" />
        <label>备注</label>
        <input v-model="form.note" style="width:180px" />
        <button class="primary" @click="createTask">创建任务</button>
      </div>
      <p class="muted" style="margin:0">
        应寄数量按「作者 × 版次」归集: 旧版样书的签收数量不会抵扣新版应寄份数。
      </p>
    </div>

    <div class="card">
      <div class="section-title">
        <h2>寄送任务</h2>
        <button class="sm" @click="load">刷新</button>
      </div>
      <div v-if="error" class="error-banner">{{ error }}</div>
      <div v-if="tasks.length === 0" class="empty">暂无任务</div>
      <table v-else>
        <thead>
          <tr>
            <th>任务号</th><th>作者</th><th>图书 · 版次</th>
            <th>应寄</th><th>已寄</th><th>实收</th><th>差额</th>
            <th>状态</th><th>编辑</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.id">
            <td>{{ t.task_no }}</td>
            <td>{{ t.author_name }}</td>
            <td>{{ t.book_title }} · {{ t.edition_no }}</td>
            <td>{{ t.quantity_due }}</td>
            <td>{{ t.quantity_shipped }}</td>
            <td>{{ t.quantity_received }}</td>
            <td :style="{ color: t.outstanding ? '#c02222' : '#177245', fontWeight: 600 }">
              {{ t.outstanding }}
            </td>
            <td>
              <span class="badge" :class="taskStatus[t.status].cls">{{ taskStatus[t.status].text }}</span>
            </td>
            <td>{{ t.created_by }}</td>
            <td><RouterLink :to="`/tasks/${t.id}`"><button class="sm">详情</button></RouterLink></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { taskStatus } from '../labels'

const tasks = ref([])
const authors = ref([])
const editions = ref([])
const error = ref('')
const formError = ref('')
const form = reactive({
  author_id: 0, edition_id: 0, quantity_due: 1, created_by: '编辑', note: '',
})

async function load() {
  error.value = ''
  try {
    ;[tasks.value, authors.value, editions.value] = await Promise.all([
      api.get('/api/tasks'), api.get('/api/authors'), api.get('/api/editions'),
    ])
  } catch (e) {
    error.value = e.message
  }
}

async function createTask() {
  formError.value = ''
  if (!form.author_id || !form.edition_id) {
    formError.value = '请选择作者和版次'
    return
  }
  try {
    await api.post('/api/tasks', { ...form })
    form.note = ''
    await load()
  } catch (e) {
    formError.value = e.message
  }
}

onMounted(load)
</script>
