import { useState, type FormEvent } from "react"
import { Fish } from "lucide-react"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

export function LoginPage({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError("")
    try {
      await api("/api/login", { method: "POST", body: JSON.stringify({ password }) })
      onSuccess()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "登录失败")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-svh place-items-center bg-muted/40 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <Fish className="size-6" />
          <CardTitle className="font-heading text-2xl">飞鱼</CardTitle>
          <CardDescription>先登录，再给它接模型和 QQ。</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="grid gap-3" onSubmit={(event) => void submit(event)}>
            <div className="grid gap-1.5">
              <Label htmlFor="password">管理密码</Label>
              <Input
                id="password"
                type="password"
                autoFocus
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              {error ? <p className="text-sm text-destructive">{error}</p> : null}
            </div>
            <Button type="submit" disabled={busy}>{busy ? "正在进入…" : "进入"}</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
