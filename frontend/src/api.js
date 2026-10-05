// 极简 API 封装
async function request(method, url, body) {
  const resp = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await resp.json().catch(() => null)
  if (!resp.ok) {
    throw new Error(data?.detail || `请求失败 ${resp.status}`)
  }
  return data
}

export const api = {
  get: (u) => request('GET', u),
  post: (u, b) => request('POST', u, b),
}
