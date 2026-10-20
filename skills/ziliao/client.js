(function () {
  if (window.__ziliaoClient) return;
  window.__ziliaoClient = true;

  function hidePluginEntry() {
    document.querySelectorAll("a.plugin-link").forEach(function (node) { node.remove(); });
  }

  function boot() {
    hidePluginEntry();
    if (!window.pywebview || !window.pywebview.api) {
      window.addEventListener("pywebviewready", boot, { once: true });
      return;
    }
    const top = document.querySelector(".top");
    if (!top || document.getElementById("ziliao-client")) return;
    const bar = document.createElement("div");
    bar.id = "ziliao-client";
    bar.innerHTML = '<span>下载位置</span><span id="ziliao-client-dir"></span><button type="button" id="ziliao-client-pick">更改</button><span id="ziliao-client-note"></span>';
    top.prepend(bar);
    const style = document.createElement("style");
    style.textContent = "#ziliao-client{display:flex;align-items:center;gap:10px;margin:0 0 10px;padding:8px 10px;border:1px solid var(--line,#d8dee6);border-radius:8px;background:var(--bg,#f3f4f6);font-size:13px}#ziliao-client button{border:1px solid var(--line,#d8dee6);background:#fff;border-radius:8px;padding:4px 10px;cursor:pointer}#ziliao-client-dir{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}#ziliao-client-note{margin-left:auto;color:var(--muted,#5e6774)}button[data-ziliao-download]{margin-left:8px}";
    document.head.appendChild(style);
    const dir = document.getElementById("ziliao-client-dir");
    const note = document.getElementById("ziliao-client-note");
    function showDir(path) { dir.textContent = path || ""; dir.title = path || ""; }
    window.pywebview.api.current_dir().then(showDir).catch(function () {});
    document.getElementById("ziliao-client-pick").addEventListener("click", function () {
      window.pywebview.api.choose_dir().then(function (path) { if (path) showDir(path); });
    });
    document.documentElement.style.setProperty("--toolbar-h", top.offsetHeight + "px");

    function repoFrom(href) {
      try {
        const url = new URL(href);
        if (url.hostname !== "github.com" && url.hostname !== "www.github.com") return "";
        const parts = url.pathname.split("/").filter(Boolean);
        if (parts.length < 2) return "";
        return parts[0] + "/" + parts[1].replace(/\.git$/, "");
      } catch (error) {
        return "";
      }
    }

    function arm() {
      const root = document.getElementById("detail-body");
      if (!root || root.querySelector("[data-ziliao-download]")) return;
      const link = root.querySelector("a.github");
      if (!link) return;
      const repo = repoFrom(link.href);
      if (!repo) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "github";
      button.dataset.ziliaoDownload = repo;
      button.textContent = "下载到本机";
      button.addEventListener("click", function () {
        button.disabled = true;
        note.textContent = "正在下载 " + repo;
        window.pywebview.api.download(repo).then(function (result) {
          note.textContent = (result && result.message) || "下载结束";
          button.disabled = false;
        }).catch(function () {
          note.textContent = "下载失败";
          button.disabled = false;
        });
      });
      link.insertAdjacentElement("afterend", button);
    }

    const detail = document.getElementById("detail-body");
    if (detail) new MutationObserver(arm).observe(detail, { childList: true });
    arm();
  }

  boot();
})();
