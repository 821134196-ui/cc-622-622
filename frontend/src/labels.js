export const taskStatus = {
  pending: { text: '待出库', cls: 'gray' },
  shipping: { text: '寄送中', cls: 'blue' },
  completed: { text: '已完成', cls: 'green' },
  mismatch: { text: '数量不一致', cls: 'red' },
}

export const pkgStatus = {
  shipped: { text: '已出库', cls: 'blue' },
  in_transit: { text: '运输中', cls: 'blue' },
  out_for_delivery: { text: '派送中', cls: 'blue' },
  received: { text: '已签收', cls: 'green' },
  missing: { text: '少件', cls: 'red' },
  damaged: { text: '破损', cls: 'orange' },
  rejected: { text: '已拒收', cls: 'red' },
}

export const receiptResult = {
  received: '正常签收',
  missing: '少件',
  damaged: '破损',
  rejected: '拒收',
}

export const reshipReason = {
  missing: '少件',
  damaged: '破损',
  rejected: '拒收',
  other: '其他',
}

export const TERMINAL = ['received', 'missing', 'damaged', 'rejected']

export function fmtTime(iso) {
  if (!iso) return '-'
  return iso.replace('T', ' ').slice(0, 16)
}
