import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

// The demo persists its watchlist/portfolio through window.storage (an API
// provided by the environment it was originally authored for). Standalone,
// back it with localStorage so state survives a page reload.
if (!window.storage) {
  window.storage = {
    async get(key) {
      const raw = localStorage.getItem(key)
      return raw != null ? { value: raw } : null
    },
    async set(key, value) {
      localStorage.setItem(key, value)
    },
  }
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
