import type { Metadata } from 'next'
import type { ReactNode } from 'react'
import Link from 'next/link'
import './globals.css'

export const metadata: Metadata = {
  title: 'Backstop Console',
  description: 'Governed agent platform for retail customer operations',
}

const NAV = [
  { href: '/', label: 'Posture' },
  { href: '/tickets', label: 'Tickets' },
  { href: '/approvals', label: 'Approvals' },
  { href: '/lab', label: 'Attack Lab' },
  { href: '/governance', label: 'Governance' },
]

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="masthead">
          <div className="masthead-inner">
            <Link href="/" className="wordmark">
              Backstop
            </Link>
            <nav className="nav">
              {NAV.map((item) => (
                <Link key={item.href} href={item.href}>
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="shell">{children}</main>
      </body>
    </html>
  )
}
