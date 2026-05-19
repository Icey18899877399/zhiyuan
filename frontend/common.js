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

// 页面加载时自动初始化
document.addEventListener('DOMContentLoaded', () => {
  DarkModeManager.init();
});