import './pwa/update'
import { PeoplePage } from './features/people'
import { CompaniesPage } from './features/company-tools'
import { ExportsPage } from './features/exports'
import { CapturePage } from './features/capture'
import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { api, ApiError } from './api/client'
import { LibraryProvider, ToastProvider } from './app/providers'
import { Layout } from './app/layout'
import { AuthPage } from './features/auth'
import { HomePage } from './features/home'
import { ExposPage } from './features/expos'
import { UploadPage } from './features/upload'
import { LibraryPage } from './features/library'
import { DetailPage } from './features/detail'
import { SettingsPage, HealthPage } from './features/settings'
import { ReviewPage } from './features/review'
import { CompanyPage } from './features/company'
import { GroupingPage } from './features/grouping'
import { Empty, Loading } from './components/ui'
import './app.css'

function App() {
  const [signedIn, setSignedIn] = useState(false)
  const [expired, setExpired] = useState(false)
  const session = useQuery({
    queryKey: ['session', signedIn],
    queryFn: async () => {
      try {
        return await api<{ password_required: boolean }>('/auth/me', {
          signal: AbortSignal.timeout(5000),
        })
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error
        const status = await api<{ password_required: boolean }>('/auth/status')
        if (status.password_required) throw error
        await api('/auth/open', { method: 'POST' })
        return api<{ password_required: boolean }>('/auth/me')
      }
    },
    retry: false,
  })
  useEffect(() => {
    const logout = () => {
      setExpired(true)
      setSignedIn(false)
    }
    window.addEventListener('signed-out', logout)
    return () => window.removeEventListener('signed-out', logout)
  }, [])
  useEffect(() => {
    if (session.data) {
      localStorage.setItem('expo-offline-owner', '1')
      localStorage.setItem('expo-password-required', String(session.data.password_required))
    }
  }, [session.data])
  const onSignedIn = () => {
    setExpired(false)
    setSignedIn(true)
    void session.refetch()
  }
  if (expired && session.data?.password_required !== false && !session.isPending)
    return <AuthPage onSignedIn={onSignedIn} />
  if (session.isPending) return <Loading />
  const unavailable =
    session.error instanceof TypeError ||
    (session.error instanceof DOMException && session.error.name === 'TimeoutError')
  if (
    (!session.data || session.isError) &&
    !signedIn &&
    !(unavailable && localStorage.getItem('expo-offline-owner') === '1')
  )
    return <AuthPage onSignedIn={onSignedIn} />
  return (
    <LibraryProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<HomePage />} />
            <Route path="library" element={<LibraryPage />} />
            <Route path="library/people" element={<PeoplePage />} />
            <Route path="library/companies" element={<CompaniesPage />} />
            <Route path="expos" element={<ExposPage />} />
            <Route path="capture" element={<CapturePage />} />
            <Route path="upload" element={<UploadPage />} />
            <Route path="documents/:id" element={<DetailPage />} />
            <Route
              path="settings"
              element={
                <SettingsPage
                  passwordRequired={
                    session.data?.password_required ??
                    localStorage.getItem('expo-password-required') !== 'false'
                  }
                  onSignedOut={() => {
                    localStorage.removeItem('expo-offline-owner')
                    setSignedIn(false)
                    void session.refetch()
                  }}
                />
              }
            />
            <Route path="health" element={<HealthPage />} />
            <Route path="review" element={<ReviewPage />} />
            <Route path="companies/:id" element={<CompanyPage />} />
            <Route path="grouping" element={<GroupingPage />} />
            <Route path="exports" element={<ExportsPage />} />
            <Route
              path="*"
              element={
                <Empty
                  title="Page not found"
                  description="Use the navigation to return to your library."
                />
              }
            />
          </Route>
        </Routes>
      </BrowserRouter>
    </LibraryProvider>
  )
}

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 15000 } } })
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <App />
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
)
