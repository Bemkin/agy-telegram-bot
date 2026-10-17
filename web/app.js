/**
 * app.js — Antigravity Mission Control (Telegram Mini App Client Logic)
 */

// Initialize Telegram WebApp
const tg = window.Telegram?.WebApp;
if (tg) {
  tg.expand();
  tg.ready();
  tg.enableClosingConfirmation();
}

// Every API call proves it comes from the bot owner's Telegram client by sending
// the signed initData Telegram gave this Mini App. The server rejects anything else.
function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-Telegram-Init-Data", tg?.initData || "");
  return fetch(url, { ...options, headers });
}

// Global State (dynamically populated on boot via /api/status)
let appState = {
  project: "",
  projectDir: "",
  model: "",
  mode: "plan",
  devRunning: false,
  devPort: null,
  tunnelUrl: "",
  gitBranch: "",
  modifiedFiles: [],
};

// ── Haptic Helpers ──────────────────────────────────────────────────
function hapticImpact(style = "medium") {
  try {
    tg?.HapticFeedback?.impactOccurred(style);
  } catch (e) {}
}

function hapticNotification(type = "success") {
  try {
    tg?.HapticFeedback?.notificationOccurred(type);
  } catch (e) {}
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ── Tab Switching ───────────────────────────────────────────────────
function switchTab(tabName, btnElement) {
  hapticImpact("light");

  // Update tabs
  document.querySelectorAll(".tab-pane").forEach((el) => el.classList.remove("active"));
  const targetTab = document.getElementById(`tab-${tabName}`);
  if (targetTab) targetTab.classList.add("active");

  // Update nav buttons
  if (btnElement) {
    document.querySelectorAll(".bottom-nav .nav-item").forEach((el) => el.classList.remove("active"));
    btnElement.classList.add("active");
  }

  // Refresh tab-specific data
  if (tabName === "plans") {
    fetchActivePlan();
    fetchActiveWalkthrough();
  }
  if (tabName === "history") fetchHistory();
  if (tabName === "diffs") fetchGitDiff();
  if (tabName === "terminal") fetchDevLogs();
  if (tabName === "chat") {
    scrollChatToBottom();
    const input = document.getElementById("chatTextInput");
    if (input) input.focus();
  }
}

// ── Status Polling ──────────────────────────────────────────────────
async function fetchStatus() {
  try {
    const res = await apiFetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();

    appState = { ...appState, ...data };

    // Update UI elements
    const projShort = data.project.split(/[\\/]/).filter(Boolean).pop() || "Project";
    document.getElementById("currentProjectName").textContent = projShort;
    document.getElementById("currentModelName").textContent = data.model.replace("gemini-", "");

    // Port & Server status
    const port = data.devPort || data.tunnelPort || 8080;
    document.getElementById("previewPort").textContent = port;
    document.getElementById("termPort").textContent = port;
    document.getElementById("metricDevStatus").textContent = data.devRunning ? "🟢 Running" : "⚪ Stopped";
    document.getElementById("metricGitBranch").textContent = `${data.gitBranch} (${data.gitModifiedCount || 0} modified)`;

    // Tunnel Button
    const tunnelBtnText = document.getElementById("tunnelStatusText");
    if (tunnelBtnText) {
      tunnelBtnText.textContent = data.tunnelUrl ? "🔴 Stop Tunnel" : "🌐 Start Tunnel";
    }
  } catch (e) {
    console.error("Status fetch error:", e);
  }
}

// ── 💬 In-App AI Chat Engine ─────────────────────────────────────────

function scrollChatToBottom() {
  const vp = document.getElementById("chatViewport");
  if (vp) vp.scrollTop = vp.scrollHeight;
}

function handleChatKeyDown(event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submitChatMessage();
  }
}

function insertPrompt(text) {
  hapticImpact("light");
  const input = document.getElementById("chatTextInput");
  if (input) {
    input.value = text;
    input.focus();
  }
}

