import { useEffect, useState } from "react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import type { ProbeResult, Provider } from "@/lib/types"
import { Field } from "@/components/field"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"

const PRESETS = [
  { id: "deepseek", name: "DeepSeek", base_url: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  { id: "openai", name: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  { id: "moonshot", name: "Moonshot", base_url: "https://api.moonshot.cn/v1", model: "moonshot-v1-8k" },
  { id: "qwen", name: "通义千问", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus" },
  { id: "zhipu", name: "智谱", base_url: "https://open.bigmodel.cn/api/paas/v4", model: "glm-4-flash" },
  { id: "silicon", name: "硅基流动", base_url: "https://api.siliconflow.cn/v1", model: "deepseek-ai/DeepSeek-V3" },
  { id: "ollama", name: "Ollama", base_url: "http://127.0.0.1:11434/v1", model: "qwen2.5" },
  { id: "lmstudio", name: "LM Studio", base_url: "http://127.0.0.1:1234/v1", model: "local-model" },
]

type Draft = {
  name: string
  base_url: string
  api_key: string
  model: string
  priority: string
  timeout_seconds: string
  enabled: boolean
}

const EMPTY: Draft = {
  name: "",
  base_url: "",
  api_key: "",
  model: "",
  priority: "100",
  timeout_seconds: "60",
  enabled: true,
}

export function ProviderDialog({
  open,
  provider,
  onOpenChange,
  onSaved,
}: {
  open: boolean
  provider: Provider | null
  onOpenChange: (open: boolean) => void
  onSaved: () => void
}) {
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const [preset, setPreset] = useState("custom")
  const [probe, setProbe] = useState<string>("")
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const editing = provider !== null

  useEffect(() => {
    if (!open) return
    setProbe("")
    setPreset("custom")
    setConfirmDelete(false)
    if (!provider) {
      setDraft(EMPTY)
      return
    }
    setDraft({
      name: provider.name,
      base_url: provider.base_url,
      api_key: "",
      model: provider.model,
      priority: String(provider.priority),
      timeout_seconds: String(provider.timeout_seconds),
      enabled: provider.enabled,
    })
  }, [open, provider])

  function change<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((current) => ({ ...current, [key]: value }))
  }

  async function testConnection() {
    setBusy(true)
    setProbe("正在测试…")
    try {
      const payload = {
        name: draft.name || "未保存",
        base_url: draft.base_url,
        api_key: draft.api_key,
        model: draft.model,
        timeout_seconds: Number(draft.timeout_seconds || 60),
      }
      const result = editing && !draft.api_key
        ? await api<ProbeResult>(`/api/providers/${provider.id}/test`, { method: "POST", body: "{}" })
        : await api<ProbeResult>("/api/provider-tests", { method: "POST", body: JSON.stringify(payload) })
      setProbe(result.ok ? `通了（${result.latency_ms} ms）：${result.reply}` : `失败：${result.error}`)
    } catch (error) {
      setProbe(error instanceof Error ? error.message : "测试失败")
    } finally {
      setBusy(false)
    }
  }

  async function save() {
    setBusy(true)
    try {
      const payload: Record<string, unknown> = {
        name: draft.name,
        base_url: draft.base_url,
        model: draft.model,
        priority: Number(draft.priority || 100),
        timeout_seconds: Number(draft.timeout_seconds || 60),
        enabled: draft.enabled,
      }
      if (!editing || draft.api_key) payload.api_key = draft.api_key
      if (editing) {
        await api(`/api/providers/${provider.id}`, { method: "PUT", body: JSON.stringify(payload) })
      } else {
        await api("/api/providers", { method: "POST", body: JSON.stringify(payload) })
      }
      toast.success(editing ? "模型已更新" : "模型已添加")
      onOpenChange(false)
      onSaved()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存失败")
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!provider) return
    setBusy(true)
    try {
      await api(`/api/providers/${provider.id}`, { method: "DELETE" })
      toast.success("模型已删除")
      setConfirmDelete(false)
      onOpenChange(false)
      onSaved()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除失败")
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? "编辑模型" : "添加模型"}</DialogTitle>
          <DialogDescription>
            先选服务或自己填地址，贴上密钥，测试通了再保存。数字越小越先用，上面的挂了会自动换下一家。
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <Field label="从常用服务填入" hint="只是帮你填地址和模型名，密钥仍要自己贴。">
            <Select
              value={preset}
              onValueChange={(value) => {
                setPreset(value)
                const chosen = PRESETS.find((item) => item.id === value)
                if (!chosen) return
                setDraft((current) => ({
                  ...current,
                  name: chosen.name,
                  base_url: chosen.base_url,
                  model: chosen.model,
                }))
              }}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="自己填" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="custom">自己填</SelectItem>
                {PRESETS.map((item) => (
                  <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="名称">
            <Input value={draft.name} onChange={(event) => change("name", event.target.value)} placeholder="例如 DeepSeek" />
          </Field>
          <Field label="API 地址" hint="填到 /v1 即可，飞鱼会补上 /chat/completions。">
            <Input value={draft.base_url} onChange={(event) => change("base_url", event.target.value)} placeholder="https://api.deepseek.com/v1" />
          </Field>
          <Field label="API Key" hint={editing && provider.has_api_key ? `已保存 ${provider.api_key_mask}，留空表示不改。` : "本地模型可以留空。"}>
            <Input type="password" value={draft.api_key} onChange={(event) => change("api_key", event.target.value)} autoComplete="off" />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="模型名">
              <Input value={draft.model} onChange={(event) => change("model", event.target.value)} placeholder="deepseek-chat" />
            </Field>
            <Field label="优先级" hint="越小越先用">
              <Input type="number" value={draft.priority} onChange={(event) => change("priority", event.target.value)} />
            </Field>
          </div>
          <div className="flex items-center justify-between rounded-lg border px-3 py-2">
            <div>
              <div className="text-sm">启用</div>
              <div className="text-xs text-muted-foreground">停用后不会参与失败转移</div>
            </div>
            <Switch checked={draft.enabled} onCheckedChange={(checked) => change("enabled", checked)} />
          </div>
          {probe ? <p className="text-sm text-muted-foreground">{probe}</p> : null}
        </div>
        <DialogFooter className="sm:justify-between">
          <div className="flex gap-2">
            <Button type="button" variant="outline" disabled={busy} onClick={() => void testConnection()}>
              测试连接
            </Button>
            {editing ? (
              <Button type="button" variant="ghost" className="text-destructive" disabled={busy} onClick={() => setConfirmDelete(true)}>
                删除
              </Button>
            ) : null}
          </div>
          <div className="flex gap-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>取消</Button>
            <Button type="button" disabled={busy} onClick={() => void save()}>保存</Button>
          </div>
        </DialogFooter>
      </DialogContent>
      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除「{provider?.name}」？</AlertDialogTitle>
            <AlertDialogDescription>之后飞鱼不会再调用这个地址。已经记下的对话还在。</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>留下</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void remove()}>删除</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Dialog>
    </>
  )
}
