import { useEffect, useState } from "react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import type { Persona } from "@/lib/types"
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
import { Card } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"

export function PersonasPage() {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<Persona | null>(null)
  const [name, setName] = useState("")
  const [prompt, setPrompt] = useState("")
  const [activate, setActivate] = useState(false)
  const [removing, setRemoving] = useState<Persona | null>(null)

  async function load() {
    setPersonas(await api<Persona[]>("/api/personas"))
  }

  useEffect(() => {
    load().catch((error: unknown) => toast.error(error instanceof Error ? error.message : "加载失败"))
  }, [])

  function openCreate() {
    setEditing(null)
    setName("")
    setPrompt("")
    setActivate(false)
    setOpen(true)
  }

  function openEdit(persona: Persona) {
    setEditing(persona)
    setName(persona.name)
    setPrompt(persona.prompt)
    setActivate(false)
    setOpen(true)
  }

  async function save() {
    try {
      const payload = { name, prompt, activate }
      if (editing) {
        await api(`/api/personas/${editing.id}`, { method: "PUT", body: JSON.stringify(payload) })
      } else {
        await api("/api/personas", { method: "POST", body: JSON.stringify(payload) })
      }
      toast.success("人格已保存")
      setOpen(false)
      await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存失败")
    }
  }

  async function activatePersona(persona: Persona) {
    await api(`/api/personas/${persona.id}/activate`, { method: "POST", body: "{}" })
    toast.success(`之后默认用「${persona.name}」`)
    await load()
  }

  async function remove(persona: Persona) {
    try {
      await api(`/api/personas/${persona.id}`, { method: "DELETE" })
      toast.success("已删除")
      setRemoving(null)
      await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除失败")
    }
  }

  return (
    <div className="mx-auto grid max-w-3xl gap-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="font-heading text-xl font-medium">人格</h1>
          <p className="text-sm text-muted-foreground">这是每次请求前注入的提示词。群可以在记忆页单独换一个。</p>
        </div>
        <Button onClick={openCreate}>添加人格</Button>
      </div>
      <div className="grid gap-3">
        {personas.map((persona) => (
          <Card key={persona.id} className="gap-3 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="font-medium">{persona.name}</h2>
                  {persona.is_active ? <Badge>默认</Badge> : null}
                </div>
                <p className="mt-2 line-clamp-3 text-sm text-muted-foreground">{persona.prompt}</p>
              </div>
              <div className="flex gap-2">
                {persona.is_active ? null : <Button variant="outline" onClick={() => void activatePersona(persona)}>用作默认</Button>}
                <Button onClick={() => openEdit(persona)}>编辑</Button>
              </div>
            </div>
            {personas.length > 1 ? (
              <div>
                <Button variant="ghost" className="text-destructive" onClick={() => setRemoving(persona)}>删除</Button>
              </div>
            ) : null}
          </Card>
        ))}
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? "编辑人格" : "添加人格"}</DialogTitle>
            <DialogDescription>用你希望它怎么说话的口吻写。不要把密钥写在这里。</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <Field label="名称">
              <Input value={name} onChange={(event) => setName(event.target.value)} />
            </Field>
            <Field label="提示词">
              <Textarea className="min-h-40" value={prompt} onChange={(event) => setPrompt(event.target.value)} />
            </Field>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <div className="text-sm">保存后用作默认人格</div>
              <Switch checked={activate} onCheckedChange={setActivate} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>取消</Button>
            <Button onClick={() => void save()}>保存</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <AlertDialog open={removing !== null} onOpenChange={(next) => { if (!next) setRemoving(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除「{removing?.name}」？</AlertDialogTitle>
            <AlertDialogDescription>至少要留一个人格。正在使用它的会话会回到默认人格。</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => { if (removing) void remove(removing) }}>删除</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
