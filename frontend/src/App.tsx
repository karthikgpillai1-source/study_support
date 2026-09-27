import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from '@/components/AppShell'
import { Spinner } from '@/components/ui'
import { AuthProvider } from '@/context/AuthContext'
import { useAuth } from '@/context/auth-context'
import { AnalysisPage } from '@/pages/AnalysisPage'
import { AuthPage } from '@/pages/AuthPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { LandingPage } from '@/pages/LandingPage'
import { NewSubjectPage } from '@/pages/NewSubjectPage'
import { PlannerPage } from '@/pages/PlannerPage'
import { SubjectPage } from '@/pages/SubjectPage'
import { TeamPage } from '@/pages/TeamPage'
import { UploadPage } from '@/pages/UploadPage'

function RequireAuth() {
  const { user, loading } = useAuth()
  if (loading) return <Spinner label="Checking your session" />
  if (!user) return <Navigate to="/login" replace />
  return <AppShell />
}

function RedirectIfAuthed({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <Spinner label="Checking your session" />
  if (user) return <Navigate to="/dashboard" replace />
  return <>{children}</>
}

function ScrollToTop() {
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [])
  return null
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <ScrollToTop />
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route
            path="/login"
            element={
              <RedirectIfAuthed>
                <AuthPage mode="login" />
              </RedirectIfAuthed>
            }
          />
          <Route
            path="/register"
            element={
              <RedirectIfAuthed>
                <AuthPage mode="register" />
              </RedirectIfAuthed>
            }
          />

          <Route element={<RequireAuth />}>
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/subjects/new" element={<NewSubjectPage />} />
            <Route path="/subjects/:subjectId" element={<SubjectPage />} />
            <Route path="/subjects/:subjectId/analysis" element={<AnalysisPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/subjects/:subjectId/upload" element={<UploadPage />} />
            <Route path="/planner" element={<PlannerPage />} />
            <Route path="/subjects/:subjectId/planner" element={<PlannerPage />} />
            <Route path="/team" element={<TeamPage />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
