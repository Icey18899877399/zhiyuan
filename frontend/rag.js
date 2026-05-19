// 知识库展示：从后端拉真实的分类聚合 + 各分类下最新文章
// 后端契约：
//   GET /api/articles/categories                  → [{category, count}]
//   GET /api/articles?category=X&page_size=20     → {total, items: [{id, title, source, source_url, ...}]}

const kbGrid = document.getElementById("kbGrid");
const docList = document.getElementById("docList");

const CATEGORY_DISPLAY = {
  "学业": "📖 学业知识库",
  "活动": "🪁 活动知识库",
  "党团": "🀄 党团知识库",
  "就业": "🎓 就业知识库",
  "其他": "💼 其他/行政"
};

async function loadCategories() {
  kbGrid.innerHTML = '<div class="subtext">加载知识库分类中...</div>';
  try {
    const resp = await fetch("/api/articles/categories");
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    const cats = await resp.json();
    renderCategories(cats);
  } catch (err) {
    kbGrid.innerHTML = `<div class="subtext">加载失败：${err.message}</div>`;
  }
}

function renderCategories(cats) {
  kbGrid.innerHTML = "";
  if (!cats || cats.length === 0) {
    kbGrid.innerHTML = '<div class="subtext">暂无数据，请等待爬虫运行。</div>';
    return;
  }
  cats.forEach((c) => {
    const item = document.createElement("div");
    item.className = "kb-item";
    const display = CATEGORY_DISPLAY[c.category] || c.category;
    item.innerHTML = `<strong>${display}</strong><div class="subtext top-gap">共 ${c.count} 篇 · 点击查看</div>`;
    item.addEventListener("click", () => loadDocs(c.category));
    kbGrid.appendChild(item);
  });
}

async function loadDocs(category) {
  const display = CATEGORY_DISPLAY[category] || category;
  docList.innerHTML = `<h3 class="doc-title">${display}（加载中...）</h3>`;
  try {
    const url = `/api/articles?category=${encodeURIComponent(category)}&page_size=20`;
    const resp = await fetch(url);
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    const data = await resp.json();
    docList.innerHTML = `<h3 class="doc-title">${display}（共 ${data.total} 篇，显示前 ${data.items.length} 条）</h3>`;
    if (data.items.length === 0) {
      const empty = document.createElement("div");
      empty.className = "subtext";
      empty.textContent = "该分类下还没有文章。";
      docList.appendChild(empty);
      return;
    }
    data.items.forEach((art) => {
      const node = document.createElement("div");
      node.className = "doc";
      const time = art.publish_time ? art.publish_time.slice(0, 10) : "";
      node.innerHTML = `📄 <a href="${art.source_url}" target="_blank" rel="noopener">${art.title}</a> <span class="subtext">[${art.source}${time ? " · " + time : ""}]</span>`;
      docList.appendChild(node);
    });
  } catch (err) {
    docList.innerHTML = `<h3 class="doc-title">${display}</h3><div class="subtext">加载失败：${err.message}</div>`;
  }
}

loadCategories();
