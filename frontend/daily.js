// 每日数据页：接入真实 /api/stats/daily 与 /api/stats/crawl-runs。
// 展示三块内容：
//   1) 当日爬虫巡查与新增汇总
//   2) 当日各 source 巡查详情
//   3) 最近 20 条爬虫流水（实时知识库更新日志）

const datePicker = document.getElementById("datePicker");
const summaryBox = document.getElementById("dailySummary");
const dailyTable = document.getElementById("dailyTable");
const logsBox = document.getElementById("crawlLogs");

const SOURCE_LABEL = {
  cuc_jwc_notice: "教务处通知",
  cuc_cs_notice: "计网学院通知",
  cuc_career: "就业网通知",
  wechat_mp: "学院公众号",
};

function fmtTime(isoStr) {
  if (!isoStr) return "—";
  const d = new Date(isoStr);
  if (isNaN(d.getTime())) return isoStr;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function labelSource(src) {
  return SOURCE_LABEL[src] || src;
}

async function fetchDaily(dateStr) {
  const resp = await fetch(`/api/stats/daily?date=${encodeURIComponent(dateStr)}`);
  if (!resp.ok) throw new Error(`/api/stats/daily ${resp.status}`);
  return await resp.json();
}

async function fetchRecentRuns() {
  const resp = await fetch(`/api/stats/crawl-runs?limit=20`);
  if (!resp.ok) throw new Error(`/api/stats/crawl-runs ${resp.status}`);
  return await resp.json();
}

function renderSummary(data) {
  const totalRuns = data.by_spider.reduce((a, b) => a + b.runs, 0);
  const totalSuccess = data.by_spider.reduce((a, b) => a + b.success, 0);
  const totalFailed = data.by_spider.reduce((a, b) => a + b.failed, 0);
  const totalNew = data.new_articles.total;
  const cats = Object.entries(data.new_articles.by_category)
    .map(([k, v]) => `${k} ${v}`)
    .join("、") || "无";

  summaryBox.innerHTML = `
    <div class="kv"><span>巡查总次数</span><strong>${totalRuns}</strong></div>
    <div class="kv"><span>成功 / 失败</span><strong>${totalSuccess} / ${totalFailed}</strong></div>
    <div class="kv"><span>新增通知总数</span><strong>${totalNew}</strong></div>
    <div class="kv"><span>分类拆分</span><strong>${cats}</strong></div>
    <div class="kv"><span>当日问答数</span><strong>${data.chat_count}</strong></div>
  `;
}

function renderSpiderTable(data) {
  dailyTable.innerHTML = "";
  if (data.by_spider.length === 0) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="5" style="text-align:center;color:#888">当日尚无爬虫记录</td>`;
    dailyTable.appendChild(tr);
    return;
  }
  data.by_spider.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${labelSource(row.source)}</td>
      <td>${row.runs}</td>
      <td>${row.success} / ${row.failed}</td>
      <td>${row.total}</td>
      <td>${row.inserted}</td>
    `;
    dailyTable.appendChild(tr);
  });
}

function renderRecentRuns(runs) {
  if (!runs || runs.length === 0) {
    logsBox.innerHTML = `<em>暂无爬虫流水</em>`;
    return;
  }
  logsBox.innerHTML = runs
    .map((r) => {
      const dot = r.status === "success"
        ? "🟢"
        : r.status === "failed"
          ? "🔴"
          : "🟡";
      const tail = r.error_message ? ` · ⚠ ${r.error_message}` : "";
      return `<div class="log-row">
        ${dot} ${fmtTime(r.started_at)} <strong>${labelSource(r.source)}</strong>
        · 抓取 ${r.total} 新增 <strong>${r.inserted}</strong> 跳过 ${r.skipped}${tail}
      </div>`;
    })
    .join("");
}

async function render(dateStr) {
  try {
    const [daily, runs] = await Promise.all([fetchDaily(dateStr), fetchRecentRuns()]);
    renderSummary(daily);
    renderSpiderTable(daily);
    renderRecentRuns(runs);
  } catch (e) {
    summaryBox.innerHTML = `<em style="color:#c33">加载失败：${e.message}</em>`;
    dailyTable.innerHTML = "";
    logsBox.innerHTML = "";
  }
}

const today = new Date().toISOString().slice(0, 10);
datePicker.value = today;
render(today);

document.getElementById("loadData").addEventListener("click", () => {
  render(datePicker.value);
});
