// 로컬 저장소: 만든 숏폼(영상 Blob 포함)은 IndexedDB, 사용량은 localStorage.
// 모두 이 브라우저에만 저장되며, 저장이 막힌 환경에서는 메모리로 대체합니다.

const FREE_MINUTES = 90;
const Store = (() => {
  const mem = [];
  let dbp;
  const open = () => dbp || (dbp = new Promise((res, rej) => {
    const req = indexedDB.open('clipora', 1);
    req.onupgradeneeded = () => req.result.createObjectStore('shorts', { keyPath: 'id' });
    req.onsuccess = () => res(req.result);
    req.onerror = () => rej(req.error);
  }));
  const tx = async (mode, fn) => {
    const db = await open();
    return new Promise((res, rej) => {
      const t = db.transaction('shorts', mode);
      const r = fn(t.objectStore('shorts'));
      t.oncomplete = () => res(r && r.result);
      t.onerror = () => rej(t.error);
    });
  };

  return {
    async add(item) {
      try { await tx('readwrite', (s) => s.put(item)); } catch (_) { mem.push(item); }
    },
    async all() {
      try { return (await tx('readonly', (s) => s.getAll())).sort((a, b) => b.createdAt - a.createdAt); }
      catch (_) { return [...mem].sort((a, b) => b.createdAt - a.createdAt); }
    },
    async remove(id) {
      try { await tx('readwrite', (s) => s.delete(id)); } catch (_) { mem.splice(mem.findIndex((m) => m.id === id), 1); }
    },
    usedSec() {
      try { return +localStorage.getItem('clipora.usedSec') || 0; } catch (_) { return Store._used || 0; }
    },
    addUsed(sec) {
      const v = this.usedSec() + sec;
      try { localStorage.setItem('clipora.usedSec', v); } catch (_) { Store._used = v; }
      return v;
    },
    template(id) {
      try {
        if (id) localStorage.setItem('clipora.template', id);
        return localStorage.getItem('clipora.template');
      } catch (_) { return id || null; }
    },
  };
})();
