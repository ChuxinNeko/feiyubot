import { useEffect, useState, type FormEvent } from "react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import type { ExtensionInfo, Settings } from "@/lib/types"
import { Field } from "@/components/field"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"

type FormState = {
  bot_name: string
  wake_mode: string
  wake_words: string
  keep_recent: string
  compress_after: string
  context_token_budget: string
  temperature: string
  max_tokens: string
  memory_update_every: string
  max_retries: string
  min_interval_seconds: string
  group_whitelist: string
  group_blacklist: string
  knowledge: string
}

export function SettingsPage() {
  const [form, setForm] = useState<FormState | null>(null)
  const [extensions, setExtensions] = useState<ExtensionInfo[]>([])
  const [oldPassword, setOldPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")

  useEffect(() => {
    Promise.all([api<Settings>("/api/settings"), api<ExtensionInfo[]>("/api/extensions")])
      .then(([settings, loaded]) => {
        setExtensions(loaded)
        setForm({
          bot_name: settings.bot_name,
          wake_mode: settings.wake_mode,
          wake_words: settings.wake_words.join(","),
          keep_recent: String(settings.keep_recent),
          compress_after: String(settings.compress_after),
          context_token_budget: String(settings.context_token_budget),
          temperature: String(settings.temperature),
          max_tokens: String(settings.max_tokens),
          memory_update_every: String(settings.memory_update_every),
          max_retries: String(settings.max_retries),
          min_interval_seconds: String(settings.min_interval_seconds),
          group_whitelist: settings.group_whitelist.join(","),
          group_blacklist: settings.group_blacklist.join(","),
          knowledge: settings.knowledge,
        })
      })
      .catch((error: unknown) => toast.error(error instanceof Error ? error.message : "加载失败"))
  }, [])

  function update(key: keyof FormState, value: string) {
    setForm((current) => current ? { ...current, [key]: value } : current)
  }

  async function save() {
    if (!form) return
    const disabled = extensions.filter((item) => !item.enabled).map((item) => item.name)
    try {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          ...form,
          keep_recent: Number(form.keep_recent),
          compress_after: Number(form.compress_after),
          context_token_budget: Number(form.context_token_budget),
          temperature: Number(form.temperature),
          max_tokens: Number(form.max_tokens),
          memory_update_every: Number(form.memory_update_every),
          max_retries: Number(form.max_retries),
          min_interval_seconds: Number(form.min_interval_seconds),
          memory_enabled: true,
          disabled_extensions: disabled,
        }),
      })
      toast.success("设置已保存")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存失败")
    }
  }

  async function changePassword(event: FormEvent) {
    event.preventDefault()
    try {
      await api("/api/password", { method: "POST", body: JSON.stringify({ old: oldPassword, new: newPassword }) })
      setOldPassword("")
      setNewPassword("")
      toast.success("密码已更新，其他登录会退出")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "修改失败")
    }
  }

  if (!form) return <p className="text-sm text-muted-foreground">正在读取设置…</p>

  return (
    <div className="mx-auto grid max-w-3xl gap-4">
      <div>
        <h1 className="font-heading text-xl font-medium">设置</h1>
        <p className="text-sm text-muted-foreground">先决定它什么时候开口，再决定记性。改完要点保存。</p>
      </div>
      <Card className="grid gap-4 p-5">
        <h2 className="font-medium">什么时候开口</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="名字">
            <Input value={form.bot_name} onChange={(event) => update("bot_name", event.target.value)} />
          </Field>
          <Field label="群里怎么接话" hint="没开口的消息仍会记下来，下次被叫到还能接上。">
            <Select value={form.wake_mode} onValueChange={(value) => update("wake_mode", value)}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="at">被 @ 或回复才说话</SelectItem>
                <SelectItem value="keyword">听到关键词，或被 @ 时说话</SelectItem>
                <SelectItem value="always">每句话都接</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label="关键词" hint="用逗号分开">
            <Input value={form.wake_words} onChange={(event) => update("wake_words", event.target.value)} />
          </Field>
          <Field label="连续回复的最短间隔（秒）" hint="有人 @ 它时不受这个限制。">
            <Input type="number" step="0.1" value={form.min_interval_seconds} onChange={(event) => update("min_interval_seconds", event.target.value)} />
          </Field>
        </div>
      </Card>
      <Card className="grid gap-4 p-5">
        <h2 className="font-medium">记性</h2>
        <p className="text-sm text-muted-foreground">全部原文都在数据库里。发给模型的是最近几句原文，加上更早内容的摘要和长期记忆。</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="原文保留条数" hint="建议 40。太小会过早变成摘要。">
            <Input type="number" value={form.keep_recent} onChange={(event) => update("keep_recent", event.target.value)} />
          </Field>
          <Field label="再多几条才开始压缩">
            <Input type="number" value={form.compress_after} onChange={(event) => update("compress_after", event.target.value)} />
          </Field>
          <Field label="上下文预算" hint="估算的 token。超出后会把更早的原文收进摘要。">
            <Input type="number" value={form.context_token_budget} onChange={(event) => update("context_token_budget", event.target.value)} />
          </Field>
          <Field label="每隔几条用户消息整理长期记忆">
            <Input type="number" value={form.memory_update_every} onChange={(event) => update("memory_update_every", event.target.value)} />
          </Field>
        </div>
      </Card>
      <Card className="grid gap-4 p-5">
        <h2 className="font-medium">模型回复</h2>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="温度">
            <Input type="number" step="0.1" value={form.temperature} onChange={(event) => update("temperature", event.target.value)} />
          </Field>
          <Field label="单次最多 token">
            <Input type="number" value={form.max_tokens} onChange={(event) => update("max_tokens", event.target.value)} />
          </Field>
          <Field label="每家失败后重试">
            <Input type="number" value={form.max_retries} onChange={(event) => update("max_retries", event.target.value)} />
          </Field>
        </div>
        <Separator />
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="只在这些群说话" hint="留空表示所有群。填群号，逗号分开。">
            <Input value={form.group_whitelist} onChange={(event) => update("group_whitelist", event.target.value)} />
          </Field>
          <Field label="不要进这些群">
            <Input value={form.group_blacklist} onChange={(event) => update("group_blacklist", event.target.value)} />
          </Field>
        </div>
        <Field label="所有对话都带上的补充资料">
          <Textarea value={form.knowledge} onChange={(event) => update("knowledge", event.target.value)} />
        </Field>
        {extensions.length > 0 ? (
          <div className="grid gap-2">
            <h3 className="text-sm font-medium">扩展</h3>
            {extensions.map((item) => (
              <div key={item.name} className="flex items-center justify-between rounded-lg border px-3 py-2">
                <div>
                  <div className="text-sm">{item.name}</div>
                  <div className="text-xs text-muted-foreground">{item.doc}</div>
                </div>
                <Switch
                  checked={item.enabled}
                  onCheckedChange={(checked) => setExtensions((current) => current.map((entry) => entry.name === item.name ? { ...entry, enabled: checked } : entry))}
                />
              </div>
            ))}
          </div>
        ) : null}
        <div>
          <Button onClick={() => void save()}>保存设置</Button>
        </div>
      </Card>
      <Card className="p-5">
        <h2 className="font-medium">管理密码</h2>
        <p className="mt-1 text-sm text-muted-foreground">改密码会退出其他浏览器。当前这个页面会保持登录。</p>
        <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={(event) => void changePassword(event)}>
          <Field label="原密码">
            <Input type="password" value={oldPassword} onChange={(event) => setOldPassword(event.target.value)} />
          </Field>
          <Field label="新密码">
            <Input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
          </Field>
          <div>
            <Button type="submit" variant="outline">更新密码</Button>
          </div>
        </form>
      </Card>
    </div>
  )
}
