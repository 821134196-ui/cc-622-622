<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from './api'
import { fmtTime, badge, TASK_STATUS } from './labels'
import TaskDetail from './components/TaskDetail.vue'

const tab = ref('todo')           // todo | tasks | admin
const todos = ref([])
const tasks = ref([])
const authors = ref([])
const editions = ref([])
const selectedId = ref(null)
const flashMsg = ref(null)
const flashErr = ref(false)

let flashTimer = null
function flash(msg, isErr = false) {
  flashMsg.value = msg
  flashErr.value = isErr
  clearTimeout(flashTimer)
  flashTimer = setTimeout(() => (flashMsg.value = null), 3200)
}

async function reload() {
  const [t, a, e] = await Promise.all([
    api.get('/api/tasks'), api.get('/api/authors'), api.get('/api/editions'),
  ])
  tasks.value = t
  authors.value = a
  editions.value = e
  todos.value = await api.get('/api/todos')
}
onMounted(reload)

const selectedTask = computed(() =>
  tasks.value.find((x) => x.id === selectedId.value) || null)

function openTask(id) {
  selectedId.value = id
  tab.value = 'tasks'
}

const authorName = (id) => authors.value.find((a) => a.id === id)?.name || `#${id}`
const editionLabel = (id) => {
  const e = editions.value.find((x) => x.id === id)
  return e ? `《${e.title}》${e.edition}` : `#${id}`
}

// ---- 新建任务 ----
const newTask = ref({ author_id: '', edition_id: '', required_qty: 5, note: '' })
async function createTask() {
  try {
    const t = await api.post('/api/tasks', {
      ...newTask.value,
      author_id: Number(newTask.value.author_id),
      edition_id: Number(newTask.value.edition_id),
      required_qty: Number(newTask.value.required_qty),
    })
    flash(`任务 ${t.code} 已创建`)
    selectedId.value = t.id
    tab.value = 'tasks'
    await reload()
  } catch (e) { flash(e.message, true) }
}

// ---- 新增作者 / 版次 ----
const newAuthor = ref({ name: '', phone: '' })
async function createAuthor() {
  try {
    await api.post('/api/authors', newAuthor.value)
    newAuthor.value = { name: '', phone: '' }
    flash('作者已添加')
    await reload()
  } catch (e) { flash(e.message, true) }
}
const newEdition = ref({ title: '', edition: '', isbn: '' })
async function createEdition() {
  try {
    await api.post('/api/editions', newEdition.value)
    newEdition.value = { title: '', edition: '', isbn: '' }
    flash('版次已添加')
    await reload()
  } catch (e) { flash(e.message, true) }
}
</script>

