/**
 * Phase 0 console: the system posture page.
 *
 * It answers two questions before any agent exists, and it will keep answering
 * them once one does:
 *
 *   1. Are the dependencies reachable?
 *   2. What is this system currently *allowed* to do?
 *
 * The second is the one that matters. A governance dashboard that only appears
 * after the agents are built tends never to get built, so it goes in first.
 */

import { getGovernance, getReadiness } from '@/lib/api'

export const dynamic = 'force-dynamic'

const EURO = new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR' })
const USD = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

export default async function PosturePage() {
  const [readiness, governance] = await Promise.all([getReadiness(), getGovernance()])

  return (
    <>
      <section className="panel">
        <h2>Dependencies</h2>
        {readiness.ok ? (
          <ul className="checks">
            <Check label="Postgres" ok={readiness.data.dependencies.database} />
            <Check label="Redis" ok={readiness.data.dependencies.redis} />
          </ul>
        ) : (
          <p className="unreachable">
            API unreachable at <code>{readiness.endpoint}</code>. Start it with{' '}
            <code>./task.ps1 dev</code>.
          </p>
        )}
      </section>

      <section className="panel">
        <h2>Controls in force</h2>
        {governance.ok ? (
          <>
            {governance.data.kill_switch_engaged && (
              <p className="alert">
                Kill switch engaged. Every write-scoped tool is refused at the gateway.
              </p>
            )}
            <dl className="controls">
              <Control
                term="Environment"
                value={governance.data.environment}
              />
              <Control
                term="Auto-approve ceiling"
                value={EURO.format(governance.data.max_auto_refund_eur)}
                note="Refunds above this amount require a signed human approval."
              />
              <Control
                term="Daily budget"
                value={USD.format(governance.data.daily_budget_usd)}
                note="Per tenant, before the circuit breaker trips."
              />
              <Control
                term="PII detokenisation"
                value={governance.data.pii_detokenize_channels.join(', ')}
                note="Only these channels may receive personal data in the clear."
              />
            </dl>
          </>
        ) : (
          <p className="unreachable">Governance posture unavailable.</p>
        )}
      </section>

      <section className="panel muted">
        <h2>Not built yet</h2>
        <p>
          Ticket inbox, live trace viewer, approval queue and the Attack Lab arrive in
          later phases. See <code>docs/roadmap.md</code>.
        </p>
      </section>
    </>
  )
}

function Check({ label, ok }: { label: string; ok: boolean }) {
  return (
    <li className={ok ? 'check ok' : 'check down'}>
      <span className="dot" aria-hidden="true" />
      <span>{label}</span>
      <span className="state">{ok ? 'reachable' : 'unreachable'}</span>
    </li>
  )
}

function Control({ term, value, note }: { term: string; value: string; note?: string }) {
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
