import { useEffect, useState } from "react"
import { Navigate, Route, Routes } from "react-router-dom"
import { setUnauthorizedHandler } from "@/lib/api"
import { api } from "@/lib/api"
import { Shell } from "@/components/shell"
import { ChatPage } from "@/pages/chat"
import { ConnectionPage } from "@/pages/connection"
import { LoginPage } from "@/pages/login"
import { MemoryPage } from "@/pages/memory"
import { PersonasPage } from "@/pages/personas"
import { ProvidersPage } from "@/pages/providers"
import { LingPage } from "@/pages/ling"
import { SettingsPage } from "@/pages/settings"

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null)

  useEffect(() => {
    setUnauthorizedHandler(() => setAuthed(false))
    api("/api/me").then(() => setAuthed(true)).catch(() => setAuthed(false))
  }, [])

  if (authed === null) {
    return <div className="grid min-h-svh place-items-center text-sm text-muted-foreground">正在打开飞鱼…</div>
  }
  if (!authed) return <LoginPage onSuccess={() => setAuthed(true)} />

  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<ChatPage />} />
        <Route path="memory" element={<MemoryPage />} />
        <Route path="providers" element={<ProvidersPage />} />
        <Route path="personas" element={<PersonasPage />} />
        <Route path="connection" element={<ConnectionPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="ling" element={<LingPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
