import { useEffect, useState } from "react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import type { ProbeResult, Provider } from "@/lib/types"
import { ProviderDialog } from "@/components/provider-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"

export function ProvidersPage() {
  const [providers, setProviders] = useState<Provider[]>([])
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<Provider | null>(null)

  async function load() {
    setProviders(await api<Provider[]>("/api/providers"))
  }

  useEffect(() => {
    load().catch((error: unknown) => toast.error(error instanceof Error ? error.message : "加载失败"))
  }, [])

  function startCreate() {
    setEditing(null)
    setOpen(true)
  }

  function startEdit(provider: Provider) {
    setEditing(provider)
    setOpen(true)
  }

  async function testSaved(provider: Provider) {
    try {
      const result = await api<ProbeResult>(`/api/providers/${provider.id}/test`, { method: "POST", body: "{}" })
      toast[result.ok ? "success" : "error"](result.ok ? `通了：${result.reply}` : `失败：${result.error}`)
      await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "测试失败")
    }
  }

  return (
    <div className="mx-auto grid max-w-3xl gap-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="font-heading text-xl font-medium">模型</h1>
          <p className="text-sm text-muted-foreground">飞鱼按优先级从上到下调用。一家失败，就换下一家。</p>
        </div>
        <Button onClick={startCreate}>添加模型</Button>
      </div>
      {providers.length === 0 ? (
        <Card className="p-8">
          <h2 className="font-medium">还没有模型</h2>
          <p className="mt-1 text-sm text-muted-foreground">添加一个 OpenAI 兼容接口。可以是 DeepSeek、Ollama，或你自己的中转地址。</p>
          <Button className="mt-4" onClick={startCreate}>添加第一个模型</Button>
        </Card>
      ) : (
        <div className="grid gap-3">
          {providers.map((provider) => (
            <Card key={provider.id} className="gap-3 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="font-medium">{provider.name}</h2>
                    {provider.enabled ? <Badge variant="secondary">启用</Badge> : <Badge variant="outline">停用</Badge>}
                    {provider.ok === true ? <Badge>可用</Badge> : null}
                    {provider.ok === false ? <Badge variant="destructive">失败</Badge> : null}
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">{provider.model} · 优先级 {provider.priority}</p>
                  <p className="text-xs text-muted-foreground">{provider.base_url}</p>
                  {provider.ok === false && provider.last_error ? <p className="mt-1 text-xs text-destructive">{provider.last_error}</p> : null}
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={() => void testSaved(provider)}>测试</Button>
                  <Button onClick={() => startEdit(provider)}>编辑</Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
      <ProviderDialog open={open} provider={editing} onOpenChange={setOpen} onSaved={() => void load()} />
    </div>
  )
}
