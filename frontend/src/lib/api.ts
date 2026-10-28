export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let onUnauthorized = () => {}

export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json")
  }
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" })
  const text = await response.text()
  let body: unknown = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = { detail: text }
    }
  }
  if (!response.ok) {
    const detail = typeof body === "object" && body && "detail" in body ? String((body as { detail: unknown }).detail) : response.statusText
    if (response.status === 401 && !path.endsWith("/api/login")) onUnauthorized()
    throw new ApiError(response.status, detail || "请求失败")
  }
  return body as T
}
