import { useEffect, useRef, useState, type FormEvent } from "react"
import { toast } from "sonner"
import { Link, useSearchParams } from "react-router-dom"
import { Loader2 } from "lucide-react"
import { api } from "@/lib/api"
import type { ChatMessage, Provider, SessionDetail, SessionSummary } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Textarea } from "@/components/ui/textarea"

export function ChatPage() {
  const [params, setParams] = useSearchParams()
  const sessionId = params.get("session") ?? ""
  const [providers, setProviders] = useState<Provider[] | null>(null)
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState("")
  const [waiting, setWaiting] = useState(false)
  const [pending, setPending] = useState("")
  const box = useRef<HTMLTextAreaElement>(null)
  const end = useRef<HTMLDivElement>(null)

  async function loadSessions() {
    const list = await api<SessionSummary[]>("/api/sessions?kind=web")
    setSessions(list)
  }

  useEffect(() => {
    api<Provider[]>("/api/providers").then(setProviders).catch(() => setProviders([]))
    loadSessions().catch(() => {})
  }, [])

  useEffect(() => {
    if (!sessionId) {
      setMessages([])
      return
    }
    api<SessionDetail>(`/api/sessions/${encodeURIComponent(sessionId)}`)
      .then((detail) => setMessages(detail.messages))
      .catch(() => setMessages([]))
  }, [sessionId])

  useEffect(() => {
    box.current?.focus()
  }, [sessionId, waiting])

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" })
  }, [messages, pending, waiting])

  const enabled = (providers ?? []).some((item) => item.enabled)

  async function send(event: FormEvent) {
    event.preventDefault()
    const content = draft.trim()
    if (!content || waiting) return
    setDraft("")
    setPending(content)
    setWaiting(true)
    try {
      const result = await api<{ session_id: string; text: string }>("/api/chat", {
        method: "POST",
        body: JSON.stringify({
          content,
          session_id: sessionId || null,
          title: sessionId ? undefined : content.slice(0, 18),
        }),
      })
      setPending("")
      if (result.session_id !== sessionId) {
        setParams({ session: result.session_id })
      } else {
        const detail = await api<SessionDetail>(`/api/sessions/${encodeURIComponent(result.session_id)}`)
        setMessages(detail.messages)
      }
      await loadSessions()
    } catch (error) {
      setDraft(content)
      setPending("")
      toast.error(error instanceof Error ? error.message : "发送失败")
    } finally {
      setWaiting(false)
    }
  }

  if (providers === null) {
    return <p className="text-sm text-muted-foreground">正在打开对话…</p>
  }

  if (!enabled) {
    return (
      <Card className="mx-auto max-w-lg p-8">
        <h1 className="font-heading text-xl font-medium">先接一个模型</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          飞鱼还没有可以调用的模型。添加 API 地址并保存之后，回到这里就能说话。
        </p>
        <Button className="mt-5" asChild>
          <Link to="/providers">去添加模型</Link>
        </Button>
      </Card>
    )
  }

  return (
    <div className="grid h-full min-h-[32rem] gap-4 md:grid-cols-[240px_minmax(0,1fr)]">
      <Card className="flex min-h-0 flex-col gap-2 p-3">
        <Button variant={sessionId ? "outline" : "secondary"} onClick={() => setParams({})}>新对话</Button>
        <ScrollArea className="min-h-0 flex-1">
          <div className="grid gap-1 pr-3">
            {sessions.length === 0 ? <p className="px-2 py-3 text-xs text-muted-foreground">还没有网页对话。</p> : null}
            {sessions.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setParams({ session: item.id })}
                className={`rounded-lg px-3 py-2 text-left text-sm ${item.id === sessionId ? "bg-muted" : "hover:bg-muted/60"}`}
              >
                <div className="truncate">{item.title}</div>
                <div className="text-xs text-muted-foreground">{item.message_count} 条</div>
              </button>
            ))}
          </div>
        </ScrollArea>
      </Card>
      <Card className="flex min-h-0 flex-col">
        <ScrollArea className="min-h-0 flex-1 p-4">
          <div className="mx-auto flex max-w-2xl flex-col gap-3">
            {messages.length === 0 && !pending ? (
              <p className="text-sm text-muted-foreground">直接说一句。Enter 发送，Shift+Enter 换行。想让它记住，就说「记住：…」。</p>
            ) : null}
            {messages.map((item) => (
              <Bubble key={item.id} message={item} />
            ))}
            {pending ? <Bubble message={{ id: -1, role: "user", content: pending, sender_name: "你", notice: false }} /> : null}
            {waiting ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                飞鱼正在想…
              </div>
            ) : null}
            <div ref={end} />
          </div>
        </ScrollArea>
        <form className="flex gap-2 border-t p-3" onSubmit={(event) => void send(event)}>
          <Textarea
            ref={box}
            value={draft}
            rows={2}
            placeholder="跟飞鱼说一句"
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
              }
            }}
          />
          <Button type="submit" disabled={waiting || !draft.trim()}>发送</Button>
        </form>
        {sessionId ? (
          <div className="px-4 pb-3 text-xs text-muted-foreground">
            <Link className="underline" to={`/memory?session=${encodeURIComponent(sessionId)}`}>看看这段它记住了什么</Link>
          </div>
        ) : null}
      </Card>
    </div>
  )
}

function Bubble({ message }: { message: ChatMessage }) {
  const mine = message.role === "user"
  return (
    <div className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm ${message.notice ? "bg-muted text-muted-foreground" : mine ? "ml-auto bg-primary text-primary-foreground" : "bg-muted"}`}>
      {message.content}
    </div>
  )
}