<template>
  <header class="topbar">
    <div>
      <h1>📚 样书寄送与作者签收系统</h1>
      <div class="sub">按书版次核对：原寄 · 补寄 · 实收 ｜ 快递轨迹本地模拟</div>
    </div>
    <button class="btn ghost" @click="reload">刷新数据</button>
  </header>

  <div v-if="flashMsg" class="flash" :class="flashErr ? 'err' : 'ok'">{{ flashMsg }}</div>

  <nav class="tabs">
    <button :class="{ active: tab === 'todo' }" @click="tab = 'todo'">
      待办（{{ todos.length }}）
    </button>
    <button :class="{ active: tab === 'tasks' }" @click="tab = 'tasks'">全部任务</button>
    <button :class="{ active: tab === 'admin' }" @click="tab = 'admin'">新建 / 资料</button>
  </nav>

  <!-- ============ 待办 ============ -->
  <section v-if="tab === 'todo'">
    <div v-if="!todos.length" class="card">🎉 暂无待办：没有滞留包裹，也没有数量不一致的任务。</div>
    <div v-for="item in todos" :key="item.task.id" class="card todo-item clickable"
         :class="{ mid: item.priority_score < 100 }" @click="openTask(item.task.id)">
      <div class="row">
        <span class="badge" :class="badge(TASK_STATUS, item.task.status).cls">
          {{ badge(TASK_STATUS, item.task.status).text }}
        </span>
        <b class="mono">{{ item.task.code }}</b>
        <span>{{ authorName(item.task.author_id) }}</span>
        <span class="muted">{{ editionLabel(item.task.edition_id) }}</span>
        <div class="spacer"></div>
        <span class="badge amber">优先级 {{ item.priority_score }}</span>
      </div>
      <ul class="todo-reasons">
        <li v-for="(r, i) in item.reasons" :key="i">{{ r }}</li>
      </ul>
      <div class="small-text muted">
        应寄 {{ item.task.required_qty }} ｜ 原寄 {{ item.task.original_shipped_qty }}
        ｜ 补寄 {{ item.task.reship_shipped_qty }} ｜ 实收
        <b :style="item.task.received_qty >= item.task.required_qty
          ? 'color:var(--ok)' : 'color:var(--danger)'">{{ item.task.received_qty }}</b>
      </div>
    </div>
    <div class="small-text muted" style="margin-top: 6px">
      排序规则：数量不一致（含拒收未补齐）权重最高；在途包裹按未签收天数加权，滞留越久越靠前。
    </div>
  </section>

  <!-- ============ 任务 ============ -->
  <section v-if="tab === 'tasks'" class="grid2" style="align-items: start">
    <div>
      <div v-for="t in tasks" :key="t.id" class="card clickable"
           :style="selectedId === t.id ? 'border-color: var(--primary); box-shadow: 0 0 0 1px var(--primary)' : ''"
           @click="selectedId = t.id">
        <div class="row">
          <span class="badge" :class="badge(TASK_STATUS, t.status).cls">
            {{ badge(TASK_STATUS, t.status).text }}
          </span>
          <b class="mono">{{ t.code }}</b>
          <div class="spacer"></div>
          <span class="small-text muted">{{ fmtTime(t.created_at) }}</span>
        </div>
        <div class="small-text" style="margin-top: 6px">
          {{ authorName(t.author_id) }} ｜ {{ editionLabel(t.edition_id) }}
        </div>
        <div class="small-text muted" style="margin-top: 4px">
          应寄 {{ t.required_qty }} ｜ 原寄 {{ t.original_shipped_qty }}
          ｜ 补寄 {{ t.reship_shipped_qty }} ｜ 实收
          <b :style="t.received_qty >= t.required_qty ? 'color:var(--ok)' : 'color:var(--danger)'">
            {{ t.received_qty }}
          </b>
        </div>
      </div>
    </div>
    <div>
      <div v-if="!selectedTask" class="card muted">← 请选择左侧任务查看包裹、签收与补寄明细</div>
      <div v-else class="card" :key="selectedTask.id">
        <TaskDetail :task="selectedTask" :authors="authors" :editions="editions"
                    @changed="reload" @flash="flash" />
      </div>
    </div>
  </section>

  <!-- ============ 新建 / 资料 ============ -->
  <section v-if="tab === 'admin'" class="grid2" style="align-items: start">
    <div class="card">
      <h3>新建寄送任务（指定作者 + 版次 + 应寄份数）</h3>
      <label class="field"><span>作者</span>
        <select v-model="newTask.author_id">
          <option value="" disabled>请选择</option>
          <option v-for="a in authors" :key="a.id" :value="a.id">{{ a.name }}</option>
        </select></label>
      <label class="field" style="margin-top: 8px"><span>书版次</span>
        <select v-model="newTask.edition_id">
          <option value="" disabled>请选择</option>
          <option v-for="e in editions" :key="e.id" :value="e.id">
            《{{ e.title }}》{{ e.edition }}
          </option>
        </select></label>
      <label class="field" style="margin-top: 8px"><span>应寄份数</span>
        <input type="number" min="1" v-model.number="newTask.required_qty" /></label>
      <label class="field" style="margin-top: 8px"><span>备注</span>
        <input v-model="newTask.note" /></label>
      <button class="btn" style="margin-top: 10px" @click="createTask">创建任务</button>
    </div>

    <div>
      <div class="card">
        <h3>新增作者</h3>
        <div class="grid2">
          <label class="field"><span>姓名</span><input v-model="newAuthor.name" /></label>
          <label class="field"><span>电话</span><input v-model="newAuthor.phone" /></label>
        </div>
        <button class="btn" style="margin-top: 8px" @click="createAuthor">添加</button>
      </div>
      <div class="card">
        <h3>新增书版次（同名书不同版次互相独立）</h3>
        <div class="grid2">
          <label class="field"><span>书名</span><input v-model="newEdition.title" /></label>
          <label class="field"><span>版次</span><input v-model="newEdition.edition"
            placeholder="第2版" /></label>
        </div>
        <label class="field" style="margin-top: 8px"><span>ISBN</span>
          <input v-model="newEdition.isbn" /></label>
        <button class="btn" style="margin-top: 8px" @click="createEdition">添加</button>
      </div>
      <div class="card">
        <h3>现有版次</h3>
        <div v-for="e in editions" :key="e.id" class="small-text" style="padding: 3px 0">
          《{{ e.title }}》{{ e.edition }} <span class="muted mono">{{ e.isbn }}</span>
        </div>
      </div>
    </div>
  </section>
</template>
