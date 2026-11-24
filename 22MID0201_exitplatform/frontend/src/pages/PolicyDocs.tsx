import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Trash2, Upload } from 'lucide-react'
import { useSession } from '@/auth/AuthProvider'
import { Button, Empty, Loading, PageHeader, Row } from '@/components/ui'
import { api } from '@/lib/api'
import { shortDate, relativeTime } from '@/lib/format'

/**
 * HR uploads policy documents here. Each document is chunked and embedded
 * so the Exit Copilot can cite them when answering policy questions.
 * Managers can view the list but cannot upload or delete.
 */
export function PolicyDocs() {
  const { employee } = useSession()
  const qc = useQueryClient()
  const isHR = employee.app_role === 'hr'

  const { data, isLoading } = useQuery({
    queryKey: ['policies'],
    queryFn: () => api.listPolicies(),
  })

  const [title, setTitle] = useState('')
  const [version, setVersion] = useState('')
  const [effectiveFrom, setEffectiveFrom] = useState(
    new Date().toISOString().slice(0, 10),
  )
  const [file, setFile] = useState<File | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const upload = useMutation({
    mutationFn: () => api.uploadPolicy(title.trim(), version.trim(), effectiveFrom, file!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['policies'] })
      setTitle('')
      setVersion('')
      setFile(null)
      setUploadError(null)
      if (fileRef.current) fileRef.current.value = ''
    },
    onError: (err: Error) => setUploadError(err.message),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.deletePolicy(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['policies'] }),
  })

  const docs = data ?? []

  return (
    <div>
      <PageHeader
        title="Policy documents"
        lede="Documents the Exit Copilot cites when answering policy questions. Upload markdown or plain text files."
      />

      {/* Upload form — HR only */}
      {isHR && (
        <form
          className="mb-6 border border-line bg-surface p-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (!title.trim() || !version.trim() || !file) {
              setUploadError('Title, version, and a file are all required.')
              return
            }
            setUploadError(null)
            upload.mutate()
          }}
        >
          <h2 className="mb-3 text-[13px] font-semibold text-ink-soft">
            Upload a policy document
          </h2>

          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label className="block text-[12px] text-muted mb-1">Title</label>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Employee Exit Policy"
                className="w-full border border-line bg-paper px-3 py-2 text-[13px] text-ink placeholder:text-muted"
              />
            </div>
            <div>
              <label className="block text-[12px] text-muted mb-1">Version</label>
              <input
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                placeholder="e.g. v2.1"
                className="w-full border border-line bg-paper px-3 py-2 text-[13px] text-ink placeholder:text-muted"
              />
            </div>
            <div>
              <label className="block text-[12px] text-muted mb-1">Effective from</label>
              <input
                type="date"
                value={effectiveFrom}
                onChange={(e) => setEffectiveFrom(e.target.value)}
                className="w-full border border-line bg-paper px-3 py-2 text-[13px] text-ink"
              />
            </div>
          </div>

          <div className="mt-3 flex items-center gap-3">
            <input
              ref={fileRef}
              type="file"
              accept=".txt,.md"
              className="sr-only"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="flex items-center gap-2 border border-line bg-paper px-3 py-2 text-[13px] text-ink-soft hover:bg-sunken"
            >
              <FileText className="size-4" />
              {file ? file.name : 'Choose .txt or .md file'}
            </button>

            <Button
              type="submit"
              variant="primary"
              size="sm"
              disabled={upload.isPending}
            >
              <Upload className="size-3.5" />
              {upload.isPending ? 'Uploading & indexing…' : 'Upload and index'}
            </Button>
          </div>

          {uploadError && (
            <p className="mt-2 text-[13px] text-rust">{uploadError}</p>
          )}

          {upload.isSuccess && (
            <p className="mt-2 text-[13px] text-moss">
              Indexed successfully.
            </p>
          )}

          <p className="mt-2 text-[12px] text-muted">
            Plain text or markdown, max 2 MB. Indexing takes a few seconds per document.
          </p>
        </form>
      )}

      {/* Document list */}
      {isLoading ? (
        <Loading />
      ) : docs.length === 0 ? (
        <Empty
          title="No policy documents yet."
          hint={
            isHR
              ? 'Upload a document above and the Exit Copilot will cite it when answering policy questions.'
              : 'HR has not uploaded any policy documents yet.'
          }
        />
      ) : (
        <div className="border border-line bg-surface">
          {docs.map((doc) => (
            <Row key={doc.id} tone="neutral">
              <div className="min-w-0 flex-1">
                <p className="text-ink">{doc.title}</p>
                <p className="mt-0.5 text-[13px] text-muted">
                  {doc.version} · effective {shortDate(doc.effective_from)} · uploaded{' '}
                  {relativeTime(doc.created_at)}
                  {doc.chunk_count !== undefined && (
                    <> · {doc.chunk_count} chunks indexed</>
                  )}
                </p>
              </div>

              {isHR && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={remove.isPending}
                  onClick={() => {
                    if (confirm(`Delete "${doc.title}"? This cannot be undone.`)) {
                      remove.mutate(doc.id)
                    }
                  }}
                >
                  <Trash2 className="size-3.5 text-rust" />
                </Button>
              )}
            </Row>
          ))}
        </div>
      )}
    </div>
  )
}
