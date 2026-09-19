// 我的订阅页
// 流程：建档 → 读配置 → 选话题/填关键词 → 保存（后端回填历史）→ 浏览订阅流 → 标记已读
//
// 文章标题和正文来自爬取的外部网页，渲染前一律走 esc()，不要直接拼进 innerHTML。

const summaryBox = document.getElementById("subSummary");
const topicChips = document.getElementById("topicChips");
const keywordChips = document.getElementById("keywordChips");
const keywordInput = document.getElementById("keywordInput");
const saveInfo = document.getElementById("saveInfo");
const feedList = document.getElementById("feedList");
const pageInfo = document.getElementById("pageInfo");
const identityBox = document.getElementById("identityBox");
const unreadOnlyBox = document.getElementById("unreadOnly");

const SOURCE_LABEL = {
  cuc_jwc_notice: "教务处通知",
  cuc_cs_notice: "计网学院通知",
  cuc_career: "就业网通知",
  wechat_mp: "学院公众号",
};

let userId = null;
let allTopics = [];
let selectedTopics = [];
let keywords = [];
let page = 1;
let total = 0;
let unreadTotal = 0;
let enabled = true; // 提醒开关；暂停后仍保留已有的订阅流

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function fmtTime(isoStr) {
  if (!isoStr) return "—";
  const d = new Date(isoStr);
  if (isNaN(d.getTime())) return isoStr;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function labelSource(src) {
  return SOURCE_LABEL[src] || src;
}

// ─────────────── 渲染 ───────────────

function renderSummary() {
  const hasSub = selectedTopics.length || keywords.length;
  summaryBox.innerHTML = `
    <div class="kv"><span>未读通知</span><strong>${unreadTotal}</strong></div>
    <div class="kv"><span>匹配到的通知</span><strong>${total}</strong></div>
    <div class="kv"><span>关注话题</span><strong>${selectedTopics.length}</strong></div>
    <div class="kv"><span>补充关键词</span><strong>${keywords.length}</strong></div>
    <div class="kv"><span>提醒状态</span><strong>${
      !hasSub ? "未设置" : enabled ? "已开启" : "已暂停"
    }</strong></div>
  `;
}

function renderEnabledState() {
  const btn = document.getElementById("toggleEnabled");
  const hint = document.getElementById("enabledHint");
  const hasSub = selectedTopics.length || keywords.length;

  btn.textContent = enabled ? "暂停提醒" : "恢复提醒";
  btn.classList.toggle("paused", !enabled);
  // 没有订阅内容时暂停没有意义，禁用掉避免误操作
  btn.disabled = !hasSub;

  hint.textContent = !hasSub
    ? ""
    : enabled
      ? "有新通知匹配到你的关注方向时，会在各页面侧边栏显示未读提示。"
      : "提醒已暂停：不再匹配新通知，也不再回填。已有的订阅流和未读记录会保留。";
}

function renderTopicChips() {
  topicChips.innerHTML = allTopics
    .map((t) => {
      const on = selectedTopics.includes(t.topic);
      return `<button type="button" class="chip${on ? " active" : ""}"
        data-topic="${esc(t.topic)}" aria-pressed="${on}">
        ${esc(t.topic)} <span class="subtext">${t.count}</span>
      </button>`;
    })
    .join("");
}

function renderKeywordChips() {
  keywordChips.innerHTML = keywords
    .map(
      (k) => `<span class="chip static">${esc(k)}
        <span class="chip-x" data-kw="${esc(k)}" title="移除">×</span></span>`
    )
    .join("");
}

function renderFeed(items) {
  if (!items.length) {
    feedList.innerHTML = `<div class="empty-hint">${
      selectedTopics.length || keywords.length
        ? "还没有匹配到通知。等爬虫抓到新的相关内容，或换个更常见的关键词试试。"
        : "还没有设置订阅，先在上面选几个关注话题吧。"
    }</div>`;
    return;
  }

  feedList.innerHTML = items
    .map((it) => {
      const hits = (it.hit_keywords || [])
        .map((k) => `<span class="badge hit">命中：${esc(k)}</span>`)
        .join(" ");
      return `<div class="feed-item${it.is_read ? "" : " unread"}">
        <div class="feed-title">
          <a href="${esc(it.source_url)}" target="_blank" rel="noopener noreferrer">${esc(it.title)}</a>
        </div>
        <div class="feed-meta">
          <span>${esc(it.category)}</span>
          <span>${esc(labelSource(it.source))}</span>
          <span>${fmtTime(it.publish_time || it.crawled_at)}</span>
          ${it.is_read ? "" : `<span class="badge">未读</span>`}
          ${hits}
        </div>
        <div class="feed-snippet">${esc(it.snippet)}</div>
        <div class="feed-actions">
          ${
            it.is_read
              ? ""
              : `<button type="button" data-read="${it.article_id}">标记已读</button>`
          }
          <a href="${esc(it.source_url)}" target="_blank" rel="noopener noreferrer">
            <button type="button">查看原文</button>
          </a>
        </div>
      </div>`;
    })
    .join("");
}

function renderIdentity() {
  const device = getDeviceId();
  const short = device.length > 12 ? device.slice(0, 8) + "…" + device.slice(-4) : device;
  identityBox.innerHTML = `
    <div class="log-row">本机身份码：<strong>${esc(short)}</strong>
      <span class="subtext">（订阅存在本机标识下，换设备/清缓存会丢失）</span></div>
    <div class="log-row">
      <button class="save" id="copyDeviceId">复制完整身份码</button>
      <span class="subtext" id="copyInfo"></span>
    </div>`;
  document.getElementById("copyDeviceId").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(device);
      document.getElementById("copyInfo").textContent = "已复制";
    } catch (_) {
      document.getElementById("copyInfo").textContent = device;
    }
  });
}

