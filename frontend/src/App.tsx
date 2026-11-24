import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider, useAuth, HOME_FOR } from '@/auth/AuthProvider'
import { RequireRole } from '@/auth/RequireRole'
import { AppShell } from '@/components/AppShell'
import { ApprovalQueue } from '@/pages/ApprovalQueue'
import { CaseDetail } from '@/pages/CaseDetail'
import { CaseList } from '@/pages/CaseList'
import { ClearanceQueue } from '@/pages/ClearanceQueue'
import { ManagerHome } from '@/pages/ManagerHome'
import { NeedsYou } from '@/pages/NeedsYou'
import { Progress } from '@/pages/Progress'
import { ExitInterview } from '@/pages/employee/ExitInterview'
import { MyDocuments } from '@/pages/employee/MyDocuments'
import { MyExit } from '@/pages/employee/MyExit'
import { MyKt } from '@/pages/employee/MyKt'
import { MyTasks } from '@/pages/employee/MyTasks'
import { AgentTrace } from '@/pages/AgentTrace'
import { Analytics } from '@/pages/Analytics'
import { PolicyDocs } from '@/pages/PolicyDocs'
import { NotFound, SignIn } from '@/pages/SignIn'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1 },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/sign-in" element={<SignIn />} />

            <Route element={<RequireRole allow={['employee', 'manager', 'hr', 'it', 'finance']} />}>
              <Route element={<AppShell />}>
                <Route index element={<RoleHome />} />

                {/* Employee */}
                <Route path="my-exit" element={<MyExit />} />
                <Route path="my-tasks" element={<MyTasks />} />
                <Route path="my-documents" element={<MyDocuments />} />
                <Route path="my-kt" element={<MyKt />} />
                <Route path="my-interview" element={<ExitInterview />} />

                {/* Manager and HR */}
                <Route
                  path="team"
                  element={
                    <RequireRole allow={['manager', 'hr']}>
                      <CaseList
                        scope="team"
                        title="Team exits"
                        lede="People reporting to you who are working through an exit."
                      />
                    </RequireRole>
                  }
                />
                <Route
                  path="cases"
                  element={
                    <RequireRole allow={['hr']}>
                      <CaseList
                        scope="all"
                        title="All cases"
                        lede="Every exit in progress across the organisation."
                      />
                    </RequireRole>
                  }
                />
                <Route
                  path="sla"
                  element={
                    <RequireRole allow={['hr']}>
                      <CaseList
                        scope="all"
                        title="Overdue"
                        lede="Cases with at least one task past its SLA."
                        onlyOverdue
                      />
                    </RequireRole>
                  }
                />
                {/* One route, two audiences: a manager gets the consolidated
                    dashboard, HR keeps the queue-shaped inbox they already
                    work from. */}
                <Route
                  path="needs-you"
                  element={
                    <RequireRole allow={['manager', 'hr']}>
                      <NeedsYouForRole />
                    </RequireRole>
                  }
                />
                <Route
                  path="progress"
                  element={
                    <RequireRole allow={['hr']}>
                      <Progress />
                    </RequireRole>
                  }
                />
                {/* IT and Finance belong here too. The backend has always
                    allowed them — /cases/{id}/detail is RLS-only, with no role
                    check — but this guard turned them away, and the Issue
                    button for a no-dues certificate lives on this screen. So
                    Finance could be asked to issue a document they had no
                    route to. What each role actually sees is still decided by
                    RLS, not by this list. */}
                <Route
                  path="cases/:caseId"
                  element={
                    <RequireRole allow={['manager', 'hr', 'it', 'finance']}>
                      <CaseDetail />
                    </RequireRole>
                  }
                />
                <Route
                  path="approvals"
                  element={
                    <RequireRole allow={['manager', 'hr']}>
                      <ApprovalQueue />
                    </RequireRole>
                  }
                />
                <Route
                  path="policies"
                  element={
                    <RequireRole allow={['hr', 'manager']}>
                      <PolicyDocs />
                    </RequireRole>
                  }
                />
                {/* IT and Finance: one queue, whose contents depend on the
                    role signed in. RLS decides what is in it. */}
                <Route
                  path="clearance"
                  element={
                    <RequireRole allow={['it', 'finance']}>
                      <ClearanceQueue />
                    </RequireRole>
                  }
                />
                <Route
                  path="analytics"
                  element={
                    <RequireRole allow={['hr']}>
                      <Analytics />
                    </RequireRole>
                  }
                />
                {/* Open to everyone. The list is scoped by RLS — you see runs
                    you triggered, a manager sees their reports', HR sees all —
                    and the person most entitled to check whether the assistant
                    made something up is the person it answered. */}
                <Route path="agent-trace" element={<AgentTrace />} />
              </Route>
            </Route>

            <Route path="*" element={<NotFound />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

function RoleHome() {
  const { session } = useAuth()
  return <Navigate to={session ? HOME_FOR[session.role] : '/sign-in'} replace />
}

/**
 * "Needs you" means something different to each role. A manager wants their
 * team and its progress alongside the queue; HR works a much larger inbox and
 * has Progress and Analytics as separate screens already.
 */
function NeedsYouForRole() {
  const { session } = useAuth()
  return session?.role === 'manager' ? <ManagerHome /> : <NeedsYou />
}
