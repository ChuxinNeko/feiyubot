import { useEffect, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { toast } from "sonner"
import { api } from "@/lib/api"
import type { Persona, SessionDetail, SessionSummary } from "@/lib/types"
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
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"

type MemoryForm = {
  title: string
  wake_mode: string
  persona_id: string
  enabled: string
  memory_notes: string
  summary: string
  knowledge: string
}

export function MemoryPage() {
  const [params, setParams] = useSearchParams()
  const selected = params.get("session") ?? ""
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [personas, setPersonas] = useState<Persona[]>([])
  const [detail, setDetail] = useState<SessionDetail | null>(null)
  const [form, setForm] = useState<MemoryForm | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)

  async function loadList() {
    const [nextSessions, nextPersonas] = await Promise.all([
      api<SessionSummary[]>("/api/sessions"),
      api<Persona[]>("/api/personas"),
    ])
    setSessions(nextSessions)
    setPersonas(nextPersonas)
    if (!selected && nextSessions[0]) setParams({ session: nextSessions[0].id })
  }

  useEffect(() => {
    loadList().catch((error: unknown) => toast.error(error instanceof Error ? error.message : "加载失败"))
  }, [])

  useEffect(() => {
    if (!selected) {
      setDetail(null)
      setForm(null)
      return
    }
    api<SessionDetail>(`/api/sessions/${encodeURIComponent(selected)}`)
      .then((next) => {
        setDetail(next)
        setForm({
          title: next.title,
          wake_mode: next.wake_mode || "inherit",
          persona_id: next.persona_id || "inherit",
          enabled: next.enabled ? "1" : "0",
          memory_notes: next.memory_notes,
          summary: next.summary,
          knowledge: next.knowledge,
        })
      })
      .catch((error: unknown) => toast.error(error instanceof Error ? error.message : "打不开这段记忆"))
  }, [selected])

  async function save() {
    if (!detail || !form) return
    try {
      await api(`/api/sessions/${encodeURIComponent(detail.id)}`, {
        method: "PUT",
        body: JSON.stringify({
          title: form.title,
          wake_mode: form.wake_mode === "inherit" ? "" : form.wake_mode,
          persona_id: form.persona_id === "inherit" ? "" : form.persona_id,
          enabled: form.enabled === "1",
          memory_notes: form.memory_notes,
          summary: form.summary,
          knowledge: form.knowledge,
        }),
      })
      toast.success("记忆已保存")
      await loadList()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存失败")
    }
  }

  async function compress() {
    if (!detail) return
    try {
      await api(`/api/sessions/${encodeURIComponent(detail.id)}/compress`, { method: "POST", body: "{}" })
      toast.success("较早的对话已收成摘要")
      const next = await api<SessionDetail>(`/api/sessions/${encodeURIComponent(detail.id)}`)
      setDetail(next)
      setForm((current) => current ? { ...current, summary: next.summary } : current)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "压缩失败")
    }
  }

  async function clear() {
    if (!detail) return
    try {
      await api(`/api/sessions/${encodeURIComponent(detail.id)}/clear`, { method: "POST", body: "{}" })
      toast.success("这段上下文已清空")
      setConfirmClear(false)
      const next = await api<SessionDetail>(`/api/sessions/${encodeURIComponent(detail.id)}`)
      setDetail(next)
      setForm((current) => current ? { ...current, summary: "", memory_notes: "" } : current)
      await loadList()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "清空失败")
    }
  }

  return (
    <div className="grid h-full min-h-[32rem] gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
      <Card className="min-h-0 p-3">
        <h1 className="px-2 py-1 font-heading text-lg font-medium">记忆</h1>
        <ScrollArea className="h-[calc(100%-2rem)]">
          <div className="grid gap-1 pr-3">
            {sessions.length === 0 ? <p className="px-2 py-4 text-sm text-muted-foreground">还没有会话。去对话里说一句，或等群里有人说话。</p> : null}
            {sessions.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setParams({ session: item.id })}
                className={`rounded-lg px-3 py-2 text-left ${item.id === selected ? "bg-muted" : "hover:bg-muted/60"}`}
              >
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm">{item.title}</span>
                  <Badge variant="outline">{item.kind === "group" ? "群" : "网页"}</Badge>
                </div>
                <div className="text-xs text-muted-foreground">{item.message_count} 条</div>
              </button>
            ))}
          </div>
        </ScrollArea>
      </Card>
      {detail && form ? (
        <Card className="min-h-0 p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h2 className="font-medium">{detail.title}</h2>
              <p className="text-xs text-muted-foreground">{detail.kind === "group" ? "QQ 群" : "网页对话"} · 原文都在，清空之前不会丢</p>
            </div>
            {detail.kind === "web" ? <Button variant="outline" asChild><Link to={`/?session=${encodeURIComponent(detail.id)}`}>回到这段对话</Link></Button> : null}
          </div>
          <Tabs defaultValue="transcript">
            <TabsList>
              <TabsTrigger value="transcript">对话记录</TabsTrigger>
              <TabsTrigger value="memory">它记住的</TabsTrigger>
            </TabsList>
            <TabsContent value="transcript" className="mt-3">
              <ScrollArea className="h-[28rem] pr-3">
                <div className="grid gap-2">
                  {detail.messages.length === 0 ? <p className="text-sm text-muted-foreground">还没有消息。</p> : null}
                  {detail.messages.map((item) => (
                    <div key={item.id} className="whitespace-pre-wrap rounded-lg bg-muted/60 px-3 py-2 text-sm">
                      <span className="text-muted-foreground">{item.sender_name || (item.role === "assistant" ? "飞鱼" : "用户")}：</span>
                      {item.content}
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </TabsContent>
            <TabsContent value="memory" className="mt-3 grid gap-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="标题">
                  <Input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} />
                </Field>
                <Field label="什么时候开口" hint="只影响这个会话">
                  <Select value={form.wake_mode} onValueChange={(value) => setForm({ ...form, wake_mode: value })}>
                    <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="inherit">跟随全局设置</SelectItem>
                      <SelectItem value="at">被 @ 或回复才说话</SelectItem>
                      <SelectItem value="keyword">听到关键词才说话</SelectItem>
                      <SelectItem value="always">每句都接</SelectItem>
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="人格">
                  <Select value={form.persona_id} onValueChange={(value) => setForm({ ...form, persona_id: value })}>
                    <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="inherit">跟随默认人格</SelectItem>
                      {personas.map((persona) => <SelectItem key={persona.id} value={persona.id}>{persona.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="是否还理这个会话">
                  <Select value={form.enabled} onValueChange={(value) => setForm({ ...form, enabled: value })}>
                    <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="1">记录，并允许回复</SelectItem>
                      <SelectItem value="0">停用</SelectItem>
                    </SelectContent>
                  </Select>
                </Field>
              </div>
              <Field label="长期记忆" hint="稳定的事实。带「记住」的话会立刻写进来。">
                <Textarea value={form.memory_notes} onChange={(event) => setForm({ ...form, memory_notes: event.target.value })} />
              </Field>
              <Field label="较早对话摘要" hint="原文太长之后，更早的部分收在这里。最近的话仍以原文送给模型。">
                <Textarea value={form.summary} onChange={(event) => setForm({ ...form, summary: event.target.value })} />
              </Field>
              <Field label="只给这段对话的补充资料">
                <Textarea value={form.knowledge} onChange={(event) => setForm({ ...form, knowledge: event.target.value })} />
              </Field>
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => void save()}>保存记忆</Button>
                <Button variant="outline" onClick={() => void compress()}>把更早的对话收成摘要</Button>
                <Button variant="destructive" onClick={() => setConfirmClear(true)}>清空这段上下文</Button>
              </div>
            </TabsContent>
          </Tabs>
        </Card>
      ) : (
        <Card className="grid place-items-center p-8 text-sm text-muted-foreground">选左边一段会话。</Card>
      )}
      <AlertDialog open={confirmClear} onOpenChange={setConfirmClear}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>清空这段上下文？</AlertDialogTitle>
            <AlertDialogDescription>原文、摘要和长期记忆会去掉。人格和补充资料还留着。这件事不能撤销。</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>留下</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void clear()}>清空</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
