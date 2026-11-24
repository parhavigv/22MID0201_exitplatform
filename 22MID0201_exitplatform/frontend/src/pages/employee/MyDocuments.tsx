import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckSquare, Paperclip, Upload, FileText } from 'lucide-react'
import { useSession } from '@/auth/AuthProvider'
import { Button, Empty, Loading, PageHeader, Row } from '@/components/ui'
import { NDAForm } from './NDAForm'
import { api } from '@/lib/api'
import { cn, fileSize, relativeTime, TEXT_TONE, type Tone } from '@/lib/format'
import type { CaseDocument, DocumentType, NdaContent } from '@/lib/types'

/**
 * Required documents — each with its current state.
 *
 * NDA_ACKNOWLEDGEMENT uses an in-platform form (employee ticks boxes and
 * types their name). All other doc types use the file uploader. The manager
 * reads NDA content inline in their inbox; for other docs they download the
 * file via a signed URL.
 */
export function MyDocuments() {
  const { employee } = useSession()
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['my-exit', employee.id],
    queryFn: () => api.myExit(employee.id),
  })

  const upload = useMutation({
    mutationFn: ({ code, file }: { code: string; file: File }) =>
      api.uploadDocument(data!.case.id, code, file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['my-exit', employee.id] }),
  })

  if (isLoading) return <Loading />
  if (!data) return <Empty title="You have no exit in progress." />

  const mine = data.document_types.filter((t) => t.owner_role === 'employee')
  const outstanding = mine.filter(
    (t) => t.is_required && !latestFor(data.documents, t.code),
  ).length

  return (
    <div>
      <PageHeader
        title="Documents"
        lede={
          outstanding > 0
            ? `${outstanding} required ${outstanding === 1 ? 'document is' : 'documents are'} still missing. Your manager reviews each one after you submit it.`
            : 'Everything required has been submitted. Your manager reviews each one before the stage can close.'
        }
      />

      <div className="space-y-3">
        {mine.map((type) => (
          <DocumentSlot
            key={type.code}
            type={type}
            document={latestFor(data.documents, type.code)}
            caseId={data.case.id}
            employeeId={employee.id}
            uploading={upload.isPending && upload.variables?.code === type.code}
            onUpload={(file) => upload.mutate({ code: type.code, file })}
            onSubmitted={() => qc.invalidateQueries({ queryKey: ['my-exit', employee.id] })}
          />
        ))}
      </div>

      <IssuedToYou documents={data.documents} types={data.document_types} />

      <p className="mt-6 text-[13px] text-muted">
        NDA acknowledgement is filled in here. All other documents: PDF, PNG, or
        JPEG, max 10 MB. Files are private — only you, your manager, and HR can
        open them.
      </p>
    </div>
  )
}

/**
 * The documents the company owes you — relieving letter, experience letter,
 * no-dues, settlement statement.
 *
 * These are what the whole exit is *for*, and the employee had no screen
 * showing them: the list above filters to document types they own, so anything
 * HR or Finance issued was invisible. Nothing to do here but read them.
 *
 * The heading says "You'll receive", not "Issued to you". The section lists
 * all four from the start so the employee knows what is coming, and a heading
 * in the past tense made it look like all four were already waiting.
 */
function IssuedToYou({
  documents,
  types,
}: {
  documents: CaseDocument[]
  types: DocumentType[]
}) {
  const issuable = types.filter((t) => t.owner_role !== 'employee')
  if (issuable.length === 0) return null

  const ready = issuable.filter((t) => latestFor(documents, t.code)).length

  return (
    <section className="mt-8">
      <h2 className="font-serif text-[20px] leading-tight text-ink">
        You'll receive
      </h2>
      <p className="mt-1 mb-3 text-[13px] text-muted">
        {ready === 0
          ? `None of these have been issued yet. They are released as each clearance completes — nothing for you to do.`
          : `${ready} of ${issuable.length} issued so far. The rest are released as each clearance completes.`}
      </p>

      <div className="border border-line bg-surface">
        {issuable.map((type) => {
          const doc = latestFor(documents, type.code)
          return (
            <Row key={type.code} tone={doc ? 'moss' : 'neutral'} dashed={!doc}>
              <div className="min-w-0 flex-1">
                <p className={cn(doc ? 'text-ink' : 'text-muted')}>{type.name}</p>
                <p className="mt-0.5 text-[13px] text-muted">
                  {doc
                    ? `Issued ${relativeTime(doc.created_at)}`
                    : `Not issued yet · ${type.owner_role.toUpperCase()} releases this`}
                </p>
              </div>
              {doc ? (
                <Button
                  size="sm"
                  variant="ghost"
                  className="shrink-0 self-center"
                  onClick={() => api.openDocument(doc.id)}
                >
                  <FileText className="size-3.5" />
                  Open
                </Button>
              ) : (
                <span className="shrink-0 self-center text-[13px] text-muted">
                  Waiting
                </span>
              )}
            </Row>
          )
        })}
      </div>
    </section>
  )
}

