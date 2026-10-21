// 智源平台 - 对话页面脚本
// 后端契约：POST /api/chat {question, route_mode, agent?} → answer, intents, experts, confidence, warnings, retrieved

const agents = [
  { key: "study", name: "📖学业agent", guide: "你想了解哪些课程安排或学业政策？", category: "学业" },
  { key: "activity", name: "🪁活动agent", guide: "你想了解什么方面的校园活动？", category: "活动" },
  { key: "party", name: "🀄党团agent", guide: "你想了解党团事务的哪些内容？", category: "党团" },
  { key: "career", name: "🎓就业agent", guide: "你想了解实习、就业还是招聘信息？", category: "就业" },
  { key: "admin", name: "💼行政agent", guide: "你想办理哪项行政事务？", category: "其他" }
];

const agentTabs = document.getElementById("agentTabs");
const chatInput = document.getElementById("chatInput");
const chatBoard = document.getElementById("chatBoard");
const routeLine = document.getElementById("routeLine");
let currentAgent = agents[0];
let routeMode = "manual";

// 相对路径：FastAPI 单端口托管前端静态文件 + API，无需 BACKEND_URL
const API_URL = "/api/chat";

function renderAgentTabs() {
  agentTabs.innerHTML = "";
  agents.forEach((agent) => {
    const btn = document.createElement("button");
    btn.textContent = agent.name;
    if (agent.key === currentAgent.key) {
      btn.classList.add("active");
    }
    btn.addEventListener("click", () => {
      currentAgent = agent;
      chatInput.placeholder = agent.guide;
      renderAgentTabs();
      const tip = document.createElement("div");
      tip.className = "msg bot";
      tip.textContent = `已切换到${agent.name}，${agent.guide}`;
      chatBoard.appendChild(tip);
      chatBoard.scrollTop = chatBoard.scrollHeight;
    });
    agentTabs.appendChild(btn);
  });
}

function syncAutoRoutedAgent(result) {
  const category = Array.isArray(result.intents) ? result.intents[0] : null;
  const routedAgent = agents.find((agent) => agent.category === category);
  if (!routedAgent || routedAgent.key === currentAgent.key) {
    return;
  }

  currentAgent = routedAgent;
  renderAgentTabs();
}

renderAgentTabs();

async function loadHealthStatus() {
  try {
    const response = await fetch("/api/health");
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const health = await response.json();
    if (health.dependencies && health.dependencies.database === "ok") {
      routeLine.textContent = "服务状态：知识库在线，可进行完整检索问答";
      return;
    }
    routeLine.textContent = "服务状态：知识库暂不可用，当前可用降级问答";
  } catch (error) {
    routeLine.textContent = "服务状态：后端暂不可达，请稍后重试";
  }
}

loadHealthStatus();

async function sendMessageToBackend(question, mode, agent) {
  const response = await fetch(API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question: question,
      agent: mode === "manual" ? agent.category : null,
      route_mode: mode
    })
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`HTTP ${response.status}: ${text || response.statusText}`);
  }
  return await response.json();
}

function renderRetrieved(items) {
  if (!items || items.length === 0) {
    return null;
  }

  const details = document.createElement("details");
  details.className = "rag-refs";
  const summary = document.createElement("summary");
  summary.textContent = `参考来源 (${items.length})`;
  details.appendChild(summary);

  const list = document.createElement("ul");
  items.forEach((item) => {
    const listItem = document.createElement("li");
    if (Array.isArray(item.citations) && item.citations.length > 0) {
      const citations = document.createElement("strong");
      citations.textContent = `${item.citations.join(" ")} `;
      listItem.appendChild(citations);
    }
    const titleText = item.title || "未命名来源";
    const title = document.createElement("a");
    title.textContent = titleText;
    title.target = "_blank";
    title.rel = "noopener noreferrer";

    try {
      const url = new URL(item.source_url, window.location.origin);
      if (url.protocol === "http:" || url.protocol === "https:") {
        title.href = url.href;
      }
    } catch {
      // Invalid source URLs remain plain text.
    }

    if (title.hasAttribute("href")) {
      listItem.appendChild(title);
    } else {
      listItem.appendChild(document.createTextNode(titleText));
    }
    const source = document.createElement("span");
    source.className = "subtext";
    source.textContent = item.source ? ` [${item.source}]` : "";
    listItem.appendChild(source);
    list.appendChild(listItem);
  });
  details.appendChild(list);
  return details;
}

