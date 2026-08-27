/**
 * The governance dashboard.
 *
 * Everything here is derived from the audit chain and the registries on each
 * request. A dashboard fed by its own counters can disagree with the record it
 * claims to summarise, and the moment it does, neither number is worth anything.
 */

import { getOverview, getPrompts } from '@/lib/api'

export const dynamic = 'force-dynamic'

export default async function GovernanceDashboard() {
  const [overview, prompts] = await Promise.all([getOverview(), getPrompts()])

  if (!overview.ok) {
    return (
      <section className="panel">
        <h2>Governance</h2>
        <p className="alert">{overview.error}</p>
      </section>
    )
  }

  const data = overview.data

  return (
    <>
      <section className="panel">
        <h2>Controls in force</h2>
        {data.controls.kill_switch_engaged && (
          <p className="alert">
            Kill switch engaged. Every write-scoped tool is refused at the gateway.
          </p>
        )}
        <dl className="controls">
          <Field term="Environment" value={data.controls.environment} />
          <Field
            term="Auto-approve ceiling"
            value={`€${data.controls.auto_approve_ceiling_eur}`}
            note="Above this a refund needs a signed human approval."
          />
          <Field term="Daily budget" value={`$${data.controls.daily_budget_usd}`} />
          <Field
            term="PII detokenisation"
            value={data.controls.pii_detokenize_channels.join(', ')}
            note="Only these channels may receive personal data in the clear."
          />
        </dl>
      </section>

      <section className="panel">
        <h2>The record</h2>
        <div className={`verdict ${data.audit_chain.verified ? 'ok' : 'bad'}`}>
          <strong>{data.audit_chain.verified ? 'CHAIN VERIFIED' : 'CHAIN BROKEN'}</strong>
          <span>
            {data.audit_chain.problem ??
              `${data.capability_use.entries} entries, recomputed on this request.`}
          </span>
        </div>
        <dl className="controls">
          <Field term="Head" value={`${data.audit_chain.head.slice(0, 24)}…`} />
          <Field term="Entries" value={String(data.capability_use.entries)} />
        </dl>

        <div className="split">
          <Counts title="By outcome" counts={data.capability_use.by_outcome} />
          <Counts title="Refusals" counts={data.capability_use.refusals} />
          <Counts title="Tools used" counts={data.capability_use.top_tools} />
        </div>
      </section>

      <section className="panel">
        <h2>Tickets</h2>
        <dl className="controls">
          <Field term="Total" value={String(data.tickets.total)} />
          <Field term="Awaiting a person" value={String(data.tickets.awaiting_approval)} />
          <Field term="Argued in the room" value={String(data.tickets.deliberated)} />
        </dl>
        <Counts title="By status" counts={data.tickets.by_status} />
      </section>

      <section className="panel">
        <h2>Spend</h2>
        {data.spend.circuit_breaker_tripped && (
          <p className="alert">
            The budget circuit breaker has tripped. Further model calls are refused rather
            than downgraded to a cheaper tier.
          </p>
        )}
        <dl className="controls">
          <Field term="Total" value={`$${Number(data.spend.total_usd).toFixed(4)}`} />
          <Field
            term="Remaining"
            value={
              data.spend.remaining_usd
                ? `$${Number(data.spend.remaining_usd).toFixed(4)}`
                : 'no ceiling'
            }
          />
        </dl>
        <Counts title="By task" counts={data.spend.by_task} />
      </section>

      {prompts.ok && (
        <section className="panel">
          <h2>Prompt registry</h2>
          <p className="quiet">
            Every prompt is versioned and hash-pinned. Editing one without bumping its
            version fails CI, because dossiers written before the edit would otherwise cite
            a version that no longer says what it said.
          </p>
          <table className="grid">
            <thead>
              <tr>
                <th>Prompt</th>
                <th>Owner</th>
                <th>Hash</th>
              </tr>
            </thead>
            <tbody>
              {prompts.data.prompts.map((prompt) => (
                <tr key={prompt.reference}>
                  <td className="mono">{prompt.reference}</td>
                  <td>{prompt.owner}</td>
                  <td className="mono">{prompt.hash}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  )
}

function Counts({ title, counts }: { title: string; counts: Record<string, string | number> }) {
  const entries = Object.entries(counts)
  return (
    <div className="counts">
      <h3>{title}</h3>
      {entries.length === 0 ? (
        <p className="quiet">None.</p>
      ) : (
        <ul className="plain">
          {entries.map(([key, value]) => (
            <li key={key}>
              <span>{key.replace(/_/g, ' ')}</span>
              <span className="mono">
                {typeof value === 'string' && value.includes('.')
                  ? `$${Number(value).toFixed(4)}`
                  : value}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Field({ term, value, note }: { term: string; value: string; note?: string }) {
  return (
    <div className="control">
      <dt>{term}</dt>
      <dd>
        <strong>{value}</strong>
        {note && <span className="note">{note}</span>}
      </dd>
    </div>
  )
}
