<template>
  <div v-if="task">
    <div class="card">
      <div class="section-title">
        <h2>
          任务 {{ task.task_no }} — {{ task.author_name }} ·
          {{ task.book_title }} {{ task.edition_no }}
        </h2>
        <span class="badge" :class="taskStatus[task.status].cls" style="font-size:14px">
          {{ taskStatus[task.status].text }}
        </span>
      </div>
      <div class="stat-row">
        <div class="stat"><div class="num">{{ task.quantity_due }}</div><div class="lbl">应寄份数</div></div>
        <div class="stat"><div class="num">{{ task.quantity_shipped }}</div><div class="lbl">已出库(含补寄)</div></div>
        <div class="stat"><div class="num">{{ task.quantity_received }}</div><div class="lbl">作者实收</div></div>
        <div class="stat" :class="{ warn: task.outstanding > 0 }">
          <div class="num">{{ task.outstanding }}</div><div class="lbl">差额</div>
        </div>
      </div>
      <p class="muted">编辑: {{ task.created_by }} · 创建于 {{ fmtTime(task.created_at) }}
        <span v-if="task.note"> · 备注: {{ task.note }}</span>
      </p>

      <h3>仓库出库</h3>
      <div class="form-row">
        <label>数量</label>
        <input type="number" v-model.number="shipForm.quantity" min="1" style="width:90px" />
        <label>出库人</label>
        <input v-model="shipForm.shipped_by" style="width:110px" />
        <button class="primary" @click="doShip">出库并生成包裹</button>
        <span class="muted">出库时以作者「当前已确认地址」生成快照, 之后地址变化只追加改派记录</span>
      </div>
      <div v-if="error" class="error-banner">{{ error }}</div>
    </div>

    <div class="card">
      <h2>包裹（{{ task.packages.length }}）</h2>
      <div v-if="task.packages.length === 0" class="empty">尚未出库</div>
      <div v-for="p in task.packages" :key="p.id" class="pkg-card">
        <div class="pkg-head">
          <span class="no">{{ p.package_no }}</span>
          <span class="tag">运单 {{ p.tracking_no }}</span>
          <span class="tag">{{ p.quantity }} 册</span>
          <span v-if="p.parent_package_id" class="badge orange">
            补寄自 #{{ pkgNo(p.parent_package_id) }} · {{ reshipReason[p.reship_reason] || p.reship_reason }}
          </span>
          <span class="badge" :class="pkgStatus[p.status].cls">{{ pkgStatus[p.status].text }}</span>
          <div class="pkg-actions">
            <button v-if="!isTerminal(p)" class="sm" @click="doAdvance(p)">推进轨迹</button>
            <button v-if="!isTerminal(p)" class="sm" @click="openReroute(p)">地址改派</button>
            <button v-if="!p.receipt" class="sm primary" @click="openReceipt(p)">录入签收</button>
            <button v-if="p.receipt && p.status !== 'received'" class="sm danger" @click="openReship(p)">补寄</button>
          </div>
        </div>
        <div class="addr-line">
          📦 出库地址快照: {{ p.address.recipient }} {{ p.address.phone }}
          {{ p.address.region }}{{ p.address.detail }}
          <span class="muted">（不可修改, 地址变化请用「地址改派」）</span>
        </div>
        <div class="muted" style="margin-top:4px">
          出库: {{ fmtTime(p.shipped_at) }} · 操作员 {{ p.shipped_by }}
        </div>
        <div v-if="p.reship_note" class="muted" style="margin-top:4px">
          缺件原因: {{ p.reship_note }}
        </div>

        <div v-if="p.receipt" style="margin-top:8px">
          <span class="badge" :class="p.receipt.result === 'received' ? 'green' : (p.receipt.result === 'rejected' ? 'red' : 'orange')">
            回执: {{ receiptResult[p.receipt.result] }}
          </span>
          <span style="font-size:13px; margin-left:8px">
            实收 <b>{{ p.receipt.received_qty }}</b>/{{ p.quantity }} 册
            <span class="muted"> · {{ p.receipt.signed_by || '作者' }} · {{ fmtTime(p.receipt.created_at) }}</span>
          </span>
          <div v-if="p.receipt.note" class="muted">备注: {{ p.receipt.note }}</div>
        </div>

        <div v-if="p.reroutes.length" style="margin-top:8px">
          <div v-for="r in p.reroutes" :key="r.id" class="muted">
            🔀 改派记录: {{ r.recipient }} {{ r.phone }} {{ r.region }}{{ r.detail }}
            （{{ r.reason || '未填原因' }} · {{ r.created_by }} · {{ fmtTime(r.created_at) }}）
          </div>
        </div>

        <ul class="timeline">
          <li v-for="e in p.tracking_events" :key="e.id">
            <span class="t-time">{{ fmtTime(e.occurred_at) }}</span>
            {{ e.description }}
            <span v-if="e.location" class="muted">@ {{ e.location }}</span>
          </li>
        </ul>
      </div>
    </div>

    <!-- 签收弹窗 -->
    <div v-if="modal === 'receipt'" class="modal-mask" @click.self="modal = ''">
      <div class="modal">
        <h3>录入签收回执 — {{ activePkg.package_no }}</h3>
        <div class="form-row">
          <label>签收结果</label>
          <select v-model="receiptForm.result">
            <option value="received">正常签收</option>
            <option value="missing">少件</option>
            <option value="damaged">破损</option>
            <option value="rejected">拒收</option>
          </select>
        </div>
        <div class="form-row" v-if="receiptForm.result !== 'rejected'">
          <label>实收份数（共 {{ activePkg.quantity }} 册）</label>
          <input type="number" v-model.number="receiptForm.received_qty"
                 :max="activePkg.quantity" min="0" />
        </div>
        <div v-else class="muted">拒收不计入实收数量, 实收将记为 0</div>
        <div class="form-row">
          <label>签收人</label>
          <input v-model="receiptForm.signed_by" />
        </div>
        <div class="form-row">
          <label>备注（少件/破损/拒收原因）</label>
          <textarea v-model="receiptForm.note" rows="2"></textarea>
        </div>
        <p class="muted">回执幂等键: {{ receiptForm.idempotency_key }}（重复提交不会累加实收）</p>
        <div v-if="modalError" class="error-banner">{{ modalError }}</div>
        <div class="modal-actions">
          <button @click="modal = ''">取消</button>
          <button class="primary" @click="doReceipt">提交回执</button>
        </div>
      </div>
    </div>

    <!-- 补寄弹窗 -->
    <div v-if="modal === 'reship'" class="modal-mask" @click.self="modal = ''">
      <div class="modal">
        <h3>补寄 — 原包裹 {{ activePkg.package_no }}</h3>
        <p class="muted">
          原回执: {{ receiptResult[activePkg.receipt.result] }} ·
          实收 {{ activePkg.receipt.received_qty }}/{{ activePkg.quantity }} 册。
          补寄包裹将归入原任务并保留缺件原因。
        </p>
        <div class="form-row">
          <label>补寄数量</label>
          <input type="number" v-model.number="reshipForm.quantity" min="1" />
        </div>
        <div class="form-row">
          <label>缺件原因</label>
          <select v-model="reshipForm.reason">
            <option v-for="(label, key) in reshipReason" :key="key" :value="key">{{ label }}</option>
          </select>
        </div>
        <div class="form-row">
          <label>说明</label>
          <textarea v-model="reshipForm.note" rows="2"></textarea>
        </div>
        <div v-if="modalError" class="error-banner">{{ modalError }}</div>
        <div class="modal-actions">
          <button @click="modal = ''">取消</button>
          <button class="primary" @click="doReship">创建补寄包裹</button>
        </div>
      </div>
    </div>

    <!-- 改派弹窗 -->
    <div v-if="modal === 'reroute'" class="modal-mask" @click.self="modal = ''">
      <div class="modal">
        <h3>地址改派 — {{ activePkg.package_no }}</h3>
        <p class="muted">只追加改派记录, 不修改原包裹地址快照与出库记录。</p>
        <div class="form-row"><label>收件人</label><input v-model="rerouteForm.recipient" /></div>
        <div class="form-row"><label>电话</label><input v-model="rerouteForm.phone" /></div>
        <div class="form-row"><label>省市区</label><input v-model="rerouteForm.region" /></div>
        <div class="form-row"><label>详细地址</label><input v-model="rerouteForm.detail" /></div>
        <div class="form-row"><label>改派原因</label><input v-model="rerouteForm.reason" /></div>
        <div v-if="modalError" class="error-banner">{{ modalError }}</div>
        <div class="modal-actions">
          <button @click="modal = ''">取消</button>
          <button class="primary" @click="doReroute">追加改派记录</button>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="card"><div class="empty">加载中…</div></div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { fmtTime, pkgStatus, receiptResult, reshipReason, taskStatus, TERMINAL } from '../labels'

