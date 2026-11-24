/**
 * Exit Copilot chat panel — embedded in all three dashboards.
 *
 * Talks to POST /api/agent/chat (SSE streaming, Phase 3 endpoint).
 * While that endpoint isn't built yet, falls back to a mock that echoes a
 * "not yet connected" message so all three dashboards can be reviewed now.
 *
 * The chat sends the current user's JWT; the backend builds an RLS-bound
 * ActorContext from it, so the model sees exactly what the user can see.
 */

import { useEffect, useRef, useState } from 'react'
import { Bot, ChevronDown, Send } from 'lucide-react'
import { useAuth } from '@/auth/AuthProvider'
import { USE_MOCKS } from '@/lib/api'
import { supabase } from '@/lib/supabase'
import { cn } from '@/lib/format'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

/**
 * What each role is likely to want, phrased so the supervisor routes it to the
 * right specialist. There are twenty-one workers and the only way to reach any
 * of them is to type something the supervisor recognises — which nobody can be
 * expected to guess. These are the entry points.
 */
const ROLE_STARTERS: Record<string, string[]> = {
  employee: [
    "What's left before my last day?",
    'How do I submit my KT document?',
    'Can you explain the exit interview process?',
  ],
  manager: [
    "Which of my team's cases have overdue tasks?",
    'Review the KT document for this case',
    'Draft a reminder for the pending KT review',
  ],
  hr: [
    'What are the top reasons people are leaving, what did they like, and what changes are they asking for?',
    'Which cases are at risk of missing their deadline?',
    'Show me the compliance status across all active cases',
  ],
  it: [
    'Draft the access revocation plan for this person',
    'Who has left but still has access that has not been revoked?',
    'Which systems still need revoking across my queue?',
  ],
  finance: [
    'Draft the full and final settlement breakdown',
    'What is the notice period buyout rule, and does it apply here?',
    'Which settlements are still waiting on a clearance?',
  ],
}

export function AgentChat({ caseId }: { caseId?: string }) {
  const { session } = useAuth()
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [busy, setBusy] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  const role = session?.role ?? 'employee'
  const starters = ROLE_STARTERS[role] ?? []

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, open])

  async function send(text: string) {
    if (!text.trim() || busy) return
    const userMsg: Message = { role: 'user', content: text.trim() }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setBusy(true)

    if (USE_MOCKS) {
      // Mock response while the SSE endpoint isn't wired yet
      await new Promise((r) => setTimeout(r, 700))
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content:
            'Exit Copilot is not yet connected to the backend in mock mode. ' +
            'Set VITE_USE_MOCKS=false and run the FastAPI backend to use the live assistant.',
        },
      ])
      setBusy(false)
      return
    }

    try {
      const { data } = await supabase.auth.getSession()
      const token = data.session?.access_token
      const res = await fetch('/api/agent/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          message: text.trim(),
          case_id: caseId ?? null,
        }),
      })

      if (!res.ok || !res.body) {
        throw new Error(`Server error ${res.status}`)
      }

      // SSE stream — each "data: " line is a chunk of the assistant's reply
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let assistantText = ''

      setMessages((prev) => [...prev, { role: 'assistant', content: '' }])

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const chunk = line.slice(6)
            if (chunk === '[DONE]') break
            assistantText += chunk
            setMessages((prev) => {
              const updated = [...prev]
              updated[updated.length - 1] = { role: 'assistant', content: assistantText }
              return updated
            })
          }
        }
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `Could not reach the assistant: ${err instanceof Error ? err.message : String(err)}`,
        },
      ])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed right-4 bottom-14 z-40 flex flex-col items-end gap-2">
      {/* Collapsed button */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="flex items-center gap-2 rounded-sm border border-indigo bg-indigo px-3.5 py-2.5 text-[13px] font-medium text-white shadow-md hover:bg-indigo/90"
        >
          <Bot className="size-4" />
          Exit Copilot
        </button>
      )}

      {/* Chat panel */}
      {open && (
        <div className="flex h-[520px] w-[380px] flex-col rounded-sm border border-line bg-surface shadow-xl">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <div className="flex items-center gap-2">
              <Bot className="size-4 text-indigo" strokeWidth={1.75} />
              <span className="text-[13px] font-semibold text-ink">Exit Copilot</span>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="text-muted hover:text-ink"
              aria-label="Close"
            >
              <ChevronDown className="size-4" />
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {messages.length === 0 && (
              <div className="space-y-2">
                <p className="text-[12px] text-muted">Try asking:</p>
                {starters.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="block w-full rounded-sm border border-line bg-paper px-3 py-2 text-left text-[13px] text-ink-soft hover:bg-sunken"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}

            {messages.map((m, i) => (
              <div
                key={i}
                className={cn(
                  'max-w-[90%] rounded-sm px-3 py-2 text-[13px] leading-relaxed',
                  m.role === 'user'
                    ? 'ml-auto bg-indigo text-white'
                    : 'bg-paper text-ink border border-line',
                )}
              >
                {m.content || (busy && i === messages.length - 1 ? '…' : '')}
              </div>
            ))}

            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <form
            className="flex gap-2 border-t border-line p-3"
            onSubmit={(e) => {
              e.preventDefault()
              send(input)
            }}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask Exit Copilot…"
              disabled={busy}
              className="flex-1 rounded-sm border border-line bg-paper px-3 py-1.5 text-[13px] text-ink placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-indigo/50"
            />
            <button
              type="submit"
              disabled={busy || !input.trim()}
              className="rounded-sm border border-indigo bg-indigo px-3 py-1.5 text-white disabled:opacity-40 hover:bg-indigo/90"
            >
              <Send className="size-3.5" />
            </button>
          </form>
        </div>
      )}
    </div>
  )
}
