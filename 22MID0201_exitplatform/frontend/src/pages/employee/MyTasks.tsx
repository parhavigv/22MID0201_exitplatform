import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Undo2 } from 'lucide-react'
import { useSession } from '@/auth/AuthProvider'
import { Button, Empty, Loading, PageHeader, Row } from '@/components/ui'
import { api } from '@/lib/api'
import {
  cn,
  dueLabel,
  latestDocumentFor,
  OWNER_LABEL,
  taskDisplayStatus,
  TEXT_TONE,
} from '@/lib/format'
import type { CaseTask, ExitStage } from '@/lib/types'

/**
 * Every task on the exit, grouped by stage in workflow order. The employee's
 * own tasks are actionable; everyone else's are shown so they can see what is
 * blocking them and who to chase.
 */
export function MyTasks() {
  const { employee } = useSession()
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['my-exit', employee.id],
    queryFn: () => api.myExit(employee.id),
  })

  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: CaseTask['status'] }) =>
      api.setTaskStatus(id, status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['my-exit', employee.id] }),
  })

  if (isLoading) return <Loading />
  if (!data) return <Empty title="You have no exit in progress." />

  const { stages, tasks, documents, case: exitCase } = data
  const currentIndex = stages.findIndex((s) => s.code === exitCase.current_stage)

  return (
    <div>
      <PageHeader
        title="Tasks"
        lede="Everything your exit requires, in the order it happens. Stages ahead of the current one are shown so nothing is a surprise."
      />

      <div className="space-y-6">
        {stages.map((stage, i) => {
          const stageTasks = tasks.filter((t) => t.stage_code === stage.code)
          if (stageTasks.length === 0) return null

          const done = stageTasks.filter((t) => t.status === 'completed').length
          const state = i < currentIndex ? 'past' : i === currentIndex ? 'current' : 'ahead'

          return (
            <section key={stage.code}>
              <StageHeading
                stage={stage}
                done={done}
                total={stageTasks.length}
                state={state}
              />

              <div className={cn('border border-line bg-surface', state === 'ahead' && 'opacity-60')}>
                {stageTasks.map((task) => {
                  // A document-backed task's real state lives in its document:
                  // "submitted, waiting for your manager" is not something the
                  // task row alone can say.
                  const doc = latestDocumentFor(documents, task.doc_type_code)
                  const display = taskDisplayStatus(task, doc)
                  const mine = task.owner_role === 'employee'
                  const done = task.status === 'completed' || task.status === 'waived'

                  return (
                    <Row key={task.id} tone={display.tone} dashed={!mine}>
                      <div className="min-w-0 flex-1">
                        <p className={cn('text-ink', done && 'text-muted line-through')}>
                          {task.title}
                        </p>
                        <p className="mt-0.5 text-[13px] text-muted">
                          {OWNER_LABEL[task.owner_role]}
                          {task.due_date && ` · ${dueLabel(task.due_date)}`}
                        </p>
                        <p className={cn('mt-0.5 text-[13px]', TEXT_TONE[display.tone])}>
                          {display.label}
                        </p>
                        {display.hint && (
                          <p className="mt-0.5 max-w-[70ch] text-[13px] text-ink-soft">
                            {display.hint}
                          </p>
                        )}
                      </div>

                      {mine && (
                        <Button
                          size="sm"
                          variant={done ? 'ghost' : 'secondary'}
                          disabled={setStatus.isPending}
                          onClick={() =>
                            setStatus.mutate({
                              id: task.id,
                              status: done ? 'pending' : 'completed',
                            })
                          }
                        >
                          {done ? (
                            <>
                              <Undo2 className="size-3.5" />
                              Reopen
                            </>
                          ) : (
                            <>
                              <Check className="size-3.5" />
                              Mark done
                            </>
                          )}
                        </Button>
                      )}

                      {!mine && (
                        <span
                          className={cn(
                            'shrink-0 self-center text-[13px]',
                            TEXT_TONE[display.tone],
                          )}
                        >
                          {done ? 'Cleared' : 'Waiting'}
                        </span>
                      )}
                    </Row>
                  )
                })}
              </div>
            </section>
          )
        })}
      </div>
    </div>
  )
}

function StageHeading({
  stage,
  done,
  total,
  state,
}: {
  stage: ExitStage
  done: number
  total: number
  state: 'past' | 'current' | 'ahead'
}) {
  return (
    <div className="mb-2 flex items-baseline justify-between gap-3">
      <h2
        className={cn(
          'text-[15px]',
          state === 'current' ? 'font-medium text-ink' : 'text-ink-soft',
        )}
      >
        {stage.name}
        {state === 'current' && (
          <span className="ml-2 text-[13px] font-normal text-indigo">Current stage</span>
        )}
      </h2>
      <span className="tnum shrink-0 text-[13px] text-muted">
        {done} of {total}
      </span>
    </div>
  )
}
