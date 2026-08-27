'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState, useTransition } from 'react'
import { submitTicket, type TicketSummary } from '@/lib/api'

const STATUS_TONE: Record<string, string> = {
  resolved: 'ok',
  in_progress: 'info',
  awaiting_approval: 'warn',
  rejected: 'info',
  blocked: 'bad',
  failed: 'bad',
  received: 'info',
}

const EXAMPLE =
  'Merhaba, ORD-0000028 numaralı siparişim bugün geldi ama içindeki vazo kırılmıştı. ' +
  'İade istiyorum, teşekkürler.'

export function Inbox({
  tickets,
  error: initialError,
}: {
  tickets: TicketSummary[]
  error: string | null
}) {
  const router = useRouter()
  const [message, setMessage] = useState(EXAMPLE)
  const [error, setError] = useState<string | null>(initialError)
  const [busy, setBusy] = useState(false)
  const [pending, startTransition] = useTransition()

  async function submit() {
    setBusy(true)
    setError(null)
    const response = await submitTicket(message)
    setBusy(false)

    if (!response.ok) {
      setError(response.error)
      return
    }
    // Re-run the server component rather than keeping a second copy of the list.
    startTransition(() => router.refresh())
  }

  return (
    <>
      <section className="panel">
        <h2>Submit a ticket</h2>
        <p className="lede">
          This runs the real graph: guardrails, tool calls, policy, and a human gate if the
          case needs one.
        </p>
        <textarea
          className="editor"
          rows={4}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
        />
        <div className="actions">
          <button type="button" className="primary" onClick={submit} disabled={busy}>
            {busy ? 'Resolving…' : 'Submit'}
          </button>
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

      <section className="panel">
        <h2>Inbox</h2>
        {tickets.length === 0 ? (
          <p className="quiet">No tickets yet.</p>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>Ticket</th>
                <th>Status</th>
                <th>Intent</th>
                <th>Order</th>
                <th>Amount</th>
                <th>Flags</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {tickets.map((ticket) => (
                <tr key={ticket.ticket_id}>
                  <td>
                    <Link href={`/tickets/${ticket.ticket_id}`}>{ticket.ticket_id}</Link>
                    <span className="preview">{ticket.preview}</span>
                  </td>
                  <td>
                    <span className={`pill ${STATUS_TONE[ticket.status] ?? 'info'}`}>
                      {ticket.status.replace(/_/g, ' ')}
                    </span>
                    {ticket.deliberated && <span className="pill info">argued</span>}
                  </td>
                  <td>{ticket.intent?.replace(/_/g, ' ') ?? '—'}</td>
                  <td className="mono">{ticket.order_id ?? '—'}</td>
                  <td className="mono">{ticket.amount_eur ? `€${ticket.amount_eur}` : '—'}</td>
                  <td className="mono">{ticket.guardrail_flags || '—'}</td>
                  <td className="mono">${Number(ticket.cost_usd).toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}