const props = defineProps({ id: { type: String, required: true } })

const task = ref(null)
const error = ref('')
const modal = ref('')
const modalError = ref('')
const activePkg = ref({})

const shipForm = reactive({ quantity: 1, shipped_by: '仓库' })
const receiptForm = reactive({})
const reshipForm = reactive({})
const rerouteForm = reactive({})

const isTerminal = (p) => TERMINAL.includes(p.status)
const pkgNo = (pid) => task.value?.packages.find((x) => x.id === pid)?.package_no || pid

async function load() {
  error.value = ''
  try {
    task.value = await api.get(`/api/tasks/${props.id}`)
  } catch (e) {
    error.value = e.message
  }
}

async function run(fn) {
  modalError.value = ''
  error.value = ''
  try {
    await fn()
    modal.value = ''
    await load()
  } catch (e) {
    if (modal.value) modalError.value = e.message
    else error.value = e.message
  }
}

const doShip = () => run(() =>
  api.post(`/api/tasks/${props.id}/packages`, { ...shipForm }))

function openReceipt(p) {
  activePkg.value = p
  Object.assign(receiptForm, {
    result: 'received', received_qty: p.quantity, note: '',
    signed_by: task.value.author_name,
    idempotency_key: crypto.randomUUID(),
  })
  modalError.value = ''
  modal.value = 'receipt'
}
const doReceipt = () => run(() =>
  api.post(`/api/packages/${activePkg.value.id}/receipt`, { ...receiptForm }))

function openReship(p) {
  activePkg.value = p
  Object.assign(reshipForm, {
    quantity: Math.max(p.quantity - p.receipt.received_qty, 1),
    reason: p.receipt.result,
    note: '',
  })
  modalError.value = ''
  modal.value = 'reship'
}
const doReship = () => run(() =>
  api.post(`/api/packages/${activePkg.value.id}/reship`, { ...reshipForm }))

function openReroute(p) {
  activePkg.value = p
  Object.assign(rerouteForm, {
    recipient: p.address.recipient, phone: p.address.phone,
    region: p.address.region, detail: '', reason: '',
  })
  modalError.value = ''
  modal.value = 'reroute'
}
const doReroute = () => run(() =>
  api.post(`/api/packages/${activePkg.value.id}/reroute`, { ...rerouteForm }))

const doAdvance = (p) => run(() =>
  api.post(`/api/packages/${p.id}/tracking/advance`))

onMounted(load)
</script>
