/**
 * The approval queue.
 *
 * Each item shows the reviewer what the system concluded, which clauses it rests
 * on, and - where the room sat - both sides of the argument plus the recorded
 * dissent. The point is that a person deciding here should not have to
 * reconstruct the case themselves.
 */

import { listApprovals } from '@/lib/api'
import { Queue } from './queue'

export const dynamic = 'force-dynamic'

export default async function ApprovalsPage() {
  const response = await listApprovals()

  return (
    <Queue
      items={response.ok ? response.data.approvals : []}
      error={response.ok ? null : response.error}
    />
  )
}
