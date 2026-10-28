const app = document.querySelector("#app");
const state = { page: "overview", sessionId: "", detailId: "" };

const PAGES = [
  ["overview", "总览"],
  ["providers", "模型"],
  ["personas", "人格"],
  ["sessions", "群记忆"],
  ["chat", "网页对话"],
  ["connection", "OneBot"],
  ["settings", "设置"],
];

const PRESETS = [
  ["DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat"],
  ["OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"],
  ["Moonshot", "https://api.moonshot.cn/v1", "moonshot-v1-8k"],
  ["通义千问", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"],
  ["智谱", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"],
  ["硅基流动", "https://api.siliconflow.cn/v1", "deepseek-ai/DeepSeek-V3"],
  ["Ollama", "http://127.0.0.1:11434/v1", "qwen2.5"],
  ["LM Studio", "http://127.0.0.1:1234/v1", "local-model"],
];

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[char]));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "content-type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let body = null;
  if (text) {
    try { body = JSON.parse(text); } catch { body = { detail: text }; }
  }
  if (response.status === 401 && !path.endsWith("/api/login")) {
    renderLogin(body?.detail || "请先登录");
    throw new Error("unauthorized");
  }
  if (!response.ok) {
    const detail = body?.detail || response.statusText;
    throw new Error(typeof detail === "string" ? detail : "请求失败");
  }
  return body;
}

function fish() {
  return `<svg viewBox="0 0 64 64" aria-hidden="true">
    <ellipse cx="30" cy="32" rx="18" ry="10" fill="#f4d7b0"/>
    <polygon points="48,32 62,22 62,42" fill="#e36a3a"/>
    <circle cx="22" cy="30" r="2" fill="#142421"/>
  </svg>`;
}

function renderLogin(message = "") {
  app.innerHTML = `<div class="login-wrap"><form class="login" id="login-form">
    ${fish()}
    <h1>飞鱼</h1>
    <p class="meta">QQ 陪伴机器人的管理台</p>
    ${message ? `<p class="error">${esc(message)}</p>` : ""}
    <label>管理密码<input id="login-password" type="password" autocomplete="current-password" required></label>
    <div class="row" style="margin-top:14px"><button class="primary" type="submit">进入</button></div>
  </form></div>`;
  document.querySelector("#login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/login", { method: "POST", body: JSON.stringify({ password: document.querySelector("#login-password").value }) });
      state.page = "overview";
      await renderShell();
    } catch (error) {
      if (error.message !== "unauthorized") renderLogin(error.message);
    }
  });
}

function shell(title, subtitle, body) {
  app.innerHTML = `<div class="shell">
    <aside class="side">
      <div class="brand">${fish()}<div><h1>飞鱼</h1><p>陪伴还在</p></div></div>
      <nav class="nav">${PAGES.map(([id, name]) => `<button data-page="${id}" class="${state.page === id ? "active" : ""}">${name}</button>`).join("")}</nav>
      <button class="logout" id="logout" type="button">退出</button>
    </aside>
    <main class="main">
      <div class="top"><h2>${esc(title)}</h2><p>${esc(subtitle)}</p></div>
      <div id="flash"></div>
      ${body}
    </main>
  </div>`;
  document.querySelectorAll("[data-page]").forEach((button) => {
    button.addEventListener("click", () => { state.page = button.dataset.page; renderShell(); });
  });
  document.querySelector("#logout").addEventListener("click", async () => {
    await api("/api/logout", { method: "POST", body: "{}" });
    renderLogin();
  });
}

function flash(message, kind = "error") {
  const slot = document.querySelector("#flash");
  if (!slot) return;
  slot.innerHTML = `<div class="${kind === "error" ? "error" : "banner"}">${esc(message)}</div>`;
}

async function renderShell() {
  try {
    if (state.page === "overview") await renderOverview();
    else if (state.page === "providers") await renderProviders();
    else if (state.page === "personas") await renderPersonas();
    else if (state.page === "sessions") await renderSessions();
    else if (state.page === "chat") await renderChat();
    else if (state.page === "connection") await renderConnection();
    else await renderSettings();
  } catch (error) {
    if (error.message !== "unauthorized") flash(error.message);
  }
}