function DocumentSlot({
  type,
  document,
  caseId,
  employeeId,
  uploading,
  onUpload,
  onSubmitted,
}: {
  type: DocumentType
  document: CaseDocument | null
  caseId: string
  employeeId: string
  uploading: boolean
  onUpload: (file: File) => void
  onSubmitted: () => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [showForm, setShowForm] = useState(false)

  const isNDA = type.code === 'NDA_ACKNOWLEDGEMENT'

  const tone: Tone = document
    ? document.status === 'approved'
      ? 'moss'
      : document.status === 'rejected'
        ? 'rust'
        : 'amber'
    : 'neutral'

  const statusLine = !document
    ? type.is_required
      ? 'Required — not submitted'
      : 'Optional — not submitted'
    : document.status === 'pending'
      ? `Waiting for review · submitted ${relativeTime(document.created_at)}`
      : document.status === 'approved'
        ? `Approved${document.reviewed_at ? ` ${relativeTime(document.reviewed_at)}` : ''}`
        : 'Rejected — please resubmit'

  if (isNDA && !document && showForm) {
    return (
      <article className="border border-indigo/40 bg-surface">
        <div className="border-b border-line px-4 py-3">
          <p className="font-medium text-ink">{type.name}</p>
          {type.description && (
            <p className="mt-0.5 text-[13px] text-muted">{type.description}</p>
          )}
        </div>
        <div className="px-4 py-4">
          <NDAForm
            caseId={caseId}
            employeeId={employeeId}
            onSubmitted={() => {
              setShowForm(false)
              onSubmitted()
            }}
          />
        </div>
      </article>
    )
  }

  return (
    <article
      onDragOver={(e) => {
        if (isNDA) return
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        if (isNDA) return
        e.preventDefault()
        setDragging(false)
        const file = e.dataTransfer.files[0]
        if (file) onUpload(file)
      }}
      className={cn(
        'border bg-surface transition-colors',
        dragging ? 'border-indigo bg-indigo-soft' : 'border-line',
      )}
    >
      <Row tone={tone} className="border-b-0">
        <div className="min-w-0 flex-1">
          <p className="text-ink">{type.name}</p>
          {type.description && (
            <p className="mt-0.5 max-w-[68ch] text-[13px] text-muted">{type.description}</p>
          )}
          <p className={cn('mt-1 text-[13px]', TEXT_TONE[tone])}>{statusLine}</p>

          {/* Inline NDA: show which items were checked */}
          {document?.is_inline && document.content && (
            <NdaContentPreview content={document.content as NdaContent} />
          )}

          {/* File upload: show filename */}
          {document && !document.is_inline && (
            <p className="mt-1.5 flex items-center gap-1.5 text-[13px] text-ink-soft">
              <Paperclip className="size-3.5 shrink-0" />
              <span className="truncate">{document.file_name}</span>
              <span className="text-muted">{fileSize(document.size_bytes)}</span>
            </p>
          )}

          {document?.review_note && (
            <p className="mt-1.5 border-l-2 border-rust pl-2 text-[13px] text-ink-soft">
              {document.review_note}
            </p>
          )}

          {/* The automatic check, when it disagreed. Shown as a caution rather
              than a rejection — it is a second opinion, and the manager still
              decides. A passing check says nothing: silence means fine. */}
          {document?.verification && !document.verification.belongs && (
            <p className="mt-1.5 border-l-2 border-amber pl-2 text-[13px] text-ink-soft">
              <span className="text-amber">This may be the wrong document.</span>{' '}
              {document.verification.reason} Your manager will still review it — if
              you attached the wrong file, upload the right one.
            </p>
          )}
        </div>

        <div className="shrink-0 self-center">
          {isNDA ? (
            /* NDA: open form if not yet submitted; replace if rejected */
            (!document || document.status === 'rejected') ? (
              <Button
                size="sm"
                variant={document ? 'ghost' : 'secondary'}
                onClick={() => setShowForm(true)}
              >
                <FileText className="size-3.5" />
                {document ? 'Re-submit' : 'Fill in online'}
              </Button>
            ) : null
          ) : (
            /* All other docs: file upload */
            <>
              <input
                ref={inputRef}
                type="file"
                accept=".pdf,.png,.jpg,.jpeg"
                className="sr-only"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) onUpload(file)
                  e.target.value = ''
                }}
              />
              <Button
                size="sm"
                variant={document ? 'ghost' : 'secondary'}
                disabled={uploading}
                onClick={() => inputRef.current?.click()}
              >
                <Upload className="size-3.5" />
                {uploading ? 'Uploading' : document ? 'Replace' : 'Upload'}
              </Button>
            </>
          )}
        </div>
      </Row>
    </article>
  )
}

function NdaContentPreview({ content }: { content: NdaContent }) {
  const allDone = content.acknowledgements?.every(Boolean)
  return (
    <div className="mt-2 flex items-center gap-2 text-[13px] text-ink-soft">
      <CheckSquare className="size-3.5 shrink-0 text-moss" />
      <span>
        {allDone ? 'All 4 statements acknowledged' : 'Partially acknowledged'} ·{' '}
        signed as <strong>{content.full_name}</strong>
      </span>
    </div>
  )
}

function latestFor(documents: CaseDocument[], code: string): CaseDocument | null {
  const matches = documents
    .filter((d) => d.doc_type_code === code)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
  return matches[0] ?? null
}
