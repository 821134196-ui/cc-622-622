export const TASK_STATUS = {
  pending_address: { text: '待确认地址', cls: 'gray' },
  ready: { text: '待出库', cls: 'amber' },
  shipping: { text: '寄送中', cls: 'blue' },
  completed: { text: '已完成', cls: 'green' },
  abnormal: { text: '数量异常', cls: 'red' },
}

export const PARCEL_STATE = {
  in_transit: { text: '在途', cls: 'blue' },
  signed: { text: '已签收', cls: 'green' },
  rejected: { text: '已拒收', cls: 'red' },
}

export const RESHIP_REASON = {
  shortage: '少件补寄',
  damaged: '破损补寄',
  rejected: '拒收重寄',
}

export function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}`
}

export function badge(map, key) {
  return map[key] || { text: key, cls: 'gray' }
}
