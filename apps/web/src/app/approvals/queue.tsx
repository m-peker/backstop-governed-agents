'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState, useTransition } from 'react'
import { decideApproval, type ApprovalItem } from '@/lib/api'

export function Queue({
  items,
  error: initialError,
}: {
  items: ApprovalItem[]
  error: string | null
}) {
  const router = useRouter()
  const [approver, setApprover] = useState('ops.supervisor')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(initialError)
  const [pending, startTransition] = useTransition()

  async function decide(ticketId: string, approved: boolean) {
    setBusy(ticketId)
    setError(null)
    const response = await decideApproval(ticketId, approved, approver)
    setBusy(null)

    if (!response.ok) {
      setError(response.error)
      return
    }
    startTransition(() => router.refresh())
  }

  return (
    <>
      <section className="panel">
        <h2>Approval queue</h2>
        <p className="lede">
          Cases the system would not settle on its own. Each one paused mid-graph and will
          resume exactly where it stopped.
        </p>
        <div className="actions">
          <label className="field">
            <span>Deciding as</span>
            <input value={approver} onChange={(event) => setApprover(event.target.value)} />
          </label>
          <button
            type="button"
            disabled={pending}
            onClick={() => startTransition(() => router.refresh())}
          >
            Refresh
          </button>
        </div>
        {error && <p className="alert">{error}</p>}
      </section>

      {items.length === 0 ? (
        <section className="panel muted">
          <p>Nothing waiting.</p>
        </section>
      ) : (
        items.map((item) => {
          const deliberation = item.request.deliberation as
            | { dissent?: string; rationale?: string; skipped?: boolean }
            | null

          return (
            <section className="panel" key={item.ticket_id}>
              <h2>
                <Link href={`/tickets/${item.ticket_id}`}>{item.ticket_id}</Link>
              </h2>
              <p className="quiet">{item.preview}</p>

              <dl className="controls">
                <Field term="Proposed" value={item.request.proposed_resolution ?? '—'} />
                <Field
                  term="Amount"
                  value={item.request.amount_eur ? `€${item.request.amount_eur}` : '—'}
                />
                <Field term="Policy" value={item.request.policy_effect ?? '—'} />
                <Field term="Clauses" value={item.request.clauses.join(', ') || '—'} />
              </dl>

              {item.request.policy_explanation && (
                <p className="quiet">
                  <strong>Why it stopped:</strong> {item.request.policy_explanation}
                </p>
              )}

              {item.request.rationale && (
                <p className="quiet">
                  <strong>The system&rsquo;s reasoning:</strong> {item.request.rationale}
                </p>
              )}

              {item.request.concerns.length > 0 && (
                <>
                  <p className="quiet">
                    <strong>Recorded concerns</strong>
                  </p>
                  <ul className="plain">
                    {item.request.concerns.map((concern, index) => (
                      <li key={index}>{concern}</li>
                    ))}
                  </ul>
                </>
              )}

              {deliberation && !deliberation.skipped && (
                <div className="argued">
                  <p className="quiet">
                    <strong>Argued in the room.</strong> {deliberation.rationale}
                  </p>
                  {deliberation.dissent && (
                    <p className="quiet">
                      <strong>The case against:</strong> {deliberation.dissent}
                    </p>
                  )}
                </div>
              )}

              <div className="actions">
                <button
                  type="button"
                  className="primary"
                  disabled={busy === item.ticket_id}
                  onClick={() => void decide(item.ticket_id, true)}
                >
                  Approve
                </button>
                <button
                  type="button"
                  className="danger"
                  disabled={busy === item.ticket_id}
                  onClick={() => void decide(item.ticket_id, false)}
                >
                  Decline
                </button>
              </div>
            </section>
          )
        })
      )}
    </>
  )
}

function Field({ term, value }: { term: string; value: string }) {
  return (
    <div className="control">
      <dt>{term}</dt>
      <dd>
        <strong>{value}</strong>
      </dd>
    </div>
  )
}
