<template>
  <div>
    <div class="card">
      <h2>新增作者</h2>
      <div class="form-row">
        <label>姓名</label><input v-model="authorForm.name" style="width:120px" />
        <label>笔名</label><input v-model="authorForm.pen_name" style="width:120px" />
        <label>电话</label><input v-model="authorForm.phone" style="width:140px" />
        <button class="primary" @click="addAuthor">添加</button>
      </div>
      <div v-if="error" class="error-banner">{{ error }}</div>
    </div>

    <div class="card">
      <h2>作者列表</h2>
      <table>
        <thead>
          <tr><th>姓名</th><th>笔名</th><th>当前已确认地址</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="a in authors" :key="a.id"
              :style="{ background: selected?.id === a.id ? '#f0f6ff' : '' }">
            <td>{{ a.name }}</td>
            <td>{{ a.pen_name || '-' }}</td>
            <td>
              <span v-if="a.current_address">
                {{ a.current_address.recipient }} {{ a.current_address.phone }}
                {{ a.current_address.region }}{{ a.current_address.detail }}
              </span>
              <span v-else class="badge orange">未确认地址</span>
            </td>
            <td><button class="sm" @click="select(a)">地址与对账</button></td>
          </tr>
        </tbody>
      </table>
    </div>

    <template v-if="selected">
      <div class="card">
        <h2>{{ selected.name }} — 地址管理</h2>
        <table>
          <thead>
            <tr><th>收件人</th><th>电话</th><th>地址</th><th>状态</th><th>确认人</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="ad in selected.addresses" :key="ad.id">
              <td>{{ ad.recipient }}</td>
              <td>{{ ad.phone }}</td>
              <td>{{ ad.region }}{{ ad.detail }}</td>
              <td>
                <span v-if="ad.is_current" class="badge green">当前地址</span>
                <span v-else-if="ad.status === 'confirmed'" class="badge gray">已确认</span>
                <span v-else class="badge orange">待确认</span>
              </td>
              <td>{{ ad.confirmed_by || '-' }}</td>
              <td>
                <button v-if="!ad.is_current" class="sm" @click="confirm(ad)">确认为当前地址</button>
              </td>
            </tr>
          </tbody>
        </table>
        <h3>新增地址</h3>
        <div class="form-row">
          <label>收件人</label><input v-model="addrForm.recipient" style="width:110px" />
          <label>电话</label><input v-model="addrForm.phone" style="width:130px" />
          <label>省市区</label><input v-model="addrForm.region" style="width:160px" />
          <label>详细地址</label><input v-model="addrForm.detail" style="width:220px" />
          <button class="primary" @click="addAddress">添加地址</button>
        </div>
        <p class="muted" style="margin:0">
          包裹出库后地址变化: 在任务详情页对包裹做「地址改派」, 只追加记录, 不改原包裹。
        </p>
      </div>

      <div class="card">
        <h2>{{ selected.name }} — 按版次对账</h2>
        <p class="muted" style="margin-top:0">
          每个版次独立归集应寄/实收, 旧版样书不能抵扣新版应寄份数。
        </p>
        <div v-if="recon.length === 0" class="empty">暂无寄送任务</div>
        <table v-else>
          <thead>
            <tr>
              <th>任务号</th><th>图书</th><th>版次</th>
              <th>应寄</th><th>已寄</th><th>实收</th><th>差额</th><th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in recon" :key="r.id">
              <td>{{ r.task_no }}</td>
              <td>{{ r.book_title }}</td>
              <td><b>{{ r.edition_no }}</b></td>
              <td>{{ r.quantity_due }}</td>
              <td>{{ r.quantity_shipped }}</td>
              <td>{{ r.quantity_received }}</td>
              <td :style="{ color: r.outstanding ? '#c02222' : '#177245', fontWeight: 600 }">
                {{ r.outstanding }}
              </td>
              <td><span class="badge" :class="taskStatus[r.status].cls">{{ taskStatus[r.status].text }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { taskStatus } from '../labels'

const authors = ref([])
const selected = ref(null)
const recon = ref([])
const error = ref('')
const authorForm = reactive({ name: '', pen_name: '', phone: '' })
const addrForm = reactive({ recipient: '', phone: '', region: '', detail: '' })

async function load(keepSelection = true) {
  error.value = ''
  try {
    authors.value = await api.get('/api/authors')
    if (keepSelection && selected.value) {
      const fresh = authors.value.find((a) => a.id === selected.value.id)
      if (fresh) await select(fresh)
    }
  } catch (e) {
    error.value = e.message
  }
}

async function select(a) {
  selected.value = a
  recon.value = (await api.get(`/api/authors/${a.id}`)).reconciliation
}

async function addAuthor() {
  error.value = ''
  if (!authorForm.name) { error.value = '请填写姓名'; return }
  try {
    await api.post('/api/authors', { ...authorForm })
    authorForm.name = authorForm.pen_name = authorForm.phone = ''
    await load()
  } catch (e) { error.value = e.message }
}

async function addAddress() {
  error.value = ''
  try {
    await api.post(`/api/authors/${selected.value.id}/addresses`, { ...addrForm })
    addrForm.recipient = addrForm.phone = addrForm.region = addrForm.detail = ''
    await load()
  } catch (e) { error.value = e.message }
}

async function confirm(ad) {
  error.value = ''
  try {
    await api.post(`/api/addresses/${ad.id}/confirm`, { confirmed_by: '编辑' })
    await load()
  } catch (e) { error.value = e.message }
}

onMounted(() => load(false))
</script>
