import { useEffect, useState, type ReactNode } from "react"
import { Copy } from "lucide-react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import type { OneBotStatus } from "@/lib/types"
import { Field } from "@/components/field"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"

export function ConnectionPage() {
  const [status, setStatus] = useState<OneBotStatus | null>(null)
  const [token, setToken] = useState("")
  const [advanced, setAdvanced] = useState(false)
  const [wsUrls, setWsUrls] = useState("")

  async function load() {
    const next = await api<OneBotStatus>("/api/onebot")
    setStatus(next)
    setWsUrls(next.saved_ws_urls)
  }

  useEffect(() => {
    load().catch((error: unknown) => toast.error(error instanceof Error ? error.message : "加载失败"))
  }, [])

  if (!status) return <p className="text-sm text-muted-foreground">正在读取连接…</p>

  const reverseUrl = `${window.location.origin}${status.reverse_ws_path}`

  async function copyUrl() {
    await navigator.clipboard.writeText(reverseUrl)
    toast.success("反向地址已复制")
  }

  async function save() {
    const payload: Record<string, unknown> = {}
    if (token) payload.access_token = token
    if (advanced) {
      const raw = wsUrls.trim()
      if (raw.startsWith("[")) {
        try {
          payload.ws_urls = JSON.parse(raw)
        } catch {
          toast.error("正向地址不是合法的 JSON")
          return
        }
      } else {
        payload.ws_urls = raw ? raw.split(/[,，]/).map((item) => item.trim()).filter(Boolean) : []
      }
    }
    try {
      await api("/api/onebot", { method: "PUT", body: JSON.stringify(payload) })
      toast.success("已保存。重启飞鱼之后才会用新的连接配置")
      setToken("")
      await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存失败")
    }
  }

  return (
    <div className="mx-auto grid max-w-2xl gap-4">
      <div>
        <h1 className="font-heading text-xl font-medium">连接 QQ</h1>
        <p className="text-sm text-muted-foreground">用 NapCat 或 Lagrange 的反向 WebSocket 连过来。飞鱼把回复发回原来的群。</p>
      </div>
      <Card className="gap-4 p-5">
        <Step n={1} title="复制反向地址，填进 NapCat">
          <div className="flex gap-2">
            <Input readOnly value={reverseUrl} />
            <Button type="button" variant="outline" onClick={() => void copyUrl()}><Copy />复制</Button>
          </div>
          <p className="text-xs text-muted-foreground">HTTP 上报是 {window.location.origin}{status.http_path}。一般用反向 WS 就够了。</p>
        </Step>
        <Step n={2} title="两边填同一个令牌">
          <Field label="Access Token" hint={status.token_configured ? "当前进程已经有令牌。留空表示不改。" : "和 NapCat 里的 access token 相同。"}>
            <Input type="password" value={token} autoComplete="off" onChange={(event) => setToken(event.target.value)} />
          </Field>
        </Step>
        <Step n={3} title="保存，然后重启飞鱼">
          <p className="text-sm text-muted-foreground">令牌写在 data/runtime.env。正在跑的进程要重启后才读取。</p>
          {status.restart_required ? <Badge variant="outline">已保存的令牌和当前进程不一致</Badge> : null}
          <div>
            <Button variant="ghost" className="px-0" type="button" onClick={() => setAdvanced((value) => !value)}>
              {advanced ? "收起正向连接" : "我要让飞鱼主动连 NapCat"}
            </Button>
            {advanced ? (
              <Field label="正向 WebSocket" hint="多个用逗号隔开，以 ws:// 或 wss:// 开头。">
                <Input value={wsUrls} onChange={(event) => setWsUrls(event.target.value)} placeholder="ws://127.0.0.1:3001" />
              </Field>
            ) : null}
          </div>
          <Button onClick={() => void save()}>保存连接配置</Button>
        </Step>
      </Card>
      <Card className="p-5">
        <h2 className="font-medium">现在连上的机器人</h2>
        {status.connected.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">还没有。NapCat 连上之后，这里会出现 QQ 号。</p>
        ) : (
          <ul className="mt-3 grid gap-2">
            {status.connected.map((item) => (
              <li key={item.id} className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm">
                <span>{item.id}</span>
                <Badge variant="secondary">{item.adapter}</Badge>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="grid gap-2">
      <h2 className="text-sm font-medium">{n}. {title}</h2>
      {children}
    </section>
  )
}
