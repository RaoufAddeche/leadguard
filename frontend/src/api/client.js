// Thin API client. Vite proxies /api to the backend in dev; nginx does it in Docker.

async function request(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })

  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      // FastAPI returns either a string detail or a list of validation errors.
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) {
        detail = body.detail
          .map((e) => `${(e.loc || []).slice(1).join('.')}: ${e.msg}`)
          .join(' · ')
      }
    } catch {
      /* keep the generic message */
    }
    throw new Error(detail)
  }

  return response.json()
}

export const api = {
  getConfig: () => request('/config'),
  getStats: () => request('/leads/stats'),
  listLeads: (status) => request(`/leads${status ? `?status=${status}` : ''}`),
  getLead: (id) => request(`/leads/${id}`),
  createLead: (payload) => request('/leads', { method: 'POST', body: JSON.stringify(payload) }),
  listReviews: () => request('/reviews'),
  reviewLead: (id, decision) =>
    request(`/reviews/${id}`, { method: 'POST', body: JSON.stringify(decision) }),
  getCrmLeads: () => request('/fake-crm/leads'),
}
