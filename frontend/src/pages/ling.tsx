import { useEffect, useState } from "react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import { Field } from "@/components/field"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"

type LingView = {
  config: Record<string, string | number | boolean | string[]>
  atoms: number
  night: { asleep?: boolean; energy?: number }
  stage: { label?: string; cycle?: number; minutes_left?: number } | null
  diary: { id: number; day: string; body: string }[]
  dreams: { id: number; body: string; level: number }[]
  recent_atoms: { id: number; content: string; level: number }[]
  compat?: string
}

export function LingPage() {
  const [view, setView] = useState<LingView | null>(null)
  const [threshold, setThreshold] = useState("35")
  const [bubbles, setBubbles] = useState("2")
  const [hours, setHours] = useState("09:00-03:30")
  const [forgetting, setForgetting] = useState("balanced")
  const [wake, setWake] = useState("private_only")
  const [sleep, setSleep] = useState(true)
  const [enabled, setEnabled] = useState(true)
  const [proactive, setProactive] = useState(false)
  const [cookie, setCookie] = useState("")
  const [uin, setUin] = useState("")
  const [writeQzone, setWriteQzone] = useState(false)
  const [styleHint, setStyleHint] = useState(true)
  const [admins, setAdmins] = useState("")
  const [keyword, setKeyword] = useState("")
  const [forgetWord, setForgetWord] = useState("")
  const [signature, setSignature] = useState("")

  function apply(next: LingView) {
    setView(next)
    const cfg = next.config
    setThreshold(String(cfg.reply_threshold ?? 35))
    setBubbles(String(cfg.max_bubbles_group ?? 2))
    setHours(String(cfg.active_hours ?? "09:00-03:30"))
    setForgetting(String(cfg.forgetting_mode ?? "balanced"))
    setWake(String(cfg.wake_mode ?? "private_only"))
    setSleep(Boolean(cfg.allow_sleep))
    setEnabled(Boolean(cfg.enabled))
    setProactive(Boolean(cfg.proactive_enabled))
    setUin(String(cfg.qzone_uin ?? ""))
    setWriteQzone(Boolean(cfg.qzone_allow_write))
    setStyleHint(cfg.style_hint !== false)
    setAdmins(Array.isArray(cfg.extra_admins) ? cfg.extra_admins.join(", ") : "")
    setCookie("")
  }

  async function load() {
    apply(await api<LingView>("/api/ling"))
  }

  useEffect(() => {
    load().catch((error: unknown) => toast.error(error instanceof Error ? error.message : "加载失败"))
  }, [])

  async function save() {
    try {
      const payload: Record<string, unknown> = {
        enabled,
        reply_threshold: Number(threshold),
        max_bubbles_group: Number(bubbles),
        active_hours: hours,
        forgetting_mode: forgetting,
        wake_mode: wake,
        allow_sleep: sleep,
        proactive_enabled: proactive,
        qzone_uin: uin,
        qzone_allow_write: writeQzone,
        style_hint: styleHint,
        extra_admins: admins,
      }
      if (cookie.trim()) payload.qzone_cookie = cookie.trim()
      await api("/api/ling", { method: "PUT", body: JSON.stringify(payload) })
      toast.success("从绫的设置已保存")
      await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存失败")
    }
  }

  async function diary() {
    try {
      const result = await api<{ body: string }>("/api/ling/diary", { method: "POST", body: "{}" })
      toast.success(result.body.slice(0, 40))
      await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "没写出来")
    }
  }

  async function dream() {
    try {
      await api("/api/ling/dream", { method: "POST", body: "{}" })
      toast.success("做了一段")
      await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "没做成")
    }
  }

  async function forget() {
    if (!forgetWord.trim()) return
    try {
      const result = await api<{ count: number }>("/api/ling/forget", {
        method: "POST",
        body: JSON.stringify({ keyword: forgetWord.trim() }),
      })
      toast.success(result.count ? `忘掉了 ${result.count} 条` : "没找到相关的记忆")
      setForgetWord("")
      await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "没忘掉")
    }
  }

  async function sign() {
    try {
      const result = await api<{ text: string }>("/api/ling/signature", {
        method: "POST",
        body: JSON.stringify({ text: signature }),
      })
      toast.success(result.text)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "没改成")
    }
  }

  if (!view) return <p className="text-sm text-muted-foreground">正在打开从绫…</p>

  const stage = view.stage
  const energy = Math.round(Number(view.night.energy ?? 100))
  const shown = view.recent_atoms.filter((atom) => !keyword.trim() || atom.content.includes(keyword.trim()))

  return (
    <div className="mx-auto grid max-w-3xl gap-4">
      <div>
        <h1 className="font-heading text-xl font-medium">从绫</h1>
        <p className="text-sm text-muted-foreground">
          群里不每句都接，说短句，记得住的事会分级，累了会睡。群里说 /绫 状态 也能看。
        </p>
      </div>
      <Card className="grid gap-2 p-5 text-sm">
        <div>活跃记忆 {view.atoms} 条 · 精力 {energy}</div>
        <div>{view.night.asleep ? `${stage?.label ?? "在睡"} · 第 ${stage?.cycle ?? 1} 个周期` : "醒着"}</div>
      </Card>
      <Card className="grid gap-4 p-5">
        <h2 className="font-medium">什么时候开口</h2>
        <div className="flex items-center justify-between">
          <span className="text-sm">启用从绫</span>
          <Switch checked={enabled} onCheckedChange={setEnabled} />
        </div>
        <div className="flex items-center justify-between">
          <span className="text-sm">带上短句口气</span>
          <Switch checked={styleHint} onCheckedChange={setStyleHint} />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="群里开口的门槛" hint="被 @ 是 100 分。默认 35，聊开了会再降 15。">
            <Input value={threshold} onChange={(event) => setThreshold(event.target.value)} />
          </Field>
          <Field label="群里最多几条">
            <Input value={bubbles} onChange={(event) => setBubbles(event.target.value)} />
          </Field>
          <Field label="肯说话的时段" hint="跨过午夜就写成 09:00-03:30">
            <Input value={hours} onChange={(event) => setHours(event.target.value)} />
          </Field>
          <Field label="遗忘">
            <Select value={forgetting} onValueChange={setForgetting}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="off">不淡忘</SelectItem>
                <SelectItem value="dream">忘得快</SelectItem>
                <SelectItem value="balanced">均衡</SelectItem>
                <SelectItem value="ebbinghaus">记得更久</SelectItem>
              </SelectContent>
            </Select>
          </Field>
        </div>
      </Card>
      <Card className="grid gap-4 p-5">
        <h2 className="font-medium">长夜</h2>
        <div className="flex items-center justify-between">
          <span className="text-sm">允许睡着</span>
          <Switch checked={sleep} onCheckedChange={setSleep} />
        </div>
        <Field label="谁叫得醒">
          <Select value={wake} onValueChange={setWake}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="private_only">只有私聊和网页</SelectItem>
              <SelectItem value="both">群里也能叫</SelectItem>
              <SelectItem value="never">叫不醒</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => void dream()}>现在做一段梦</Button>
          <Button variant="outline" onClick={() => void diary()}>写今天的日记</Button>
        </div>
        {view.dreams[0] ? <p className="text-sm text-muted-foreground">{view.dreams[0].body}</p> : null}
        {view.diary[0] ? <p className="text-sm">{view.diary[0].day} · {view.diary[0].body}</p> : null}
      </Card>
      <Card className="grid gap-3 p-5">
        <h2 className="font-medium">它记住的人</h2>
        <Field label="搜索">
          <Input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="名字、约定、禁区" />
        </Field>
        {shown.length === 0 ? <p className="text-sm text-muted-foreground">还没有。带「记住」的话会马上写进来。</p> : null}
        {shown.map((atom) => (
          <div key={atom.id} className="text-sm">{atom.level} 级 · {atom.content}</div>
        ))}
        <div className="flex gap-2">
          <Input value={forgetWord} onChange={(event) => setForgetWord(event.target.value)} placeholder="忘掉含这个词的记忆" />
          <Button variant="outline" onClick={() => void forget()}>忘掉</Button>
        </div>
      </Card>
      <Card className="grid gap-3 p-5">
        <h2 className="font-medium">和别的能力怎么相处</h2>
        <p className="text-sm text-muted-foreground">{String(view.compat || "")}</p>
        <Field label="额外管理员" hint="一行一个或用逗号分开。网页登录的人本来就能改。群主默认不算。">
          <Input value={admins} onChange={(event) => setAdmins(event.target.value)} />
        </Field>
      </Card>
      <Card className="grid gap-3 p-5">
        <h2 className="font-medium">空间和主动找人</h2>
        <div className="flex items-center justify-between">
          <span className="text-sm">主动找人</span>
          <Switch checked={proactive} onCheckedChange={setProactive} />
        </div>
        <div className="flex items-center justify-between">
          <span className="text-sm">允许发说说</span>
          <Switch checked={writeQzone} onCheckedChange={setWriteQzone} />
        </div>
        <Field label="QQ 号">
          <Input value={uin} onChange={(event) => setUin(event.target.value)} />
        </Field>
        <Field label="空间 cookie" hint={view.config.qzone_cookie ? "已经有一份。留空表示不改。" : "协议端没有 cookie 时再填。"}>
          <Input type="password" value={cookie} autoComplete="off" onChange={(event) => setCookie(event.target.value)} />
        </Field>
        <Field label="个性签名" hint="没连上 QQ 时会告诉你，不会假装已经改了。">
          <Input value={signature} onChange={(event) => setSignature(event.target.value)} />
        </Field>
        <Button variant="outline" onClick={() => void sign()}>改签名</Button>
        <p className="text-xs text-muted-foreground">群里：/绫 状态、/绫 记忆、/绫 记住、/绫 兼容、/绫 名片。戳一戳会在一分钟后才能再回戳。</p>
      </Card>
      <div>
        <Button onClick={() => void save()}>保存这一页</Button>
      </div>
    </div>
  )
}
