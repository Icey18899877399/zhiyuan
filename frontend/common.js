// 立即执行，防止闪烁
(function() {
  const isDark = localStorage.getItem('darkMode') === 'true';
  if (isDark) {
    document.documentElement.classList.add('dark-chat');
  }
})();

// 深色模式管理
const DarkModeManager = {
  STORAGE_KEY: 'darkMode',
  
  // 初始化深色模式
  init() {
    // 从 documentElement 同步到 body（如果需要）
    const isDark = document.documentElement.classList.contains('dark-chat');
    if (isDark) {
      document.body.classList.add('dark-chat');
    }
    this.bindToggle();
  },
  
  // 绑定切换事件
  bindToggle() {
    const toggle = document.getElementById('darkToggle');
    if (toggle) {
      toggle.addEventListener('click', () => this.toggle());
    }
  },
  
  // 切换深色模式
  toggle() {
    document.documentElement.classList.toggle('dark-chat');
    document.body.classList.toggle('dark-chat');
    const isDark = document.documentElement.classList.contains('dark-chat');
    localStorage.setItem(this.STORAGE_KEY, isDark);
  },
  
  // 检查是否为深色模式
  isDark() {
    return document.documentElement.classList.contains('dark-chat');
  }
};

// ─────────── 匿名设备身份（订阅模块用） ───────────
// 前端生成一个 UUID 当 openid，后端 /api/users/ensure 建档。
// 这是「为后续公众号端联动预留入口」的落点：将来换成真实微信 openid 时，
// 只需改这里的取值来源，后端与页面都不用动。
const DEVICE_KEY = "zhiyuan_device_id";
const USER_ID_KEY = "zhiyuan_user_id";

function getDeviceId() {
  let id = localStorage.getItem(DEVICE_KEY);
  if (!id) {
    // crypto.randomUUID 只在 secure context 下存在（https 或 localhost）。
    // 用 http://192.168.x.x 局域网访问演示时它是 undefined，
    // 没有这个降级分支的话整页会直接报错白屏。
    if (window.crypto && typeof crypto.randomUUID === "function") {
      id = crypto.randomUUID();
    } else {
      id = "dev-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
    }
    localStorage.setItem(DEVICE_KEY, id);
  }
  return id;
}

// 统一 fetch：非 2xx 时抛出后端给的 detail，页面直接显示在人看得懂的地方
async function apiFetch(path, options) {
  const resp = await fetch(path, options);
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      if (body && body.detail) detail = body.detail;
    } catch (_) {
      /* 响应不是 JSON，用默认文案 */
    }
    throw new Error(detail);
  }
  return resp.json();
}

async function ensureUser() {
  const data = await apiFetch("/api/users/ensure", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ openid: getDeviceId() })
  });
  localStorage.setItem(USER_ID_KEY, String(data.user_id));
  return data.user_id;
}

// ─────────── 未读徽标 ───────────
// 让「网页端提醒」覆盖全部页面，而不是只在「我的订阅」页上生效。
async function refreshUnreadBadge() {
  const badges = document.querySelectorAll("[data-unread-badge]");
  if (!badges.length) return;

  // 还没建过档就不打扰：不给从没进过订阅页的访客凭空建用户
  const userId = localStorage.getItem(USER_ID_KEY);
  if (!userId) return;

  try {
    const data = await apiFetch(`/api/subscriptions/${userId}`);
    const n = data.unread_total || 0;
    badges.forEach((b) => {
      b.textContent = n > 99 ? "99+" : String(n);
      b.hidden = n === 0;
    });
  } catch (_) {
    // 未读提醒是增值功能，失败静默，绝不影响页面其他部分
  }
}

// 页面加载时自动初始化
document.addEventListener('DOMContentLoaded', () => {
  DarkModeManager.init();
  refreshUnreadBadge();
});