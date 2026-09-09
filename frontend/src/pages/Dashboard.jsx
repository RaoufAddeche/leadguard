import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { ErrorNotice, StatusBadge, humanize } from '../components/common'

const FILTERS = ['ALL', 'QUALIFIED', 'REVIEW', 'REJECTED']

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [leads, setLeads] = useState([])
  const [filter, setFilter] = useState('ALL')
  const [error, setError] = useState(null)

  useEffect(() => {
    Promise.all([api.getStats(), api.listLeads(filter === 'ALL' ? null : filter)])
      .then(([s, l]) => {
        setStats(s)
        setLeads(l)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }, [filter])

  return (
    <>
      <ErrorNotice error={error} />

      <div className="grid cols-4">
        <div className="stat">
          <div className="label">Leads received</div>
          <div className="value">{stats?.total ?? '—'}</div>
        </div>
        <div className="stat">
          <div className="label">Qualified</div>
          <div className="value green">{stats?.qualified ?? '—'}</div>
        </div>
        <div className="stat">
          <div className="label">Human review</div>
          <div className="value amber">{stats?.review ?? '—'}</div>
        </div>
        <div className="stat">
          <div className="label">Rejected</div>
          <div className="value red">{stats?.rejected ?? '—'}</div>
        </div>
      </div>

      <div className="grid cols-4" style={{ marginTop: 18 }}>
        <div className="stat">
          <div className="label">Qualification rate</div>
          <div className="value">{stats ? `${stats.qualification_rate}%` : '—'}</div>
        </div>
        <div className="stat">
          <div className="label">Average score</div>
          <div className="value">{stats?.average_score ?? '—'}</div>
        </div>
        <div className="stat">
          <div className="label">Duplicates detected</div>
          <div className="value">{stats?.duplicates ?? '—'}</div>
        </div>
        <div className="stat">
          <div className="label">Pending review</div>
          <div className="value amber">
            {leads.filter((l) => l.system_status === 'REVIEW' && !l.human_status).length}
          </div>
        </div>
      </div>

      {stats?.verticals?.length > 0 && (
        <div className="panel" style={{ marginTop: 18 }}>
          <h2>By vertical</h2>
          <div style={{ overflowX: 'auto' }}>
            <table className="vtable">
              <thead>
                <tr>
                  <th>Vertical</th>
                  <th>Leads</th>
                  <th>Qualified</th>
                  <th>Review</th>
                  <th>Rejected</th>
                  <th>Avg score</th>
                </tr>
              </thead>
              <tbody>
                {stats.verticals.map((v) => (
                  <tr key={v.vertical}>
                    <td>{humanize(v.vertical)}</td>
                    <td>{v.total}</td>
                    <td style={{ color: 'var(--green)' }}>{v.qualified}</td>
                    <td style={{ color: 'var(--amber)' }}>{v.review}</td>
                    <td style={{ color: 'var(--red)' }}>{v.rejected}</td>
                    <td>{v.average_score}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="panel" style={{ marginTop: 18 }}>
        <div className="row-between">
          <h2 style={{ margin: 0 }}>Recent leads</h2>
          <div className="btn-row">
            {FILTERS.map((f) => (
              <button
                key={f}
                className="chip"
                onClick={() => setFilter(f)}
                style={f === filter ? { borderColor: 'var(--accent)', color: 'var(--text)' } : {}}
              >
                {f}
              </button>
            ))}
          </div>
        </div>

        <div style={{ marginTop: 12 }}>
          {leads.length === 0 && <p className="muted">No leads yet. Create one to get started.</p>}
          {leads.map((lead) => (
            <Link to={`/leads/${lead.id}`} key={lead.id} className="lead-row">
              <div className="who">
                <div className="name">
                  {lead.full_name}{' '}
                  {lead.is_duplicate && <span className="badge muted">DUPLICATE</span>}
                </div>
                <div className="meta">
                  {humanize(lead.vertical)}
                  {lead.location && ` | ${lead.location}`}
                  {lead.routed_team && ` → ${lead.routed_team}`}
                  <span className="mono"> · {lead.public_id}</span>
                </div>
              </div>
              <div className="score">{lead.score}</div>
              <StatusBadge status={lead.status} />
            </Link>
          ))}
        </div>
      </div>
    </>
  )
}