function renderAnswer(result, intentLabel) {
  const message = document.createElement("div");
  message.className = "msg bot";

  const heading = document.createElement("strong");
  heading.textContent = `[${intentLabel}]`;
  message.appendChild(heading);

  const metadata = document.createElement("span");
  metadata.className = "subtext";
  const expertLabel = result.experts && result.experts.length
    ? ` · 专家：${result.experts.join("、")}`
    : "";
  const routeSourceLabels = {
    manual: "手动选择",
    rules: "关键词规则",
    llm: "大模型识别"
  };
  const routeSourceLabel = routeSourceLabels[result.route_source] || "未知";
  const answerModeLabels = {
    llm: "大模型专家回答",
    retrieval_fallback: "本地检索降级",
    no_context: "无可靠资料，未调用模型"
  };
  const answerMode = answerModeLabels[result.answer_mode] || "未知回答方式";
  metadata.textContent = `${expertLabel} · 路由：${routeSourceLabel} · 置信度 ${(Number(result.confidence || 0) * 100).toFixed(0)}% · ${answerMode}`;
  message.appendChild(metadata);

  (result.warnings || []).forEach((warningText) => {
    const warning = document.createElement("div");
    warning.className = "answer-warning";
    warning.textContent = warningText;
    message.appendChild(warning);
  });

  const answer = document.createElement("div");
  answer.className = "answer-text";
  answer.textContent = result.answer || "";
  message.appendChild(answer);

  const references = renderRetrieved(result.retrieved);
  if (references) {
    message.appendChild(references);
  }
  return message;
}

async function sendMessage() {
  const text = chatInput.value.trim();
  if (!text) {
    return;
  }

  const userMsg = document.createElement("div");
  userMsg.className = "msg user";
  userMsg.textContent = text;
  chatBoard.appendChild(userMsg);

  chatInput.value = "";
  chatBoard.scrollTop = chatBoard.scrollHeight;

  const loadingMsg = document.createElement("div");
  loadingMsg.className = "msg bot";
  loadingMsg.textContent = "正在思考中...";
  chatBoard.appendChild(loadingMsg);
  chatBoard.scrollTop = chatBoard.scrollHeight;

  const requestMode = routeMode;
  const requestAgent = currentAgent;

  try {
    const result = await sendMessageToBackend(text, requestMode, requestAgent);
    chatBoard.removeChild(loadingMsg);

    if (requestMode === "auto" && routeMode === "auto") {
      syncAutoRoutedAgent(result);
    }

    const intentLabel = result.intent || currentAgent.name;
    chatBoard.appendChild(renderAnswer(result, intentLabel));
    routeLine.textContent = `路由：${requestMode === "auto" ? "自动识别" : "手动选择"} · ${intentLabel}`;
    chatBoard.scrollTop = chatBoard.scrollHeight;
  } catch (error) {
    chatBoard.removeChild(loadingMsg);
    const errorMsg = document.createElement("div");
    errorMsg.className = "msg bot";
    errorMsg.textContent = `服务暂时不可用：${error.message}`;
    chatBoard.appendChild(errorMsg);
    chatBoard.scrollTop = chatBoard.scrollHeight;
  }
}

const routeModeToggle = document.getElementById("routeModeToggle");
function updateRouteModeToggle() {
  routeModeToggle.querySelectorAll("[data-route-mode]").forEach((button) => {
    const isActive = button.dataset.routeMode === routeMode;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });
}

updateRouteModeToggle();
routeModeToggle.addEventListener("click", (event) => {
  const button = event.target.closest("[data-route-mode]");
  if (!button || button.dataset.routeMode === routeMode) {
    return;
  }

  routeMode = button.dataset.routeMode;
  updateRouteModeToggle();
  chatInput.placeholder = routeMode === "auto"
    ? "直接输入问题，系统自动分配专家"
    : currentAgent.guide;
  routeLine.textContent = routeMode === "auto"
    ? "自动路由已开启，将按问题识别一个或多个专家"
    : "手动路由已开启，使用当前 Agent 标签";
});

document.getElementById("sendBtn").addEventListener("click", sendMessage);
chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    sendMessage();
  }
});
