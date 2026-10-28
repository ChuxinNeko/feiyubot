import { useEffect, useState } from "react"
import { NavLink, Outlet, useNavigate } from "react-router-dom"
import {
  Bot,
  Brain,
  Cable,
  Fish,
  LogOut,
  Menu,
  MessageCircle,
  Settings,
  Sparkles,
} from "lucide-react"
import { api } from "@/lib/api"
import type { Status } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"

const NAV = [
  { to: "/", label: "对话", icon: MessageCircle, end: true },
  { to: "/memory", label: "记忆", icon: Brain, end: false },
  { to: "/providers", label: "模型", icon: Bot, end: false },
  { to: "/personas", label: "人格", icon: Sparkles, end: false },
  { to: "/connection", label: "连接 QQ", icon: Cable, end: false },
  { to: "/settings", label: "设置", icon: Settings, end: false },
]

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-1">
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          onClick={onNavigate}
          className={({ isActive }) =>
            `flex items-center gap-2 rounded-lg px-3 py-2 text-sm ${isActive ? "bg-muted font-medium text-foreground" : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"}`
          }
        >
          <item.icon />
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}

export function Shell() {
  const navigate = useNavigate()
  const [status, setStatus] = useState<Status | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => {
    let stopped = false
    const load = () => {
      api<Status>("/api/status")
        .then((next) => {
          if (!stopped) setStatus(next)
        })
        .catch(() => {})
    }
    load()
    const timer = window.setInterval(load, 15000)
    return () => {
      stopped = true
      window.clearInterval(timer)
    }
  }, [])

  async function logout() {
    await api("/api/logout", { method: "POST", body: "{}" })
    window.location.assign("/")
  }

  const ready = status?.providers.some((item) => item.enabled) ?? false
  const connected = status?.onebot.connected.length ?? 0

  return (
    <div className="flex min-h-svh bg-background">
      <aside className="hidden w-60 shrink-0 flex-col border-r md:flex">
        <div className="flex items-center gap-2 px-5 py-5">
          <Fish className="size-5" />
          <div>
            <div className="font-heading text-base font-medium">飞鱼</div>
            <div className="text-xs text-muted-foreground">QQ 陪伴</div>
          </div>
        </div>
        <div className="px-3">
          <NavItems />
        </div>
        <div className="mt-auto space-y-2 px-4 py-4 text-xs text-muted-foreground">
          <div>{ready ? "模型已就绪" : "还没有可用模型"}</div>
          <div>{connected > 0 ? `QQ 已连接 ${connected} 个` : "QQ 还没连上"}</div>
          <Button variant="ghost" size="sm" className="px-0" onClick={() => void logout()}>
            <LogOut />
            退出
          </Button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center gap-2 border-b px-4 md:hidden">
          <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="打开菜单">
                <Menu />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-64">
              <SheetHeader>
                <SheetTitle>飞鱼</SheetTitle>
              </SheetHeader>
              <NavItems onNavigate={() => setMenuOpen(false)} />
            </SheetContent>
          </Sheet>
          <span className="font-medium">飞鱼</span>
        </header>
        {status?.password_is_default ? (
          <div className="border-b bg-muted/60 px-4 py-2 text-sm">
            管理密码还是示例值。到
            <button className="mx-1 underline" type="button" onClick={() => navigate("/settings")}>
              设置
            </button>
            里改掉。
          </div>
        ) : null}
        <main className="min-h-0 flex-1 overflow-auto p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
