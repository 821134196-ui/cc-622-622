<script setup>
import { ref } from 'vue'
import { api } from '../api'
import { fmtTime, badge, TASK_STATUS, PARCEL_STATE, RESHIP_REASON } from '../labels'

const props = defineProps({
  task: Object,
  authors: Array,
  editions: Array,
})
const emit = defineEmits(['changed', 'flash'])

const authorName = (id) => props.authors.find((a) => a.id === id)?.name || `#${id}`
const editionLabel = (id) => {
  const e = props.editions.find((x) => x.id === id)
  return e ? `《${e.title}》${e.edition}` : `#${id}`
}

// ---- 地址确认 ----
const addrForm = ref({ recipient: '', phone: '', address: '' })
async function confirmAddress() {
  try {
    await api.post(`/api/tasks/${props.task.id}/confirm-address`, addrForm.value)
    emit('flash', '地址已确认')
    emit('changed')
  } catch (e) { emit('flash', e.message, true) }
}

// ---- 原寄出库 ----
const outboundQty = ref(props.task.required_qty)
async function outbound() {
  try {
    const p = await api.post('/api/outbound', {
      task_id: props.task.id, qty: Number(outboundQty.value),
    })
    emit('flash', `已出库，包裹单号 ${p.tracking_no}`)
    emit('changed')
  } catch (e) { emit('flash', e.message, true) }
}

// ---- 签收 ----
const receiptForms = ref({})
function receiptForm(pid, parcelQty) {
  if (!receiptForms.value[pid]) {
    receiptForms.value[pid] = {
      receipt_no: '', action: 'signed',
      received_qty: parcelQty, damaged_qty: 0, note: '',
    }
  }
  return receiptForms.value[pid]
}
async function submitReceipt(parcelId) {
  const f = receiptForms.value[parcelId]
  const payload = {
    parcel_id: parcelId,
    action: f.action,
    received_qty: f.action === 'signed' ? Number(f.received_qty) : 0,
    damaged_qty: f.action === 'signed' ? Number(f.damaged_qty) : 0,
    note: f.note,
  }
  if (f.receipt_no) payload.receipt_no = f.receipt_no
  try {
    const r = await api.post('/api/receipts', payload)
    if (!f.receipt_no) f.receipt_no = r.receipt_no
    emit('flash', r.duplicate ? '重复回执：已忽略，实收数量不变' : '回执已提交')
    emit('changed')
  } catch (e) { emit('flash', e.message, true) }
}

// ---- 改派 ----
const redirectForms = ref({})
function redirectForm(p) {
  if (!redirectForms.value[p.id]) {
    redirectForms.value[p.id] = {
      parcel_id: p.id, new_recipient: p.recipient,
      new_phone: p.phone, new_address: '', reason: '',
    }
  }
  return redirectForms.value[p.id]
}
async function redirectAddr(parcelId) {
  try {
    await api.post(`/api/parcels/${parcelId}/redirect`, redirectForms.value[parcelId])
    emit('flash', '已追加改派记录，原包裹地址保持不变')
    emit('changed')
  } catch (e) { emit('flash', e.message, true) }
}

// ---- 补寄 ----
const reshipForms = ref({})
function reshipForm(p) {
  if (!reshipForms.value[p.id]) {
    const shortage = p.receipts.reduce((s, r) => s + r.shortage_qty, 0)
    const damaged = p.receipts.reduce((s, r) => s + r.damaged_qty, 0)
    const reason = shortage > 0 ? 'shortage' : damaged > 0 ? 'damaged' : 'rejected'
    reshipForms.value[p.id] = {
      source_parcel_id: p.id,
      reason_type: reason,
      qty: shortage || damaged || p.qty,
      reason_detail: '',
      recipient: p.recipient, phone: p.phone, address: p.address,
    }
  }
  return reshipForms.value[p.id]
}
async function reship(parcelId) {
  const f = reshipForms.value[parcelId]
  try {
    const r = await api.post('/api/reshipments', f)
    emit('flash', `补寄包裹已生成（挂在任务 ${props.task.code} 下，#${r.new_parcel_id}）`)
    emit('changed')
  } catch (e) { emit('flash', e.message, true) }
}

// ---- 模拟轨迹 ----
async function advance(pid) {
  try {
    await api.post(`/api/parcels/${pid}/advance-tracking`)
    emit('flash', '快递轨迹已更新')
    emit('changed')
  } catch (e) { emit('flash', e.message, true) }
}

const t = props.task
const statusBadge = badge(TASK_STATUS, t.status)
</script>