async function renderOverview() {
  const status = await api("/api/status");
  const connected = status.onebot.connected.length;
  shell("总览", "模型和群记忆都写在本地数据库里，重启不会丢。", `
    ${status.password_is_default ? `<div class="banner">管理密码还是示例值 feiyu-admin。请到「设置」里改掉。</div>` : ""}
    <section class="grid">
      <article class="card"><span>消息</span><strong>${status.message_count}</strong></article>
      <article class="card"><span>会话</span><strong>${status.session_count}</strong></article>
      <article class="card"><span>OneBot</span><strong>${connected}</strong></article>
      <article class="card"><span>当前人格</span><strong>${esc(status.active_persona?.name || "未设置")}</strong></article>
    </section>
    <section class="panel">
      <h3>模型提供商</h3>
      <div class="list">${status.providers.length ? status.providers.map((item) => `<div class="item"><h3>${esc(item.name)}</h3><div class="meta">${esc(item.model)} · ${item.enabled ? "启用" : "停用"} · <span class="${item.ok ? "ok" : "bad"}">${item.ok == null ? "未测试" : item.ok ? "可用" : esc(item.last_error || "失败")}</span></div></div>`).join("") : `<p class="meta">还没有模型。到「模型」页添加 API 地址。</p>`}</div>
    </section>
    <section class="panel">
      <h3>最近事件</h3>
      <div class="list">${(status.events || []).map((item) => `<div class="meta">${esc(item.created_at)} · ${esc(item.message)}</div>`).join("") || `<p class="meta">还没有事件。</p>`}</div>
    </section>`);
}

async function renderProviders() {
  const providers = await api("/api/providers");
  shell("模型", "填写任何 OpenAI 兼容接口。数字越小越先用，失败会自动换下一家。", `
    <section class="panel">
      <form id="provider-form" class="fields">
        <label>预设<select id="preset"><option value="">自己填</option>${PRESETS.map((item, index) => `<option value="${index}">${esc(item[0])}</option>`).join("")}</select></label>
        <label>名称<input id="p-name" required placeholder="DeepSeek"></label>
        <label>API 地址<input id="p-base" required placeholder="https://api.deepseek.com/v1"></label>
        <label>API Key<input id="p-key" type="password" placeholder="本地模型可以留空"></label>
        <label>模型名<input id="p-model" required placeholder="deepseek-chat"></label>
        <label>优先级<input id="p-priority" type="number" value="100"></label>
        <label>超时（秒）<input id="p-timeout" type="number" value="60"></label>
        <label>启用<select id="p-enabled"><option value="1">启用</option><option value="0">停用</option></select></label>
      </form>
      <div class="row" style="margin-top:12px">
        <button class="primary" id="p-save" type="button">保存</button>
        <button class="ghost" id="p-test" type="button">先测试这条</button>
      </div>
      <p id="p-result" class="meta"></p>
    </section>
    <div class="list">${providers.map((item) => `<article class="item">
      <div class="spread"><h3>${esc(item.name)} ${item.enabled ? `<span class="pill">启用</span>` : ""}</h3>
        <div class="row"><button class="ghost" data-test="${esc(item.id)}" type="button">测试</button><button class="danger" data-del="${esc(item.id)}" type="button">删除</button></div>
      </div>
      <div class="meta">${esc(item.base_url)} · ${esc(item.model)} · 优先级 ${item.priority} · Key ${item.has_api_key ? esc(item.api_key_mask) : "无"}</div>
      <div class="${item.ok ? "ok" : "bad"} meta">${item.ok == null ? "还没测试" : item.ok ? "上次可用" : esc(item.last_error)}</div>
    </article>`).join("")}</div>`);
  document.querySelector("#preset").addEventListener("change", (event) => {
    const preset = PRESETS[event.target.value];
    if (!preset) return;
    document.querySelector("#p-name").value = preset[0];
    document.querySelector("#p-base").value = preset[1];
    document.querySelector("#p-model").value = preset[2];
  });
  const payload = () => ({
    name: document.querySelector("#p-name").value,
    base_url: document.querySelector("#p-base").value,
    api_key: document.querySelector("#p-key").value,
    model: document.querySelector("#p-model").value,
    priority: Number(document.querySelector("#p-priority").value || 100),
    timeout_seconds: Number(document.querySelector("#p-timeout").value || 60),
    enabled: document.querySelector("#p-enabled").value === "1",
  });
  document.querySelector("#p-save").addEventListener("click", async () => {
    try {
      await api("/api/providers", { method: "POST", body: JSON.stringify(payload()) });
      await renderProviders();
    } catch (error) { flash(error.message); }
  });
  document.querySelector("#p-test").addEventListener("click", async () => {
    const slot = document.querySelector("#p-result");
    slot.textContent = "测试中…";
    try {
      const result = await api("/api/provider-tests", { method: "POST", body: JSON.stringify(payload()) });
      slot.textContent = result.ok ? `通了（${result.latency_ms} ms）：${result.reply}` : `失败：${result.error}`;
    } catch (error) { slot.textContent = error.message; }
  });
  document.querySelectorAll("[data-test]").forEach((button) => button.addEventListener("click", async () => {
    try {
      const result = await api(`/api/providers/${button.dataset.test}/test`, { method: "POST", body: "{}" });
      flash(result.ok ? `通了：${result.reply}` : `失败：${result.error}`, result.ok ? "info" : "error");
      if (result.ok) await renderProviders();
    } catch (error) { flash(error.message); }
  }));
  document.querySelectorAll("[data-del]").forEach((button) => button.addEventListener("click", async () => {
    if (!confirm("删除这个提供商？")) return;
    await api(`/api/providers/${button.dataset.del}`, { method: "DELETE" });
    await renderProviders();
  }));
}

