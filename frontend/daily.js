// 每日数据页：当前为前端 mock 数据
// TODO: 后端尚未提供按日期聚合 ChatLog 请求次数的接口，
//       接口规划：GET /api/stats/daily?date=YYYY-MM-DD → {agent: count, ...}
//       前端已留 fetch 入口，接口上线后把 mockDaily 删掉即可。

const mockDaily = {
  "2026-03-21": { 学业agent: 102, 活动agent: 63, 党团agent: 41, 就业agent: 88, 行政agent: 57 },
  "2026-03-20": { 学业agent: 95, 活动agent: 72, 党团agent: 39, 就业agent: 76, 行政agent: 52 },
  "2026-03-19": { 学业agent: 81, 活动agent: 60, 党团agent: 45, 就业agent: 69, 行政agent: 48 }
};

const datePicker = document.getElementById("datePicker");
const dailyTable = document.getElementById("dailyTable");

async function fetchDaily(date) {
  // 优先尝试后端接口，失败则退回 mock
  try {
    const resp = await fetch(`/api/stats/daily?date=${encodeURIComponent(date)}`);
    if (resp.ok) {
      return await resp.json();
    }
  } catch (_) {
    // 后端尚未实现，静默退回 mock
  }
  return mockDaily[date] || {
    学业agent: 0,
    活动agent: 0,
    党团agent: 0,
    就业agent: 0,
    行政agent: 0
  };
}

async function renderDaily(date) {
  const data = await fetchDaily(date);
  dailyTable.innerHTML = "";
  Object.entries(data).forEach(([name, count]) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${name}</td><td>${count}</td>`;
    dailyTable.appendChild(tr);
  });
}

const today = new Date().toISOString().slice(0, 10);
datePicker.value = today;
renderDaily(today);

document.getElementById("loadData").addEventListener("click", () => {
  renderDaily(datePicker.value);
});