<template>
  <div>
    <!-- 任务头 -->
    <div class="row" style="margin-bottom: 10px">
      <h3 style="margin: 0">
        任务 <span class="mono">{{ t.code }}</span>
        <span class="badge" :class="statusBadge.cls">{{ statusBadge.text }}</span>
      </h3>
      <div class="spacer"></div>
      <span class="muted small-text">创建于 {{ fmtTime(t.created_at) }}</span>
    </div>
    <div class="muted small-text" style="margin-bottom: 10px">
      作者：<b>{{ authorName(t.author_id) }}</b> ｜ 版次：<b>{{ editionLabel(t.edition_id) }}</b>
      <span v-if="t.note"> ｜ 备注：{{ t.note }}</span>
    </div>

    <!-- 数量核对面板 -->
    <div class="row" style="gap: 8px; margin-bottom: 6px">
      <div class="metric" :class="t.received_qty >= t.required_qty ? 'ok' : 'bad'">
        <div class="v">{{ t.required_qty }}</div><div class="l">应寄（该版次）</div>
      </div>
      <div class="metric"><div class="v">{{ t.original_shipped_qty }}</div><div class="l">原寄出库</div></div>
      <div class="metric warn"><div class="v">{{ t.reship_shipped_qty }}</div><div class="l">补寄出库</div></div>
      <div class="metric" :class="t.received_qty >= t.required_qty ? 'ok' : 'bad'">
        <div class="v">{{ t.received_qty }}</div><div class="l">作者实收</div>
      </div>
      <div class="metric"><div class="v">{{ t.shortage_total }}</div><div class="l">少件</div></div>
      <div class="metric"><div class="v">{{ t.damaged_total }}</div><div class="l">破损</div></div>
      <div class="metric"><div class="v">{{ t.rejected_count }}</div><div class="l">拒收包裹</div></div>
      <div class="metric"><div class="v">{{ t.in_transit_count }}</div><div class="l">在途</div></div>
    </div>
    <div class="small-text muted" style="margin-bottom: 10px">
      数量核对只在同一任务、同一版次内汇总；其他版次（含旧版）样书不参与抵扣。
    </div>

    <!-- 地址确认 -->
    <div v-if="!t.address_confirmed_at" class="card" style="background: #fffbeb">
      <h3>① 编辑确认作者地址</h3>
      <div class="grid2">
        <label class="field"><span>收件人</span>
          <input v-model="addrForm.recipient" :placeholder="authorName(t.author_id)" /></label>
        <label class="field"><span>电话</span><input v-model="addrForm.phone" /></label>
      </div>
      <label class="field" style="margin-top: 8px"><span>收件地址</span>
        <textarea v-model="addrForm.address"></textarea></label>
      <div style="margin-top: 8px">
        <button class="btn" @click="confirmAddress">确认地址，交仓库出库</button>
      </div>
    </div>

    <div v-else class="small-text muted" style="margin: 6px 0 10px">
      任务级地址（{{ fmtTime(t.address_confirmed_at) }} 确认）：
      {{ t.confirmed_recipient }}，{{ t.confirmed_phone }}，{{ t.confirmed_address }}
    </div>

    <!-- 原寄出库 -->
    <div v-if="t.address_confirmed_at && !t.parcels.some((p) => !p.is_reship)" class="card">
      <h3>② 仓库按版次出库（原寄）</h3>
      <div class="row">
        <label class="field"><span>出库份数（{{ editionLabel(t.edition_id) }}）</span>
          <input class="small" type="number" min="1" v-model.number="outboundQty" /></label>
        <button class="btn" @click="outbound">生成包裹与出库记录</button>
      </div>
    </div>

    <!-- 包裹列表 -->
    <h3 style="margin: 14px 0 4px">包裹与签收 / 补寄记录</h3>
    <div v-for="p in t.parcels" :key="p.id" class="parcel" :class="{ reship: p.is_reship }">
      <div class="row">
        <span class="badge purple" v-if="p.is_reship">补寄</span>
        <span class="badge gray" v-else>原寄</span>
        <b class="mono">{{ p.tracking_no }}</b>
        <span class="badge" :class="badge(PARCEL_STATE, p.state).cls">
          {{ badge(PARCEL_STATE, p.state).text }}
        </span>
        <div class="spacer"></div>
        <span class="small-text muted">
          出库 {{ fmtTime(p.outbound_at) }} ｜ 出库 {{ p.qty }} 份 ｜ 实收
          <b :style="p.received_qty >= p.qty ? 'color:var(--ok)' : 'color:var(--danger)'">
            {{ p.received_qty }}
          </b> 份
        </span>
      </div>

      <!-- 不可变地址快照 + 改派留痕 -->
      <div class="small-text" style="margin-top: 6px">
        <span class="muted">出库地址快照（不可修改）：</span>
        {{ p.recipient }}，{{ p.phone }}，{{ p.address }}
      </div>
      <div v-for="r in p.redirects" :key="r.id" class="small-text"
           style="margin-top: 4px; color: var(--purple)">
        ↳ 改派 {{ fmtTime(r.created_at) }}：{{ r.old_recipient }} / {{ r.old_address }}
        → <b>{{ r.new_recipient }} / {{ r.new_address }}</b>
        <span v-if="r.reason">（{{ r.reason }}）</span>
      </div>

      <!-- 回执 -->
      <div v-for="rc in p.receipts" :key="rc.id" class="small-text" style="margin-top: 6px">
        <span v-if="rc.action === 'signed'" style="color: var(--ok)">
          ✓ 签收 {{ fmtTime(rc.created_at) }}：实收 {{ rc.received_qty }} 份
          <template v-if="rc.shortage_qty">，少件 {{ rc.shortage_qty }} 份</template>
          <template v-if="rc.damaged_qty">，破损 {{ rc.damaged_qty }} 份</template>
        </span>
        <span v-else style="color: var(--danger)">
          ✗ 拒收 {{ fmtTime(rc.created_at) }}：{{ rc.note || '无说明' }}（不计入实收）
        </span>
        <span class="muted mono">（回执号 {{ rc.receipt_no }}）</span>
      </div>

      <!-- 操作区 -->
      <div v-if="p.state === 'in_transit'" class="divider"></div>
      <div v-if="p.state === 'in_transit'" class="grid2">
        <!-- 签收回执 -->
        <div>
          <div class="small-text muted" style="margin-bottom: 4px">作者签收回执：</div>
          <div class="row wrap" style="gap: 6px">
            <label class="field"><span>回执编号（留空则自动生成）</span>
              <input style="width: 190px" v-model="receiptForm(p.id, p.qty).receipt_no"
                     placeholder="如 RT2026100501" /></label>
            <label class="field"><span>结果</span>
              <select style="width: 110px" v-model="receiptForm(p.id, p.qty).action">
                <option value="signed">签收</option>
                <option value="rejected">拒收</option>
              </select></label>
            <template v-if="receiptForm(p.id, p.qty).action === 'signed'">
              <label class="field"><span>实收份数</span>
                <input class="small" type="number" min="0" :max="p.qty"
                       v-model.number="receiptForm(p.id, p.qty).received_qty" /></label>
              <label class="field"><span>其中破损</span>
                <input class="small" type="number" min="0" :max="p.qty"
                       v-model.number="receiptForm(p.id, p.qty).damaged_qty" /></label>
            </template>
          </div>
          <label class="field" style="margin-top: 6px"><span>备注 / 少件破损说明</span>
            <input v-model="receiptForm(p.id, p.qty).note" /></label>
          <div style="margin-top: 6px" class="row">
            <button class="btn mini" @click="submitReceipt(p.id)">提交回执</button>
            <button class="btn mini ghost" @click="advance(p.id)">模拟快递推进</button>
          </div>
        </div>

        <!-- 改派 -->
        <div>
          <div class="small-text muted" style="margin-bottom: 4px">
            出库后地址变化（只追加改派记录）：
          </div>
          <div class="grid2">
            <label class="field"><span>新收件人</span>
              <input v-model="redirectForm(p).new_recipient" /></label>
            <label class="field"><span>新电话</span>
              <input v-model="redirectForm(p).new_phone" /></label>
          </div>
          <label class="field" style="margin-top: 6px"><span>新地址</span>
            <input v-model="redirectForm(p).new_address" /></label>
          <label class="field" style="margin-top: 6px"><span>改派原因</span>
            <input v-model="redirectForm(p).reason" /></label>
          <div style="margin-top: 6px">
            <button class="btn mini purple" @click="redirectAddr(p.id)">追加改派记录</button>
          </div>
        </div>
      </div>

      <!-- 已了结：补寄 -->
      <div v-if="p.state !== 'in_transit'" class="divider"></div>
      <div v-if="p.state !== 'in_transit'">
        <div class="small-text muted" style="margin-bottom: 4px">补寄（新包裹继续挂在本任务下，原因随记录冻结）：</div>
        <div class="row wrap" style="gap: 6px">
          <label class="field"><span>缺件原因</span>
            <select style="width: 120px" v-model="reshipForm(p).reason_type">
              <option value="shortage">少件</option>
              <option value="damaged">破损</option>
              <option value="rejected">拒收重寄</option>
            </select></label>
          <label class="field"><span>补寄份数</span>
            <input class="small" type="number" min="1" v-model.number="reshipForm(p).qty" /></label>
          <label class="field" style="flex: 1; min-width: 220px"><span>原因详情（留痕）</span>
            <input v-model="reshipForm(p).reason_detail" /></label>
          <button class="btn mini warn" @click="reship(p.id)">生成补寄包裹</button>
        </div>
        <details class="small-text" style="margin-top: 6px">
          <summary class="muted clickable">补寄收件地址（默认沿用原包裹，可调整）</summary>
          <div class="grid2" style="margin-top: 6px">
            <label class="field"><span>收件人</span><input v-model="reshipForm(p).recipient" /></label>
            <label class="field"><span>电话</span><input v-model="reshipForm(p).phone" /></label>
          </div>
          <label class="field" style="margin-top: 6px"><span>地址</span>
            <input v-model="reshipForm(p).address" /></label>
        </details>
      </div>

      <!-- 轨迹 -->
      <details class="small-text" style="margin-top: 8px">
        <summary class="muted clickable">快递轨迹（本地模拟，{{ p.tracking_events.length }} 条）</summary>
        <ul class="timeline">
          <li v-for="e in [...p.tracking_events].reverse()" :key="e.id">
            <div>{{ e.description }} <span class="muted">· {{ e.location }}</span></div>
            <div class="t">{{ fmtTime(e.occurred_at) }}</div>
          </li>
        </ul>
      </details>
    </div>
  </div>
</template>
