import { Outlet, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import BdsRepRoute from './components/BdsRepRoute'
import ProtectedRoute from './components/ProtectedRoute'
import TopNav from './components/TopNav'
import FirmDetailPage from './pages/FirmDetailPage'
import HistoryPage from './pages/HistoryPage'
import LoginPage from './pages/LoginPage'
import ManagementPage from './pages/ManagementPage'
import ResultsPage from './pages/ResultsPage'
import UploadPage from './pages/UploadPage'

function Layout() {
  return (
    <>
      <TopNav />
      <Outlet />
    </>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<Layout />}>
            <Route path="/" element={<UploadPage />} />
            <Route path="/results/:id" element={<ResultsPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route element={<BdsRepRoute />}>
              <Route path="/management" element={<ManagementPage />} />
              <Route path="/management/firms/:id" element={<FirmDetailPage />} />
            </Route>
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  )
}