async function renderPersonas() {
  const personas = await api("/api/personas");
  shell("人格", "系统提示词会在每次请求前注入。一个群可以单独换人格。", `
    <section class="panel">
      <form id="persona-form" class="fields">
        <label>名称<input id="persona-name" required></label>
        <label style="grid-column: 1 / -1">提示词<textarea id="persona-prompt" required></textarea></label>
      </form>
      <div class="row" style="margin-top:12px"><button class="primary" id="persona-save" type="button">添加</button></div>
    </section>
    <div class="list">${personas.map((item) => `<article class="item">
      <div class="spread"><h3>${esc(item.name)} ${item.is_active ? `<span class="pill">默认</span>` : ""}</h3>
        <div class="row">
          ${item.is_active ? "" : `<button class="ghost" data-act="${esc(item.id)}" type="button">设为默认</button>`}
          <button class="danger" data-del="${esc(item.id)}" type="button">删除</button>
        </div>
      </div>
      <div class="meta">${esc(item.prompt)}</div>
    </article>`).join("")}</div>`);
  document.querySelector("#persona-save").addEventListener("click", async () => {
    try {
      await api("/api/personas", { method: "POST", body: JSON.stringify({
        name: document.querySelector("#persona-name").value,
        prompt: document.querySelector("#persona-prompt").value,
      }) });
      await renderPersonas();
    } catch (error) { flash(error.message); }
  });
  document.querySelectorAll("[data-act]").forEach((button) => button.addEventListener("click", async () => {
    await api(`/api/personas/${button.dataset.act}/activate`, { method: "POST", body: "{}" });
    await renderPersonas();
  }));
  document.querySelectorAll("[data-del]").forEach((button) => button.addEventListener("click", async () => {
    try {
      await api(`/api/personas/${button.dataset.del}`, { method: "DELETE" });
      await renderPersonas();
    } catch (error) { flash(error.message); }
  }));
}

