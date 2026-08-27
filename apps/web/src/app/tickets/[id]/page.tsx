/**
 * One ticket, with everything that happened to it.
 *
 * The order of the sections is the order of the pipeline, so reading top to
 * bottom is reading the decision being made. The audit table at the end is the
 * record itself, not a summary of it.
 */

import Link from 'next/link'
import { getTicket, type PolicyRuling, type TicketDetail } from '@/lib/api'

export const dynamic = 'force-dynamic'

const OUTCOME_TONE: Record<string, string> = {
  allowed: 'ok',
  replayed: 'info',
  refused: 'warn',
  failed: 'bad',
}

const ACTION_TONE: Record<string, string> = {
  allow: 'ok',
  annotate: 'info',
  escalate: 'warn',
  block: 'bad',
}

export default async function TicketPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const response = await getTicket(id)

  if (!response.ok) {
    return (
      <section className="panel">
        <h2>Ticket {id}</h2>
        <p className="alert">{response.error}</p>
        <Link href="/tickets">Back to the inbox</Link>
      </section>
    )
  }

  const ticket = response.data
  const decision = ticket.policy_decision

  return (
    <>
      <section className="panel">
        <h2>{ticket.ticket_id}</h2>
        <dl className="controls">
          <Field term="Status" value={ticket.status?.replace(/_/g, ' ') ?? '—'} />
          <Field term="Intent" value={ticket.intent?.replace(/_/g, ' ') ?? '—'} />
          <Field term="Order" value={ticket.order_id ?? '—'} />
          <Field term="Cost" value={`$${Number(ticket.cost_usd).toFixed(4)}`} />
        </dl>
        {ticket.failure && <p className="alert">{ticket.failure}</p>}
      </section>

      <section className="panel">
        <h2>1 · What arrived, and what the model saw</h2>
        <p className="quiet">
          The raw message is kept for the record and never placed in a prompt. The second
          block is what a model actually received.
        </p>
        <pre className="code">{ticket.raw_message ?? '—'}</pre>
        {ticket.pii_placeholders.length > 0 && (
          <p className="quiet">
            Personal data replaced by {ticket.pii_placeholders.length} placeholder(s):{' '}
            <span className="mono">{ticket.pii_placeholders.join(', ')}</span>
          </p>
        )}
        <pre className="code">{ticket.safe_message ?? '—'}</pre>
      </section>

      {ticket.guardrail_events.length > 0 && (
        <section className="panel">
          <h2>2 · Guardrail findings</h2>
          <ul className="findings">
            {ticket.guardrail_events.map((event, index) => (
              <li key={index} className={ACTION_TONE[event.action] ?? 'info'}>
                <span className="detector">{event.detector.replace(/_/g, ' ')}</span>
                <span className="summary">{event.summary}</span>
                <span className="tag">{event.action}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {ticket.fact_gaps.length > 0 && (
        <section className="panel">
          <h2>Facts that could not be gathered</h2>
          <ul className="plain">
            {ticket.fact_gaps.map((gap, index) => (
              <li key={index}>{gap}</li>
            ))}
          </ul>
        </section>
      )}

      {ticket.policy_refs.length > 0 && (
        <section className="panel">
          <h2>3 · Policy retrieved</h2>
          <ul className="clauses">
            {ticket.policy_refs.map((clause) => (
              <li key={clause.clause_id}>
                <span className="mono">{clause.clause_id}</span>
                <span>{clause.text}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {ticket.assessment && (
        <section className="panel">
          <h2>4 · What the model proposed</h2>
          <dl className="controls">
            <Field term="Resolution" value={String(ticket.assessment.resolution ?? '—')} />
            <Field
              term="Amount"
              value={ticket.assessment.amount_eur ? `€${ticket.assessment.amount_eur}` : '—'}
            />
            <Field
              term="Confidence"
              value={
                typeof ticket.assessment.confidence === 'number'
                  ? `${(ticket.assessment.confidence * 100).toFixed(0)}%`
                  : '—'
              }
            />
            <Field
              term="Cited"
              value={(ticket.assessment.cited_clauses as string[] | undefined)?.join(', ') || '—'}
            />
          </dl>
          {typeof ticket.assessment.rationale === 'string' && (
            <p className="quiet">{ticket.assessment.rationale}</p>
          )}
        </section>
      )}

      {decision && (
        <section className="panel">
          <h2>5 · What the policy engine decided</h2>
          <p className="lede">
            The model proposes; this decides. Deterministic code, outside any prompt.
          </p>
          <div className={`verdict ${decision.effect === 'permit' ? 'ok' : 'warn'}`}>
            <strong>{decision.effect.replace(/_/g, ' ').toUpperCase()}</strong>
            <span>{decision.explanation || 'No rule objected.'}</span>
          </div>
          {decision.rulings.length > 0 && (
            <ul className="findings">
              {decision.rulings.map((ruling: PolicyRuling) => (
                <li key={ruling.rule_id} className={ruling.effect === 'permit' ? 'ok' : 'warn'}>
                  <span className="detector">{ruling.rule_id}</span>
                  <span className="summary">{ruling.reason}</span>
                  <span className="tag">
                    {ruling.ambiguous ? 'policy conflict' : ruling.clauses.join(' ')}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {ticket.deliberation && !ticket.deliberation.skipped && (
        <Deliberation record={ticket.deliberation} />
      )}

      {ticket.reply && (
        <section className="panel">
          <h2>6 · What the customer received</h2>
          <pre className="code">{ticket.reply}</pre>
        </section>
      )}

      <section className="panel">
        <h2>The record</h2>
        <p className="quiet">
          Every capability use on this ticket, in order, including the ones that were
          refused. Arguments are stored as a digest, never in the clear.
        </p>
        {ticket.audit.length === 0 ? (
          <p className="quiet">No tool was called.</p>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>#</th>
                <th>Principal</th>
                <th>Tool</th>
                <th>Outcome</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {ticket.audit.map((entry) => (
                <tr key={entry.sequence}>
                  <td className="mono">{entry.sequence}</td>
                  <td className="mono">{entry.principal}</td>
                  <td className="mono">{entry.tool}</td>
                  <td>
                    <span className={`pill ${OUTCOME_TONE[entry.outcome] ?? 'info'}`}>
                      {entry.outcome}
                    </span>
                  </td>
                  <td className="mono">
                    {entry.refusal_code ??
                      (entry.duration_ms ? `${entry.duration_ms.toFixed(1)} ms` : '—')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {ticket.model_calls.length > 0 && (
        <section className="panel">
          <h2>Model calls</h2>
          <table className="grid">
            <thead>
              <tr>
                <th>Prompt</th>
                <th>Model</th>
                <th>Tokens</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {ticket.model_calls.map((call, index) => (
                <tr key={index}>
                  <td className="mono">{call.prompt}</td>
                  <td className="mono">{call.model}</td>
                  <td className="mono">
                    {call.input_tokens} / {call.output_tokens}
                  </td>
                  <td className="mono">${Number(call.cost_usd).toFixed(6)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <p>
        <Link href="/tickets">Back to the inbox</Link>
      </p>
    </>
  )
}

function Deliberation({ record }: { record: Record<string, unknown> }) {
  const transcript = (record.transcript as { speaker: string; argument: string }[]) ?? []

  return (
    <section className="panel">
      <h2>5b · The room</h2>
      <p className="lede">
        The policy contradicts itself here, so the case was argued before it reached a
        person. The room recommends; it never executes.
      </p>
      <ul className="transcript">
        {transcript.map((turn, index) => (
          <li key={index}>
            <span className="speaker">{turn.speaker}</span>
            <span>{turn.argument}</span>
          </li>
        ))}
      </ul>
      <dl className="controls">
        <Field term="Verdict" value={String(record.resolution ?? '—')} />
        <Field
          term="Confidence"
          value={
            typeof record.confidence === 'number'
              ? `${(record.confidence * 100).toFixed(0)}%`
              : '—'
          }
        />
      </dl>
      {typeof record.dissent === 'string' && record.dissent && (
        <p className="quiet">
          <strong>Recorded dissent:</strong> {record.dissent}
        </p>
      )}
    </section>
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

export type { TicketDetail }
