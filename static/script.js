(() => {
  "use strict";

  /* ── Elements ──────────────────────────────────────────────────────── */
  const $ = (id) => document.getElementById(id);
  const app = $("app");
  const sidebar = $("sidebar");
  const overlay = $("overlay");
  const main = $("main");
  const scrollEl = $("scroll");
  const messages = $("messages");
  const chatForm = $("chat-form");
  const chatInput = $("chat-input");
  const sendBtn = $("send-btn");
  const taskForm = $("task-form");
  const taskInput = $("task-input");
  const taskList = $("task-list");
  const taskEmpty = $("task-empty");
  const themeToggle = $("theme-toggle");

  const THEME_KEY = "studymate-theme";
  const REQUEST_TIMEOUT_MS = 60000;
  const mobileQuery = window.matchMedia("(max-width: 768px)");

  const SOURCE_LABEL = {
    notes: "From your notes",
    general: "General knowledge",
    task: "Task",
    chat: "Chat",
    error: "Error",
  };

  let busy = false;

  // Session expired (or logged out in another tab): go back to the login page.
  function redirectIfLoggedOut(res) {
    if (res.status === 401) {
      window.location.href = "/login";
      return true;
    }
    return false;
  }

  const icon = (name) =>
    `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;

  /* ── Theme ─────────────────────────────────────────────────────────── */
  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  function applyTheme(theme, persist) {
    document.documentElement.setAttribute("data-theme", theme);
    themeToggle.setAttribute(
      "aria-label",
      theme === "dark" ? "Switch to light theme" : "Switch to dark theme"
    );
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#212121" : "#ffffff");
    if (persist) {
      try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* storage blocked */ }
    }
  }

  themeToggle.addEventListener("click", () => {
    applyTheme(currentTheme() === "dark" ? "light" : "dark", true);
  });

  // Follow the OS setting until the user picks a theme themselves.
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    let saved = null;
    try { saved = localStorage.getItem(THEME_KEY); } catch (err) { /* ignore */ }
    if (!saved) applyTheme(e.matches ? "dark" : "light", false);
  });

  applyTheme(currentTheme(), false);

  /* ── Sidebar ───────────────────────────────────────────────────────── */
  function setSidebar(open) {
    app.classList.toggle("sidebar-open", open);
    overlay.hidden = !(open && mobileQuery.matches);
    sidebar.inert = !open;
  }

  $("open-sidebar").addEventListener("click", () => setSidebar(true));
  $("close-sidebar").addEventListener("click", () => setSidebar(false));
  overlay.addEventListener("click", () => setSidebar(false));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && mobileQuery.matches && app.classList.contains("sidebar-open")) {
      setSidebar(false);
    }
  });
  mobileQuery.addEventListener("change", (e) => setSidebar(!e.matches));
  setSidebar(!mobileQuery.matches);

  /* ── Helpers ───────────────────────────────────────────────────────── */
  function scrollToBottom() {
    scrollEl.scrollTop = scrollEl.scrollHeight;
  }

  function autosize() {
    chatInput.style.height = "auto";
    chatInput.style.height = Math.min(chatInput.scrollHeight, 200) + "px";
  }

  function updateSendState() {
    sendBtn.disabled = busy || chatInput.value.trim() === "";
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (e) {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); } catch (err) { /* ignore */ }
      ta.remove();
    }
  }

  function flashCopied(btn, restoreHtml) {
    btn.classList.add("copied");
    btn.innerHTML = icon("check") + (btn.dataset.label ? "<span>Copied</span>" : "");
    setTimeout(() => {
      btn.classList.remove("copied");
      btn.innerHTML = restoreHtml;
    }, 1500);
  }

  /* ── Markdown rendering (sanitized) ────────────────────────────────── */
  if (window.marked && marked.use) marked.use({ gfm: true, breaks: true });

  function renderMarkdown(target, text) {
    if (window.marked && window.DOMPurify) {
      const html = marked.parse(text || "");
      target.innerHTML = DOMPurify.sanitize(html);
      enhanceCodeBlocks(target);
    } else {
      // Libraries failed to load (offline / CDN blocked): show safe plain text.
      target.textContent = text || "";
      target.style.whiteSpace = "pre-wrap";
    }
  }

  function enhanceCodeBlocks(root) {
    root.querySelectorAll("pre").forEach((pre) => {
      const code = pre.querySelector("code");
      const langMatch = code && /language-([\w+-]+)/.exec(code.className);
      const lang = langMatch ? langMatch[1] : "code";

      const wrapper = document.createElement("div");
      wrapper.className = "code-block";

      const head = document.createElement("div");
      head.className = "code-head";
      const label = document.createElement("span");
      label.textContent = lang;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "code-copy";
      btn.dataset.label = "1";
      const idle = icon("copy") + "<span>Copy</span>";
      btn.innerHTML = idle;
      btn.addEventListener("click", async () => {
        await copyText(pre.innerText);
        flashCopied(btn, idle);
      });
      head.append(label, btn);

      pre.replaceWith(wrapper);
      wrapper.append(head, pre);
    });
  }

  /* ── Messages ──────────────────────────────────────────────────────── */
  function setEmpty(isEmpty) {
    main.classList.toggle("is-empty", isEmpty);
  }

  function addUserMessage(text) {
    setEmpty(false);
    const el = document.createElement("div");
    el.className = "msg user";
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    el.appendChild(bubble);
    messages.appendChild(el);
    scrollToBottom();
    return el;
  }

  function addBotPlaceholder() {
    const el = document.createElement("div");
    el.className = "msg bot";
    el.innerHTML = `
      <div class="avatar" aria-hidden="true">${icon("spark")}</div>
      <div class="bot-main">
        <div class="typing" role="status" aria-label="StudyMate is thinking"><i></i><i></i><i></i></div>
      </div>`;
    messages.appendChild(el);
    scrollToBottom();
    return el;
  }

  function fillBotMessage(el, text, intent) {
    const holder = el.querySelector(".bot-main");
    holder.innerHTML = "";

    const tag = document.createElement("span");
    tag.className = "source-tag" + (intent === "error" ? " error" : "");
    tag.textContent = SOURCE_LABEL[intent] || intent;
    holder.appendChild(tag);

    const body = document.createElement("div");
    body.className = "markdown-body";
    if (intent === "error") {
      body.textContent = text;
    } else {
      renderMarkdown(body, text);
    }
    holder.appendChild(body);

    if (intent !== "error") {
      const actions = document.createElement("div");
      actions.className = "bot-actions";
      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "icon-btn";
      copyBtn.setAttribute("aria-label", "Copy response");
      copyBtn.title = "Copy";
      const idle = icon("copy");
      copyBtn.innerHTML = idle;
      copyBtn.addEventListener("click", async () => {
        await copyText(text);
        flashCopied(copyBtn, idle);
      });
      actions.appendChild(copyBtn);
      holder.appendChild(actions);
    }
    scrollToBottom();
  }

  function addRetry(botEl, userEl, text) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "retry-btn";
    btn.textContent = "Try again";
    btn.addEventListener("click", () => {
      if (busy) return;
      botEl.remove();
      userEl.remove();
      sendMessage(text);
    });
    botEl.querySelector(".bot-main").appendChild(btn);
  }

  /* ── Chat ──────────────────────────────────────────────────────────── */
  function setBusy(value) {
    busy = value;
    chatInput.setAttribute("aria-busy", String(value));
    updateSendState();
  }

  async function sendMessage(text) {
    const message = text.trim();
    if (!message || busy) return;

    setBusy(true);
    const userEl = addUserMessage(message);
    const botEl = addBotPlaceholder();

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
        signal: controller.signal,
      });

      if (redirectIfLoggedOut(res)) return;

      let data = {};
      try { data = await res.json(); } catch (e) { /* non-JSON error page */ }

      if (!res.ok) {
        fillBotMessage(botEl, data.response || data.error || "The server returned an error.", "error");
        addRetry(botEl, userEl, message);
      } else {
        fillBotMessage(botEl, data.response, data.intent);
        if (data.intent === "task") loadTasks();
      }
    } catch (err) {
      const reason = err && err.name === "AbortError"
        ? "The request took too long."
        : "Couldn't reach StudyMate. Check that the server is still running.";
      fillBotMessage(botEl, reason, "error");
      addRetry(botEl, userEl, message);
    } finally {
      clearTimeout(timer);
      setBusy(false);
      if (!mobileQuery.matches) chatInput.focus();
    }
  }

  chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = chatInput.value;
    if (!text.trim() || busy) return;
    chatInput.value = "";
    autosize();
    updateSendState();
    sendMessage(text);
  });

  chatInput.addEventListener("input", () => {
    autosize();
    updateSendState();
  });

  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      chatForm.requestSubmit();
    }
  });

  $("chips").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (chip) sendMessage(chip.dataset.prompt);
  });

  $("new-chat").addEventListener("click", () => {
    if (busy) return;
    messages.innerHTML = "";
    setEmpty(true);
    chatInput.value = "";
    autosize();
    updateSendState();
    if (mobileQuery.matches) setSidebar(false);
    chatInput.focus();
  });

  /* ── Tasks ─────────────────────────────────────────────────────────── */
  function renderTasks(tasks) {
    taskList.innerHTML = "";
    taskEmpty.hidden = tasks.length > 0;

    for (const task of tasks) {
      const done = task.status === "done";
      const li = document.createElement("li");
      li.className = "task-item" + (done ? " done" : "");

      const check = document.createElement("button");
      check.type = "button";
      check.className = "task-check";
      check.innerHTML = icon("check");
      check.setAttribute("aria-label", done ? "Task completed" : "Mark task " + task.id + " as done");
      if (done) check.disabled = true;
      else check.addEventListener("click", () => completeTask(task.id));

      const body = document.createElement("span");
      body.className = "task-body";
      const id = document.createElement("span");
      id.className = "task-id";
      id.textContent = "#" + task.id;
      const topic = document.createElement("span");
      topic.className = "task-topic";
      topic.textContent = task.topic;
      body.append(id, topic);

      li.append(check, body);
      taskList.appendChild(li);
    }
  }

  async function loadTasks() {
    try {
      const res = await fetch("/api/tasks");
      if (redirectIfLoggedOut(res)) return;
      if (!res.ok) return;
      renderTasks(await res.json());
    } catch (err) {
      /* sidebar keeps its last state if the server hiccups */
    }
  }

  async function completeTask(taskId) {
    try {
      const res = await fetch(`/api/tasks/${taskId}/done`, { method: "POST" });
      if (redirectIfLoggedOut(res)) return;
    } catch (err) { /* ignore */ }
    loadTasks();
  }

  taskForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const topic = taskInput.value.trim();
    if (!topic) return;
    taskInput.value = "";
    try {
      const res = await fetch("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic }),
      });
      if (redirectIfLoggedOut(res)) return;
    } catch (err) { /* ignore */ }
    loadTasks();
  });

  /* ── Init ──────────────────────────────────────────────────────────── */
  loadTasks();
  updateSendState();
  if (!mobileQuery.matches) chatInput.focus();
})();
