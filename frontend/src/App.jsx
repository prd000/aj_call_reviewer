import { Routes, Route } from 'react-router-dom'
import TopNav from './components/TopNav'
import UploadPage from './pages/UploadPage'
import ProcessingPage from './pages/ProcessingPage'
import ResultsPage from './pages/ResultsPage'
import HistoryPage from './pages/HistoryPage'

export default function App() {
  return (
    <>
      <TopNav />
      <Routes>
        <Route path="/" element={<UploadPage />} />
        <Route path="/processing/:id" element={<ProcessingPage />} />
        <Route path="/results/:id" element={<ResultsPage />} />
        <Route path="/history" element={<HistoryPage />} />
      </Routes>
    </>
  )
}