async function submitChatMessage() {
  const input = document.getElementById("chatTextInput");
  const text = input.value.trim();
  if (!text) return;

  hapticImpact("medium");
  input.value = "";
  input.style.height = "auto";

  // Append user bubble
  appendChatBubble("user", text);
  scrollChatToBottom();

  // Show thinking bubble
  const thinkingId = appendThinkingBubble();
  scrollChatToBottom();

  try {
    const res = await apiFetch("/api/chat/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });

    removeBubble(thinkingId);

    if (!res.ok) {
      let errMsg = `Server returned status ${res.status}`;
      try {
        const err = await res.json();
        errMsg = err.detail || errMsg;
      } catch (e) {
        const rawText = await res.text().catch(() => "");
        if (rawText.includes("Error 1016") || rawText.includes("Origin DNS")) {
          errMsg = "Tunnel reconnecting. Please wait 5s and try again.";
        }
      }
      appendChatBubble("ai", `❌ ${errMsg}`);
      scrollChatToBottom();
      return;
    }

    let data;
    try {
      data = await res.json();
    } catch (parseErr) {
      appendChatBubble("ai", `⚠️ Received unexpected response format. Please refresh the page.`);
      scrollChatToBottom();
      return;
    }

    hapticNotification("success");
    appendChatBubble("ai", data.reply);
    scrollChatToBottom();

    // If it was a /plan command, switch to plans tab
    if (text.startsWith("/plan") || data.isPlan) {
      setTimeout(() => {
        switchTab("plans");
        switchPlanSubView("active");
      }, 1500);
    }
  } catch (e) {
    removeBubble(thinkingId);
    appendChatBubble("ai", `❌ Connection error: Backend server unavailable. Please reopen the Mini App.`);
    scrollChatToBottom();
  }
}

function appendChatBubble(role, content) {
  const list = document.getElementById("chatMessagesList");
  if (!list) return;

  const msgDiv = document.createElement("div");
  msgDiv.className = `chat-msg ${role === "user" ? "msg-user" : "msg-ai"}`;

  const avatar = role === "user" ? "👤" : "🤖";
  const author = role === "user" ? "You" : "Antigravity AI";
  const formattedHtml = role === "user" ? escapeHtml(content) : formatMarkdown(content);

  msgDiv.innerHTML = `
    <div class="msg-avatar">${avatar}</div>
    <div class="msg-bubble">
      <div class="msg-author">${author}</div>
      <div class="msg-content">${formattedHtml}</div>
    </div>
  `;

  list.appendChild(msgDiv);
}

function appendThinkingBubble() {
  const list = document.getElementById("chatMessagesList");
  const id = `thinking-${Date.now()}`;
  const msgDiv = document.createElement("div");
  msgDiv.id = id;
  msgDiv.className = "chat-msg msg-ai";
  msgDiv.innerHTML = `
    <div class="msg-avatar">🤖</div>
    <div class="msg-bubble">
      <div class="msg-author">Antigravity AI</div>
      <div class="msg-content thinking-dots">
        <span>Thinking</span> <span>•</span> <span>•</span> <span>•</span>
      </div>
    </div>
  `;
  list.appendChild(msgDiv);
  return id;
}

function removeBubble(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function formatMarkdown(text) {
  if (!text) return "";
  let out = escapeHtml(text);

  // Code blocks: ```code```
  out = out.replace(/```([\s\S]*?)```/g, "<pre><code>$1</code></pre>");

  // Inline code: `code`
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");

  // Bold: **text**
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

  // Italic: *text*
  out = out.replace(/\*([^*]+)\*/g, "<em>$1</em>");

  // Line breaks
  out = out.replace(/\n/g, "<br>");

  return out;
}

// ── 🧠 Plans & Completed Walkthroughs ────────────────────────────────

function switchPlanSubView(viewName, btnElement) {
  hapticImpact("light");
  document.querySelectorAll(".plan-subnav .subnav-pill").forEach((el) => el.classList.remove("active"));
  if (btnElement) btnElement.classList.add("active");
  else {
    const targetBtn = document.getElementById(viewName === "active" ? "subnavActiveBtn" : "subnavWalkthroughBtn");
    if (targetBtn) targetBtn.classList.add("active");
  }

  const activeView = document.getElementById("planSubViewActive");
  const walkthroughView = document.getElementById("planSubViewWalkthrough");

  if (viewName === "active") {
    if (activeView) activeView.style.display = "block";
    if (walkthroughView) walkthroughView.style.display = "none";
    fetchActivePlan();
  } else {
    if (activeView) activeView.style.display = "none";
    if (walkthroughView) walkthroughView.style.display = "block";
    fetchActiveWalkthrough();
  }
}

async function fetchActivePlan() {
  const container = document.getElementById("planTasksList");
  try {
    const res = await apiFetch("/api/plan/active");
    if (!res.ok) {
      container.innerHTML = `<div class="plan-empty-state">No active plan found.<br>Send <code>/plan &lt;feature&gt;</code> in chat to start!</div>`;
      return;
    }
    const data = await res.json();

    if (data.title) {
      document.getElementById("activePlanTitle").textContent = data.title;
    }

    if (data.tasks && data.tasks.length > 0) {
      const completed = data.tasks.filter((t) => t.done).length;
      const pct = Math.round((completed / data.tasks.length) * 100);

      document.getElementById("planProgressBar").style.width = `${pct}%`;
      document.getElementById("planProgressText").textContent = `Step ${completed} of ${data.tasks.length} Complete (${pct}%)`;

      container.innerHTML = data.tasks
        .map(
          (t, idx) => `
        <div class="task-item">
          <input type="checkbox" class="task-checkbox" ${t.done ? "checked" : ""} onchange="toggleTask(${idx})">
          <div class="task-details">
            <div class="task-text">${t.text}</div>
            ${t.file ? `<span class="task-file-badge">${t.file}</span>` : ""}
          </div>
        </div>
      `
        )
        .join("");
    } else if (data.rawContent) {
      container.innerHTML = `<div class="diff-content"><pre>${escapeHtml(data.rawContent)}</pre></div>`;
    }
  } catch (e) {
    container.innerHTML = `<div class="plan-empty-state">Ready for your next feature idea.</div>`;
  }
}

async function fetchActiveWalkthrough() {
  const filesList = document.getElementById("walkthroughFilesList");
  const reportText = document.getElementById("walkthroughReportText");

  try {
    const res = await apiFetch("/api/plan/walkthrough");
    if (!res.ok) {
      if (filesList) filesList.innerHTML = `<div style="font-size:11px; color:#64748B;">No completed walkthrough on record yet.</div>`;
      if (reportText) reportText.textContent = "Execute a plan to see the verified task completion report here.";
      return;
    }

    const data = await res.json();
    if (data.title) {
      document.getElementById("walkthroughTitle").textContent = data.title;
    }

    if (filesList) {
      if (data.files && data.files.length > 0) {
        filesList.innerHTML = data.files.map((f) => `<span class="timeline-file-pill">✅ ${escapeHtml(f)}</span>`).join("");
      } else {
        filesList.innerHTML = `<span class="timeline-file-pill">✅ Verification Passed</span>`;
      }
    }

    if (reportText) {
      reportText.textContent = data.rawContent || "Execution complete.";
    }
  } catch (e) {
    if (reportText) reportText.textContent = "Error loading walkthrough: " + e.message;
  }
}

async function approveAndExecutePlan() {
  hapticImpact("heavy");
  const btn = document.getElementById("approvePlanBtn");
  btn.textContent = "⏳ Executing Changes on Laptop...";
  btn.disabled = true;

  try {
    const res = await apiFetch("/api/plan/approve", { method: "POST" });
    const data = await res.json();
    hapticNotification("success");
    btn.textContent = "✅ Plan Executed Successfully!";
    
    setTimeout(() => {
      btn.textContent = "⚡ Approve & Execute Plan";
      btn.disabled = false;
      // Switch automatically to the Completed Walkthrough view!
      switchPlanSubView("walkthrough");
    }, 1500);
  } catch (e) {
    alert("Error executing plan: " + e);
    btn.textContent = "⚡ Approve & Execute Plan";
    btn.disabled = false;
  }
}

function triggerNewPlan() {
  hapticImpact("medium");
  switchTab("chat");
  insertPrompt("/plan ");
}

// ── 📜 Mobile Change History Timeline ────────────────────────────────
async function fetchHistory() {
  const container = document.getElementById("historyTimelineList");
  if (!container) return;

  try {
    const res = await apiFetch("/api/history");
    if (!res.ok) {
      container.innerHTML = `<div class="plan-empty-state">No audit logs recorded yet.</div>`;
      return;
    }

    const data = await res.json();
    const records = data.history || [];

    if (records.length === 0) {
      container.innerHTML = `<div class="plan-empty-state">No mobile actions logged yet.<br>Prompts and file edits will appear here!</div>`;
      return;
    }

    container.innerHTML = records
      .map((r, idx) => {
        const filesHtml =
          r.files && r.files.length > 0
            ? `<div class="timeline-files-list">
                ${r.files.map((f) => `<span class="timeline-file-pill">📄 ${escapeHtml(f)}</span>`).join("")}
               </div>`
            : `<div style="font-size:11px; color:#64748B;">No file changes recorded.</div>`;

        return `
        <div class="timeline-item" id="item-${r.id}">
          <div class="timeline-meta-bar">
            <span class="timeline-time">🕒 ${r.time_short || "Just now"} • ${r.timestamp ? r.timestamp.split(" ")[0] : ""}</span>
            <span class="timeline-model-tag">${(r.model || "flash").replace("gemini-", "")}</span>
          </div>

          <div class="timeline-prompt-box">
            💬 "${escapeHtml(r.prompt)}"
          </div>

          <div style="margin-top: 4px;">
            <span style="font-size:10px; text-transform:uppercase; font-weight:700; color:#94A3B8; margin-bottom:4px; display:block;">Files Touched:</span>
            ${filesHtml}
          </div>

          <div class="timeline-output-summary" id="summary-${r.id}">
            ${escapeHtml(r.summary)}
          </div>

          <div class="timeline-actions">
            <button class="micro-btn" onclick="toggleFullHistory('${r.id}', ${idx})">Details ▾</button>
            <button class="micro-btn" onclick="switchTab('diffs')">View Diff ↗</button>
          </div>

          <div id="full-details-${r.id}" style="display:none; margin-top:8px; background:#06080D; padding:10px; border-radius:8px; font-size:11px; font-family:var(--font-mono); overflow-x:auto;">
            <pre>${escapeHtml(r.full_response || "")}</pre>
          </div>
        </div>
      `;
      })
      .join("");
  } catch (e) {
    container.innerHTML = `<div class="plan-empty-state">Error loading history: ${e.message}</div>`;
  }
}

function toggleFullHistory(id, index) {
  hapticImpact("light");
  const el = document.getElementById(`full-details-${id}`);
  if (el) {
    el.style.display = el.style.display === "none" ? "block" : "none";
  }
}

// ── Live App Preview & Tunnel ───────────────────────────────────────
function refreshPreview() {
  hapticImpact("medium");
  loadPreviewImage();
}

// <img src> cannot send headers, so fetch the screenshot with auth and show it as a blob.
let previewObjectUrl = null;
async function loadPreviewImage() {
  const img = document.getElementById("previewImg");
  if (!img) return;
  try {
    const res = await apiFetch(`/api/preview/image?t=${Date.now()}`);
    if (!res.ok) throw new Error(`preview ${res.status}`);
    const blob = await res.blob();
    if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
    previewObjectUrl = URL.createObjectURL(blob);
    img.src = previewObjectUrl;
  } catch (err) {
    handlePreviewError();
  }
}

function handlePreviewError() {
  const img = document.getElementById("previewImg");
  if (img) {
    img.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='400' height='200' viewBox='0 0 400 200'><rect width='100%' height='100%' fill='%230B0D13'/><text x='50%' y='50%' dominant-baseline='middle' text-anchor='middle' fill='%2394A3B8' font-family='sans-serif' font-size='14'>Preview capturing on localhost...</text></svg>";
  }
}

function openLiveTunnel() {
  hapticImpact("heavy");
  if (appState.tunnelUrl) {
    if (tg?.openLink) {
      tg.openLink(appState.tunnelUrl);
    } else {
      window.open(appState.tunnelUrl, "_blank");
    }
  } else {
    toggleTunnel();
  }
}

async function toggleTunnel() {
  hapticImpact("medium");
  try {
    const res = await apiFetch("/api/tunnel/toggle", { method: "POST" });
    const data = await res.json();
    if (data.url) {
      appState.tunnelUrl = data.url;
      hapticNotification("success");
      if (tg?.openLink) tg.openLink(data.url);
      else window.open(data.url, "_blank");
    }
    fetchStatus();
  } catch (e) {
    alert("Error toggling tunnel: " + e);
  }
}

async function restartDevServer() {
  hapticImpact("medium");
  try {
    const res = await apiFetch("/api/dev/restart", { method: "POST" });
    const data = await res.json();
    hapticNotification("success");
    fetchStatus();
  } catch (e) {
    alert("Error restarting server: " + e);
  }
}

// ── Git & Diffs Tab ─────────────────────────────────────────────────
async function fetchGitDiff() {
  const codeEl = document.getElementById("diffCodeText");
  try {
    const res = await apiFetch("/api/git/diff");
    const data = await res.json();

    if (!data.diff || data.diff.trim() === "") {
      codeEl.innerHTML = '<span style="color:#10B981;">Working tree clean. No uncommitted changes.</span>';
      return;
    }

    // Format diff lines
    const lines = data.diff.split("\n");
    const formatted = lines
      .map((line) => {
        if (line.startsWith("+") && !line.startsWith("+++")) {
          return `<span class="diff-add">${escapeHtml(line)}</span>`;
        } else if (line.startsWith("-") && !line.startsWith("---")) {
          return `<span class="diff-del">${escapeHtml(line)}</span>`;
        }
        return escapeHtml(line);
      })
      .join("\n");

    codeEl.innerHTML = formatted;
  } catch (e) {
    codeEl.textContent = "Error loading git diff: " + e;
  }
}

async function executeGitCommitPush() {
  const input = document.getElementById("commitMsgInput");
  const msg = input.value.trim() || "update from mobile mission control";
  hapticImpact("heavy");

  try {
    const res = await apiFetch("/api/git/push", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg }),
    });
    const data = await res.json();
    hapticNotification("success");
    alert("✅ Pushed to remote successfully!");
    input.value = "";
    fetchGitDiff();
  } catch (e) {
    alert("Git push error: " + e);
  }
}