async function renderSessions() {
  const sessions = await api("/api/sessions");
  const personas = await api("/api/personas");
  shell("群记忆", "这里是全部原文、摘要和长期记忆。清空之前，它们会一直留着。", `
    <div class="split">
      <div class="list">${sessions.map((item) => `<button class="session-btn ${state.detailId === item.id ? "active" : ""}" data-session="${esc(item.id)}" type="button">
        <strong>${esc(item.title)}</strong><br><span class="meta">${esc(item.kind)} · ${item.message_count} 条</span>
      </button>`).join("") || `<p class="meta">还没有会话。去网页对话说一句，或者等群里有人说话。</p>`}</div>
      <div id="detail"><p class="meta">选一个会话查看记忆。</p></div>
    </div>`);
  document.querySelectorAll("[data-session]").forEach((button) => button.addEventListener("click", async () => {
    state.detailId = button.dataset.session;
    await renderSessions();
  }));
  if (!state.detailId) return;
  const detail = await api(`/api/sessions/${encodeURIComponent(state.detailId)}`);
  const host = document.querySelector("#detail");
  if (!host) return;
  host.innerHTML = `<section class="panel">
    <div class="spread"><h3>${esc(detail.title)}</h3><span class="meta">${esc(detail.id)}</span></div>
    <div class="fields" style="margin-top:12px">
      <label>标题<input id="s-title" value="${esc(detail.title)}"></label>
      <label>唤醒<select id="s-wake">
        <option value="" ${detail.wake_mode ? "" : "selected"}>跟随全局</option>
        <option value="at" ${detail.wake_mode === "at" ? "selected" : ""}>被 @ 才回复</option>
        <option value="keyword" ${detail.wake_mode === "keyword" ? "selected" : ""}>关键词</option>
        <option value="always" ${detail.wake_mode === "always" ? "selected" : ""}>每句都回复</option>
      </select></label>
      <label>人格<select id="s-persona"><option value="">跟随默认</option>${personas.map((item) => `<option value="${esc(item.id)}" ${detail.persona_id === item.id ? "selected" : ""}>${esc(item.name)}</option>`).join("")}</select></label>
      <label>启用<select id="s-enabled"><option value="1" ${detail.enabled ? "selected" : ""}>记录并允许回复</option><option value="0" ${detail.enabled ? "" : "selected"}>停用</option></select></label>
      <label style="grid-column:1 / -1">长期记忆<textarea id="s-notes">${esc(detail.memory_notes)}</textarea></label>
      <label style="grid-column:1 / -1">较早对话摘要<textarea id="s-summary">${esc(detail.summary)}</textarea></label>
      <label style="grid-column:1 / -1">这个会话的补充资料<textarea id="s-knowledge">${esc(detail.knowledge)}</textarea></label>
    </div>
    <div class="row" style="margin-top:12px">
      <button class="primary" id="s-save" type="button">保存记忆</button>
      <button class="ghost" id="s-compress" type="button">现在压缩</button>
      <button class="danger" id="s-clear" type="button">清空上下文</button>
    </div>
    <div class="messages" style="margin-top:14px">${detail.messages.map((item) => `<div class="msg">${esc(item.sender_name || item.role)}：${esc(item.content)}</div>`).join("")}</div>
  </section>`;
  document.querySelector("#s-save").addEventListener("click", async () => {
    await api(`/api/sessions/${encodeURIComponent(detail.id)}`, { method: "PUT", body: JSON.stringify({
      title: document.querySelector("#s-title").value,
      wake_mode: document.querySelector("#s-wake").value,
      persona_id: document.querySelector("#s-persona").value,
      enabled: document.querySelector("#s-enabled").value === "1",
      memory_notes: document.querySelector("#s-notes").value,
      summary: document.querySelector("#s-summary").value,
      knowledge: document.querySelector("#s-knowledge").value,
    }) });
    flash("已保存", "info");
  });
  document.querySelector("#s-compress").addEventListener("click", async () => {
    await api(`/api/sessions/${encodeURIComponent(detail.id)}/compress`, { method: "POST", body: "{}" });
    await renderSessions();
  });
  document.querySelector("#s-clear").addEventListener("click", async () => {
    if (!confirm("清空这段对话的原文、摘要和长期记忆？")) return;
    await api(`/api/sessions/${encodeURIComponent(detail.id)}/clear`, { method: "POST", body: "{}" });
    await renderSessions();
  });
}

