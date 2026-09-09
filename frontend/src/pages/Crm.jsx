import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { ErrorNotice, StatusBadge } from '../components/common'

// Shows what the simulated downstream CRM actually received.
export default function Crm() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.getCrmLeads().then(setData).catch((e) => setError(e.message))
  }, [])

  return (
    <>
      <ErrorNotice error={error} />
      <div className="panel">
        <h2>Fake CRM — received leads ({data?.count ?? 0})</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          Only QUALIFIED leads are pushed downstream. This store is in-memory and resets when the
          backend restarts.
        </p>
        {data?.leads?.length
          ? data.leads.map((lead) => (
              <div className="lead-row" key={lead.crm_id}>
                <div className="who">
                  <div className="name">
                    {lead.firstname} {lead.lastname}
                  </div>
                  <div className="meta">
                    {lead.team} · {lead.project_type}
                    <span className="mono"> · {lead.lead_id} → {lead.crm_id}</span>
                  </div>
                </div>
                <div className="score">{lead.score}</div>
                <StatusBadge status={lead.status} />
              </div>
            ))
          : !error && <p className="muted">Nothing synchronized yet.</p>}
      </div>
    </>
  )
}