// ── Terminal Logs Tab ───────────────────────────────────────────────
let fullLogCache = "";

async function fetchDevLogs() {
  const termEl = document.getElementById("terminalLogText");
  try {
    const res = await apiFetch("/api/dev/logs");
    const data = await res.json();
    fullLogCache = data.logs || "No logs recorded.";
    renderLogs(fullLogCache);
  } catch (e) {
    termEl.textContent = "Error loading logs: " + e;
  }
}

function renderLogs(logString) {
  const termEl = document.getElementById("terminalLogText");
  termEl.textContent = logString;
  const body = document.getElementById("terminalBody");
  if (body) body.scrollTop = body.scrollHeight;
}

function filterLogs(filterType, btnEl) {
  hapticImpact("light");
  document.querySelectorAll(".terminal-filter-bar .filter-chip").forEach((el) => el.classList.remove("active"));
  if (btnEl) btnEl.classList.add("active");

  if (filterType === "all") {
    renderLogs(fullLogCache);
  } else if (filterType === "vite") {
    const filtered = fullLogCache
      .split("\n")
      .filter((l) => l.toLowerCase().includes("vite") || l.toLowerCase().includes("hmr"))
      .join("\n");
    renderLogs(filtered || "No Vite HMR lines found.");
  } else if (filterType === "error") {
    const filtered = fullLogCache
      .split("\n")
      .filter((l) => l.toLowerCase().includes("error") || l.toLowerCase().includes("fail") || l.toLowerCase().includes("warn"))
      .join("\n");
    renderLogs(filtered || "No error lines found in recent logs.");
  }
}