async function renderChat() {
  const sessions = await api("/api/sessions?kind=web");
  let messages = [];
  if (state.sessionId) {
    const detail = await api(`/api/sessions/${encodeURIComponent(state.sessionId)}`);
    messages = detail.messages;
  }
  shell("网页对话", "和 QQ 群用同一条记忆、人格和模型链路。这里用来确认它真的记得。", `
    <div class="chat-layout">
      <div>
        <button class="primary" id="new-chat" type="button">新的对话</button>
        <div class="list">${sessions.map((item) => `<button class="session-btn ${state.sessionId === item.id ? "active" : ""}" data-open="${esc(item.id)}" type="button">${esc(item.title)}<br><span class="meta">${item.message_count} 条</span></button>`).join("")}</div>
      </div>
      <div>
        <div class="transcript" id="transcript">${messages.map(bubble).join("") || `<p class="meta">说点什么。试着告诉它一件要记住的事，多聊几句再问回来。</p>`}</div>
        <form class="composer" id="composer">
          <textarea id="chat-input" placeholder="输入消息，Enter 发送"></textarea>
          <button class="primary" type="submit">发送</button>
        </form>
      </div>
    </div>`);
  const box = document.querySelector("#transcript");
  box.scrollTop = box.scrollHeight;
  document.querySelector("#new-chat").addEventListener("click", () => { state.sessionId = ""; renderChat(); });
  document.querySelectorAll("[data-open]").forEach((button) => button.addEventListener("click", () => {
    state.sessionId = button.dataset.open;
    renderChat();
  }));
  const input = document.querySelector("#chat-input");
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      document.querySelector("#composer").requestSubmit();
    }
  });
  document.querySelector("#composer").addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = input.value.trim();
    if (!content) return;
    input.value = "";
    try {
      const result = await api("/api/chat", { method: "POST", body: JSON.stringify({ content, session_id: state.sessionId || null }) });
      state.sessionId = result.session_id;
      await renderChat();
    } catch (error) { flash(error.message); }
  });
}

function bubble(message) {
  const role = message.notice ? "notice" : message.role === "user" ? "user" : "assistant";
  return `<div class="bubble ${role}">${esc(message.content)}</div>`;
}

async function renderConnection() {
  const onebot = await api("/api/onebot");
  const origin = location.origin;
  shell("OneBot", "用 NapCat 或 Lagrange 的反向 WebSocket 连过来，飞鱼把回复发回原来的群。", `
    <section class="panel">
      <p>反向 WS：<strong>${esc(origin + onebot.reverse_ws_path)}</strong></p>
      <p class="meta">HTTP 上报：${esc(origin + onebot.http_path)} 。当前已连接 ${onebot.connected.length} 个机器人。</p>
      <div class="list">${onebot.connected.map((item) => `<div class="item"><h3>${esc(item.id)}</h3><div class="meta">${esc(item.adapter)}</div></div>`).join("") || `<p class="meta">还没有 OneBot 客户端连上来。</p>`}</div>
      <form id="onebot-form" class="fields" style="margin-top:16px">
        <label>Access Token<input id="ob-token" type="password" placeholder="${onebot.token_configured ? "已配置，留空表示不修改" : "与 NapCat 里填写的相同"}"></label>
        <label>正向 WS（可选，逗号分隔）<input id="ob-ws" value="${esc(onebot.saved_ws_urls)}" placeholder='ws://127.0.0.1:3001'></label>
      </form>
      <div class="row" style="margin-top:12px"><button class="primary" id="ob-save" type="button">保存并在重启后生效</button></div>
      ${onebot.restart_required ? `<p class="banner">已保存的令牌和当前进程不一致，重启飞鱼后才会用新令牌。</p>` : ""}
    </section>`);
  document.querySelector("#ob-save").addEventListener("click", async () => {
    const token = document.querySelector("#ob-token").value;
    const wsRaw = document.querySelector("#ob-ws").value.trim();
    const payload = {};
    if (token) payload.access_token = token;
    if (wsRaw.startsWith("[")) {
      try { payload.ws_urls = JSON.parse(wsRaw); } catch { flash("正向 WS 不是合法 JSON"); return; }
    } else if (document.querySelector("#ob-ws").value !== onebot.saved_ws_urls) {
      payload.ws_urls = wsRaw ? wsRaw.split(",").map((item) => item.trim()).filter(Boolean) : [];
    }
    try {
      await api("/api/onebot", { method: "PUT", body: JSON.stringify(payload) });
      flash("已写入 data/runtime.env，重启后生效", "info");
    } catch (error) { flash(error.message); }
  });
}

