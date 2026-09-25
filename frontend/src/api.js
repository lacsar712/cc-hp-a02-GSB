export function getToken() {
  return localStorage.getItem('herb_token') || ''
}

export function getRole() {
  return localStorage.getItem('herb_role') || ''
}

export async function api(path, options = {}) {
  const token = getToken()
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || '请求失败')
  return data
}

export function clearAuth() {
  localStorage.clear()
}