// ── Project Modal ───────────────────────────────────────────────────
async function toggleProjectModal(show = true) {
  hapticImpact("medium");
  const modal = document.getElementById("projectModal");
  if (!modal) return;

  if (show) {
    modal.classList.add("open");
    const listEl = document.getElementById("modalProjectList");
    listEl.innerHTML = "Loading projects...";

    try {
      const res = await apiFetch("/api/projects");
      const data = await res.json();
      listEl.innerHTML = data.projects
        .map(
          (p) => `
        <div class="project-item ${p.active ? "active-project" : ""}" onclick="selectProject('${p.name}')">
          <div>
            <strong>${p.name}</strong>
            <div style="font-size:10px; color:#64748B;">${p.path}</div>
          </div>
          ${p.active ? "<span>⭐</span>" : ""}
        </div>
      `
        )
        .join("");
    } catch (e) {
      listEl.innerHTML = "Error loading projects: " + e;
    }
  } else {
    modal.classList.remove("open");
  }
}

async function selectProject(projectName) {
  hapticImpact("heavy");
  try {
    await apiFetch("/api/projects/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: projectName }),
    });
    toggleProjectModal(false);
    hapticNotification("success");
    fetchStatus();
    refreshPreview();
  } catch (e) {
    alert("Error switching project: " + e);
  }
}