async function renderSettings() {
  const settings = await api("/api/settings");
  const extensions = await api("/api/extensions");
  shell("设置", "最近原文默认保留 40 条。更早的对话会压成摘要，加上长期记忆，所以不会几句就忘。", `
    <section class="panel">
      <form id="settings-form" class="fields">
        <label>名字<input name="bot_name" value="${esc(settings.bot_name)}"></label>
        <label>唤醒<select name="wake_mode">
          <option value="at" ${settings.wake_mode === "at" ? "selected" : ""}>被 @ 或回复才开口</option>
          <option value="keyword" ${settings.wake_mode === "keyword" ? "selected" : ""}>关键词或 @</option>
          <option value="always" ${settings.wake_mode === "always" ? "selected" : ""}>每句都回复</option>
        </select></label>
        <label>关键词（逗号分隔）<input name="wake_words" value="${esc(settings.wake_words.join(","))}"></label>
        <label>原文保留条数<input name="keep_recent" type="number" value="${settings.keep_recent}"></label>
        <label>超出多少条再压缩<input name="compress_after" type="number" value="${settings.compress_after}"></label>
        <label>上下文预算（估算 token）<input name="context_token_budget" type="number" value="${settings.context_token_budget}"></label>
        <label>温度<input name="temperature" type="number" step="0.1" value="${settings.temperature}"></label>
        <label>最大回复 token<input name="max_tokens" type="number" value="${settings.max_tokens}"></label>
        <label>每隔几条用户消息更新长期记忆<input name="memory_update_every" type="number" value="${settings.memory_update_every}"></label>
        <label>失败重试次数<input name="max_retries" type="number" value="${settings.max_retries}"></label>
        <label>群回复最小间隔（秒）<input name="min_interval_seconds" type="number" step="0.1" value="${settings.min_interval_seconds}"></label>
        <label>群白名单（空=全部）<input name="group_whitelist" value="${esc(settings.group_whitelist.join(","))}"></label>
        <label>群黑名单<input name="group_blacklist" value="${esc(settings.group_blacklist.join(","))}"></label>
        <label style="grid-column:1 / -1">全局补充资料<textarea name="knowledge">${esc(settings.knowledge)}</textarea></label>
      </form>
      <div class="row" style="margin-top:12px"><button class="primary" id="settings-save" type="button">保存设置</button></div>
    </section>
    <section class="panel">
      <h3>扩展</h3>
      ${extensions.map((item) => `<label class="row"><input type="checkbox" data-ext="${esc(item.name)}" ${item.enabled ? "checked" : ""}> ${esc(item.name)} <span class="meta">${esc(item.doc)}</span></label>`).join("") || `<p class="meta">没有扩展。</p>`}
    </section>
    <section class="panel">
      <h3>修改管理密码</h3>
      <form id="password-form" class="fields">
        <label>原密码<input id="old-password" type="password" required></label>
        <label>新密码<input id="new-password" type="password" required></label>
      </form>
      <div class="row" style="margin-top:12px"><button class="ghost" id="password-save" type="button">更新密码</button></div>
    </section>`);
  document.querySelector("#settings-save").addEventListener("click", async () => {
    const form = document.querySelector("#settings-form");
    const data = Object.fromEntries(new FormData(form).entries());
    ["keep_recent", "compress_after", "context_token_budget", "max_tokens", "memory_update_every", "max_retries"].forEach((key) => { data[key] = Number(data[key]); });
    data.temperature = Number(data.temperature);
    data.min_interval_seconds = Number(data.min_interval_seconds);
    data.memory_enabled = true;
    const disabled = extensions.filter((item) => !document.querySelector(`[data-ext="${item.name}"]`).checked).map((item) => item.name);
    data.disabled_extensions = disabled;
    try {
      await api("/api/settings", { method: "PUT", body: JSON.stringify(data) });
      flash("设置已保存", "info");
    } catch (error) { flash(error.message); }
  });
  document.querySelector("#password-save").addEventListener("click", async () => {
    try {
      await api("/api/password", { method: "POST", body: JSON.stringify({
        old: document.querySelector("#old-password").value,
        new: document.querySelector("#new-password").value,
      }) });
      flash("密码已更新", "info");
    } catch (error) { flash(error.message); }
  });
}

async function boot() {
  const response = await fetch("/api/me", { credentials: "same-origin" });
  if (response.ok) await renderShell();
  else renderLogin();
}

boot();
