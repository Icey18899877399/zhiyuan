// 智源平台 - 对话页面脚本
// 后端契约：POST /api/chat  body: {question, agent?} → {success, answer, intent, retrieved}

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

renderAgentTabs();

async function sendMessageToBackend(question) {
  const response = await fetch(API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question: question,
      agent: currentAgent.category
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
    return "";
  }
  const lines = items.map((it) => {
    const url = it.source_url || "#";
    return `<li><a href="${url}" target="_blank" rel="noopener">${it.title}</a> <span class="subtext">[${it.source}]</span></li>`;
  });
  return `<details class="rag-refs"><summary>参考来源 (${items.length})</summary><ul>${lines.join("")}</ul></details>`;
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

  try {
    const result = await sendMessageToBackend(text);
    chatBoard.removeChild(loadingMsg);

    const botMsg = document.createElement("div");
    botMsg.className = "msg bot";
    const intentLabel = result.intent || currentAgent.name;
    const refs = renderRetrieved(result.retrieved);
    botMsg.innerHTML = `<strong>[${intentLabel}]</strong><br/>${result.answer || ""}${refs}`;
    chatBoard.appendChild(botMsg);
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

document.getElementById("sendBtn").addEventListener("click", sendMessage);
chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    sendMessage();
  }
});
