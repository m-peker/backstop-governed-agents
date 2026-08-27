/**
 * The ticket inbox.
 *
 * The list is fetched on the server so the page arrives populated; the client
 * island below only handles submitting and asks Next to re-render the server
 * component afterwards. That is one less place for the console's idea of the
 * ticket list to drift from the API's.
 */

import { listTickets } from '@/lib/api'
import { Inbox } from './inbox'

export const dynamic = 'force-dynamic'

export default async function TicketsPage() {
  const response = await listTickets()

  return (
    <Inbox
      tickets={response.ok ? response.data.tickets : []}
      error={response.ok ? null : response.error}
    />
  )
}