// ─────────────── 数据 ───────────────

async function loadTopics() {
  allTopics = await apiFetch("/api/subscriptions/topics");
  renderTopicChips();
}

async function loadConfig() {
  const data = await apiFetch(`/api/subscriptions/${userId}`);
  selectedTopics = data.config ? data.config.topics : [];
  keywords = data.config ? data.config.keywords : [];
  enabled = data.config ? data.config.enabled : true;
  unreadTotal = data.unread_total || 0;
  renderTopicChips();
  renderKeywordChips();
  renderSummary();
  renderEnabledState();
}

async function loadFeed() {
  const qs = new URLSearchParams({
    page: String(page),
    unread_only: String(unreadOnlyBox.checked),
  });
  const data = await apiFetch(`/api/subscriptions/${userId}/feed?${qs}`);
  total = data.total;
  unreadTotal = data.unread_total;
  renderFeed(data.items);
  renderSummary();
  const maxPage = Math.max(1, Math.ceil(data.total / data.page_size));
  pageInfo.textContent = `第 ${data.page} / ${maxPage} 页 · 共 ${data.total} 条`;
  document.getElementById("prevPage").disabled = data.page <= 1;
  document.getElementById("nextPage").disabled = data.page >= maxPage;
}

async function save() {
  saveInfo.textContent = "保存中…";
  try {
    const data = await apiFetch(`/api/subscriptions/${userId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      // 带上 enabled，避免「暂停后改关键词再保存」把提醒偷偷打开
      body: JSON.stringify({ topics: selectedTopics, keywords, enabled }),
    });
    selectedTopics = data.config.topics;
    keywords = data.config.keywords;
    enabled = data.config.enabled;
    unreadTotal = data.unread_total;
    // 不说死「近 30 天」：窗口由后端 SUBSCRIPTION_BACKFILL_DAYS 决定
    saveInfo.textContent = enabled
      ? `已保存，回填历史匹配 ${data.backfilled} 条`
      : "已保存。提醒处于暂停状态，不回填新内容。";
    keywordInput.value = "";
    renderTopicChips();
    renderKeywordChips();
    renderEnabledState();
    page = 1;
    await loadFeed();
  } catch (e) {
    saveInfo.textContent = `保存失败：${e.message}`;
  }
}

function addKeywordFromInput() {
  // 逗号（中英文）、顿号、分号、空白都当分隔符
  const parts = keywordInput.value.split(/[,，、;；\s]+/).filter(Boolean);
  if (!parts.length) return;
  for (const p of parts) {
    const kw = p.trim();
    // 长度和泛词的最终判定在后端，这里只挡明显无效的，避免用户困惑
    if (kw.length >= 2 && !keywords.some((k) => k.toLowerCase() === kw.toLowerCase())) {
      keywords.push(kw);
    }
  }
  keywordInput.value = "";
  renderKeywordChips();
  renderSummary();
  renderEnabledState();
}

async function markRead(articleIds, all) {
  await apiFetch(`/api/subscriptions/${userId}/read`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(all ? { all: true } : { article_ids: articleIds }),
  });
  await loadFeed();
}

// ─────────────── 事件绑定 ───────────────

topicChips.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-topic]");
  if (!btn) return;
  const t = btn.dataset.topic;
  const i = selectedTopics.indexOf(t);
  if (i >= 0) selectedTopics.splice(i, 1);
  else selectedTopics.push(t);
  renderTopicChips();
  renderSummary();
  renderEnabledState();
});

keywordChips.addEventListener("click", (e) => {
  const x = e.target.closest("[data-kw]");
  if (!x) return;
  keywords = keywords.filter((k) => k !== x.dataset.kw);
  renderKeywordChips();
  renderSummary();
  renderEnabledState();
});

keywordInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === "," || e.key === "，") {
    e.preventDefault();
    addKeywordFromInput();
  }
});
// 失焦也收一次，避免用户填完直接点保存结果没带上
keywordInput.addEventListener("blur", addKeywordFromInput);

feedList.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-read]");
  if (!btn) return;
  markRead([Number(btn.dataset.read)], false).catch((err) => {
    feedList.insertAdjacentHTML("afterbegin", `<div class="empty-hint">操作失败：${esc(err.message)}</div>`);
  });
});

document.getElementById("saveSub").addEventListener("click", () => {
  addKeywordFromInput();
  save();
});

document.getElementById("markAllRead").addEventListener("click", () => {
  if (unreadTotal === 0) return;
  markRead([], true).catch((e) => {
    pageInfo.textContent = `操作失败：${e.message}`;
  });
});

unreadOnlyBox.addEventListener("change", () => {
  page = 1;
  loadFeed();
});
document.getElementById("prevPage").addEventListener("click", () => {
  if (page > 1) { page -= 1; loadFeed(); }
});
document.getElementById("nextPage").addEventListener("click", () => {
  const maxPage = Math.max(1, Math.ceil(total / 20));
  if (page < maxPage) { page += 1; loadFeed(); }
});

// 暂停/恢复是独立动作，点了立刻生效，不需要再按保存
document.getElementById("toggleEnabled").addEventListener("click", async () => {
  const btn = document.getElementById("toggleEnabled");
  const next = !enabled;
  btn.disabled = true;
  try {
    const data = await apiFetch(`/api/subscriptions/${userId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      // 连当前的关注方向一起回传，避免这次请求把它们清空
      body: JSON.stringify({ topics: selectedTopics, keywords, enabled: next }),
    });
    enabled = data.config.enabled;
    selectedTopics = data.config.topics;
    keywords = data.config.keywords;
    unreadTotal = data.unread_total;
    saveInfo.textContent = enabled ? "提醒已恢复" : "提醒已暂停";
    renderTopicChips();
    renderKeywordChips();
    renderSummary();
    await loadFeed();
  } catch (e) {
    saveInfo.textContent = `操作失败：${e.message}`;
  } finally {
    renderEnabledState();
  }
});

// ─────────────── 启动 ───────────────

(async function init() {
  try {
    renderIdentity();
    userId = await ensureUser();
    await loadTopics();
    await loadConfig();
    await loadFeed();
  } catch (e) {
    summaryBox.innerHTML = `<em style="color:#c33">加载失败：${esc(e.message)}</em>`;
  }
})();
