import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn, RAIL, TEXT_TONE, type Tone } from '@/lib/format'

/* -------------------------------------------------------------------------- */
/* Button                                                                      */
/* -------------------------------------------------------------------------- */

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md'
}

export function Button({
  variant = 'secondary',
  size = 'md',
  className,
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      className={cn(
        'inline-flex items-center justify-center gap-1.5 rounded-sm border font-medium',
        'transition-colors disabled:cursor-not-allowed disabled:opacity-45',
        size === 'sm' ? 'h-7 px-2.5 text-[13px]' : 'h-9 px-3.5 text-sm',
        variant === 'primary' &&
          'border-indigo bg-indigo text-white hover:bg-indigo/90',
        variant === 'secondary' &&
          'border-line-strong bg-surface text-ink hover:bg-sunken',
        variant === 'ghost' &&
          'border-transparent bg-transparent text-ink-soft hover:bg-sunken hover:text-ink',
        variant === 'danger' &&
          'border-rust/40 bg-rust-soft text-rust hover:border-rust/70',
        className,
      )}
    />
  )
}

/* -------------------------------------------------------------------------- */
/* Panel — a titled region. Deliberately flat: one hairline border, no shadow, */
/* no gradient. Depth is reserved for overlays.                                */
/* -------------------------------------------------------------------------- */

export function Panel({
  title,
  action,
  children,
  className,
}: {
  title?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cn('border border-line bg-surface', className)}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h2 className="text-[13px] font-semibold text-ink-soft">{title}</h2>
          {action}
        </header>
      )}
      {children}
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Row — the workhorse. Status lives in a 3px left rail, so a long list reads  */
/* as a vertical progress barcode instead of a field of coloured pills.        */
/* -------------------------------------------------------------------------- */

export function Row({
  tone = 'neutral',
  dashed = false,
  children,
  className,
}: {
  tone?: Tone
  /** Dashed rail = waiting on someone else, not on you. */
  dashed?: boolean
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('relative flex gap-3 border-b border-line px-4 py-3 last:border-b-0', className)}>
      <span
        aria-hidden
        className={cn(
          'absolute top-0 bottom-0 left-0 w-[3px]',
          dashed ? 'bg-transparent' : RAIL[tone],
        )}
        style={
          dashed
            ? {
                backgroundImage: `repeating-linear-gradient(to bottom, currentColor 0 4px, transparent 4px 8px)`,
                color: `var(--color-${tone === 'neutral' ? 'line-strong' : tone})`,
              }
            : undefined
        }
      />
      {children}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Tone text — used sparingly, where the word itself is the signal.            */
/* -------------------------------------------------------------------------- */

export function ToneText({
  tone,
  children,
  className,
}: {
  tone: Tone
  children: ReactNode
  className?: string
}) {
  return <span className={cn(TEXT_TONE[tone], className)}>{children}</span>
}

/* -------------------------------------------------------------------------- */
/* Count — a number and what it counts, for compact summary strips.            */
/* -------------------------------------------------------------------------- */

export function Count({
  value,
  label,
  tone = 'neutral',
}: {
  value: number | string
  label: string
  tone?: Tone
}) {
  return (
    <div className="flex items-baseline gap-2">
      <span className={cn('tnum text-xl leading-none font-medium', TEXT_TONE[tone])}>
        {value}
      </span>
      <span className="text-[13px] text-muted">{label}</span>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Empty state — an invitation to act, never "no data".                        */
/* -------------------------------------------------------------------------- */

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="px-4 py-10 text-center">
      <p className="text-ink-soft">{title}</p>
      {hint && <p className="mt-1 text-[13px] text-muted">{hint}</p>}
    </div>
  )
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return <p className="px-4 py-10 text-center text-muted">{label}…</p>
}

/* -------------------------------------------------------------------------- */
/* Page header                                                                 */
/* -------------------------------------------------------------------------- */

export function PageHeader({
  title,
  lede,
  action,
}: {
  title: ReactNode
  lede?: ReactNode
  action?: ReactNode
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-serif text-[28px] leading-tight text-ink">{title}</h1>
        {lede && <p className="mt-1 max-w-[62ch] text-ink-soft">{lede}</p>}
      </div>
      {action}
    </header>
  )
}
