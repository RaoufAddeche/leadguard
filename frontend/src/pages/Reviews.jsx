import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { ErrorNotice, StatusBadge, humanize } from '../components/common'

export default function Reviews() {
  const [leads, setLeads] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    api.listReviews().then(setLeads).catch((e) => setError(e.message))
  }, [])

  return (
    <>
      <ErrorNotice error={error} />
      <div className="panel">
        <h2>Leads awaiting human review</h2>
        {leads.length === 0 ? (
          <p className="muted">Nothing to review — the queue is empty.</p>
        ) : (
          leads.map((lead) => (
            <Link to={`/leads/${lead.id}`} key={lead.id} className="lead-row">
              <div className="who">
                <div className="name">
                  {lead.full_name}{' '}
                  {lead.is_duplicate && <span className="badge muted">DUPLICATE</span>}
                </div>
                <div className="meta">
                  {humanize(lead.vertical)}
                  {lead.location && ` | ${lead.location}`}
                  <span className="mono"> · {lead.public_id}</span>
                </div>
              </div>
              <div className="score">{lead.score}</div>
              <StatusBadge status={lead.system_status} />
            </Link>
          ))
        )}
      </div>
    </>
  )
}
