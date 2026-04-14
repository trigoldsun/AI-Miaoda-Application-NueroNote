# NueroNote PWA 配置

## manifest.json

```json
{
  "name": "NueroNote",
  "short_name": "NN",
  "description": "端到端加密笔记同步",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#1a1a2e",
  "theme_color": "#16213e",
  "orientation": "portrait-primary",
  "icons": [
    {
      "src": "/icons/icon-192.png",
      "sizes": "192x192",
      "type": "image/png",
      "purpose": "any maskable"
    },
    {
      "src": "/icons/icon-512.png",
      "sizes": "512x512",
      "type": "image/png",
      "purpose": "any maskable"
    }
  ],
  "categories": ["productivity", "utilities"],
  "screenshots": [
    {
      "src": "/screenshots/mobile-1.png",
      "sizes": "390x844",
      "type": "image/png",
      "form_factor": "narrow"
    }
  ],
  "shortcuts": [
    {
      "name": "新建笔记",
      "short_name": "新建",
      "url": "/?action=new",
      "icons": [{ "src": "/icons/plus.png", "sizes": "96x96" }]
    }
  ]
}
```

## Service Worker (sw.js)

```javascript
const CACHE_NAME = 'nueronote-v1';
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/styles.css',
  '/app.js',
  '/icons/icon-192.png',
  '/icons/icon-512.png'
];

const OFFLINE_URL = '/offline.html';

// 安装
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  );
});

// 激活
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// 拦截请求
self.addEventListener('fetch', (event) => {
  // API请求 - 网络优先
  if (event.request.url.includes('/api/')) {
    event.respondWith(
      fetch(event.request)
        .catch(() => new Response(
          JSON.stringify({ error: 'offline' }),
          { headers: { 'Content-Type': 'application/json' } }
        ))
    );
    return;
  }

  // 静态资源 - 缓存优先
  event.respondWith(
    caches.match(event.request)
      .then((response) => {
        if (response) {
          return response;
        }
        return fetch(event.request)
          .then((response) => {
            if (!response || response.status !== 200) {
              return response;
            }
            const responseToCache = response.clone();
            caches.open(CACHE_NAME)
              .then((cache) => cache.put(event.request, responseToCache));
            return response;
          })
          .catch(() => {
            if (event.request.mode === 'navigate') {
              return caches.match(OFFLINE_URL);
            }
          });
      })
  );
});

// 后台同步
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-notes') {
    event.waitUntil(syncNotes());
  }
});

async function syncNotes() {
  const db = await openDB();
  const notes = await db.getAll('pending_sync');
  
  for (const note of notes) {
    try {
      await fetch('/api/v1/sync/push', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(note)
      });
      await db.delete('pending_sync', note.id);
    } catch (e) {
      console.error('Sync failed:', e);
    }
  }
}

// 推送通知
self.addEventListener('push', (event) => {
  if (!event.data) return;
  
  const data = event.data.json();
  const options = {
    body: data.body,
    icon: '/icons/icon-192.png',
    badge: '/icons/badge.png',
    vibrate: [100, 50, 100],
    data: { url: data.url }
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    clients.openWindow(event.notification.data.url)
  );
});
```

## 移动端优化CSS

```css
/* 移动端基础优化 */
@media (max-width: 768px) {
  :root {
    --font-size-base: 16px;
    --spacing-xs: 4px;
    --spacing-sm: 8px;
    --spacing-md: 16px;
    --spacing-lg: 24px;
  }

  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    -webkit-tap-highlight-color: transparent;
  }

  /* 触摸友好按钮 */
  .btn {
    min-height: 44px;
    min-width: 44px;
    padding: 12px 24px;
  }

  /* 编辑器优化 */
  .editor {
    font-size: 18px;
    line-height: 1.6;
    padding: 16px;
    -webkit-appearance: none;
  }

  /* 手势导航 */
  .swipe-container {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scroll-snap-type: x mandatory;
  }

  /* 防止缩放 */
  input, textarea, select {
    font-size: 16px;
  }

  /* 状态栏适配 */
  .safe-area-top {
    padding-top: env(safe-area-inset-top);
  }
  .safe-area-bottom {
    padding-bottom: env(safe-area-inset-bottom);
  }
}

/* 暗色模式 */
@media (prefers-color-scheme: dark) {
  :root {
    --bg-primary: #1a1a2e;
    --bg-secondary: #16213e;
    --text-primary: #ffffff;
    --text-secondary: #a0a0a0;
    --accent: #0f3460;
  }
}

/* 减少动画 */
@media (prefers-reduced-motion: reduce) {
  * {
    animation: none !important;
    transition: none !important;
  }
}

/* 离线指示器 */
.offline-indicator {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  background: #ff9800;
  color: white;
  text-align: center;
  padding: 8px;
  font-size: 14px;
  z-index: 10000;
  transform: translateY(-100%);
  transition: transform 0.3s ease;
}

.offline-indicator.visible {
  transform: translateY(0);
}
```

## IndexedDB 存储

```javascript
// 离线存储管理器
class OfflineStorage {
  constructor() {
    this.dbName = 'nueronote';
    this.dbVersion = 1;
    this.db = null;
  }

  async init() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(this.dbName, this.dbVersion);
      
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        this.db = request.result;
        resolve();
      };
      
      request.onupgradeneeded = (event) => {
        const db = event.target.result;
        
        // 笔记存储
        if (!db.objectStoreNames.contains('notes')) {
          const store = db.createObjectStore('notes', { keyPath: 'id' });
          store.createIndex('user_id', 'user_id');
          store.createIndex('updated_at', 'updated_at');
        }
        
        // 待同步操作
        if (!db.objectStoreNames.contains('pending_sync')) {
          db.createObjectStore('pending_sync', { keyPath: 'id' });
        }
        
        // 草稿
        if (!db.objectStoreNames.contains('drafts')) {
          db.createObjectStore('drafts', { keyPath: 'id' });
        }
        
        // 附件
        if (!db.objectStoreNames.contains('attachments')) {
          db.createObjectStore('attachments', { keyPath: 'id' });
        }
      };
    });
  }

  async saveNote(note) {
    const tx = this.db.transaction('notes', 'readwrite');
    await tx.objectStore('notes').put(note);
    await tx.complete;
  }

  async getNote(id) {
    const tx = this.db.transaction('notes', 'readonly');
    return tx.objectStore('notes').get(id);
  }

  async getAllNotes(userId) {
    const tx = this.db.transaction('notes', 'readonly');
    const index = tx.objectStore('notes').index('user_id');
    return index.getAll(userId);
  }

  async queueSync(operation) {
    const tx = this.db.transaction('pending_sync', 'readwrite');
    await tx.objectStore('pending_sync').put(operation);
    await tx.complete;
  }
}
```