let selectedProjectTemplate = "html";

function toggleNewProjectForm(forceState) {
  hapticImpact("light");
  const card = document.getElementById("newProjectCard");
  if (!card) return;
  const isHidden = card.style.display === "none";
  card.style.display = forceState !== undefined ? (forceState ? "block" : "none") : (isHidden ? "block" : "none");
  if (card.style.display === "block") {
    const input = document.getElementById("newProjectNameInput");
    if (input) {
      input.value = "";
      input.focus();
    }
  }
}

function selectTemplate(templateName, btn) {
  hapticImpact("light");
  selectedProjectTemplate = templateName;
  document.querySelectorAll("#newProjectCard .chip").forEach((el) => el.classList.remove("active-template"));
  if (btn) btn.classList.add("active-template");
}

async function submitCreateNewProject() {
  const input = document.getElementById("newProjectNameInput");
  const name = input ? input.value.trim() : "";
  if (!name) {
    alert("Please enter a project name.");
    return;
  }

  hapticImpact("heavy");
  try {
    const res = await apiFetch("/api/projects/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name, template: selectedProjectTemplate }),
    });

    if (!res.ok) {
      const err = await res.json();
      alert("Error creating project: " + (err.detail || "Failed"));
      return;
    }

    const data = await res.json();
    hapticNotification("success");
    toggleNewProjectForm(false);
    toggleProjectModal(false);
    
    // Refresh status and switch to chat
    fetchStatus();
    switchTab("chat");
    appendChatBubble("ai", `🎉 **Workspace Created:** Switched to new project \`${data.name}\` at \`${data.path}\`.\n\nWhat would you like to build first?`);
  } catch (e) {
    alert("Error: " + e.message);
  }
}

// ── Initial Boot ────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  fetchStatus();
  loadPreviewImage();
  setInterval(fetchStatus, 3500); // 3.5s background polling
});
