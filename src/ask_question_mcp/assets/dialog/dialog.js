(() => {
  const OTHER_IDS = new Set(["other", "something_else", "something-else"]);
  const state = {
    payload: null,
    selected: new Set(),
    armed: false,
    typing: false,
  };

  const $ = (sel) => document.querySelector(sel);

  function esc(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function stripHotkeyPrefix(label) {
    return String(label || "").replace(/^\d+\s*[·.]\s*/, "").trim();
  }

  async function apiCall(name, ...args) {
    // Edge --app / localhost bridge (no pywebview — killable, no destroy hang).
    const bridge = window.__ASK_BRIDGE__;
    if (bridge && typeof bridge === "string") {
      if (name === "content_ready" || name === "resize_to") {
        try {
          await fetch(`${bridge}/event`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, args }),
          });
        } catch (_) {
          /* ignore */
        }
        return null;
      }
      const res = await fetch(`${bridge}/api`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, args }),
      });
      if (!res.ok) {
        throw new Error(`bridge api.${name} HTTP ${res.status}`);
      }
      const data = await res.json();
      return data.result;
    }

    const api = window.pywebview && window.pywebview.api;
    if (!api || typeof api[name] !== "function") {
      throw new Error(`pywebview api.${name} unavailable`);
    }
    return api[name](...args);
  }

  function setArmed(armed) {
    state.armed = armed;
    const ok = $("#ok-btn");
    if (!ok) return;
    ok.disabled = !armed;
    ok.classList.toggle("is-arming", !armed);
    const danger = ok.classList.contains("is-danger");
    if (armed) {
      const fill = ok.querySelector(".arm-fill");
      if (fill) fill.style.width = "100%";
      ok.innerHTML = `
        <span class="arm-fill" style="width:100%"></span>
        <span class="btn-label">OK</span>
        <span class="btn-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17L17 7M17 7H9M17 7v8"/></svg></span>
      `;
      if (danger) ok.classList.add("is-danger");
    }
  }

  function armCountdown(ms) {
    const ok = $("#ok-btn");
    if (ms <= 0) {
      setArmed(true);
      return;
    }
    setArmed(false);
    ok.innerHTML = `
      <span class="arm-fill" style="width:0%"></span>
      <span class="btn-label">OK</span>
      <span class="btn-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17L17 7M17 7H9M17 7v8"/></svg></span>
    `;
    const fill = ok.querySelector(".arm-fill");
    const started = performance.now();
    const tick = (now) => {
      if (state.armed) return;
      const t = Math.min(1, (now - started) / ms);
      if (fill) fill.style.width = `${(t * 100).toFixed(1)}%`;
      if (t >= 1) {
        setArmed(true);
        return;
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  function spawnDots() {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return;
    }
    const layers = [
      { sel: "#stars-near", n: 48, cls: "star-dot is-near" },
      { sel: "#stars-far", n: 36, cls: "star-dot is-far" },
    ];
    layers.forEach(({ sel, n, cls }) => {
      const el = $(sel);
      if (!el) {
        apiCall("debug", `stars missing ${sel}`).catch(() => {});
        return;
      }
      el.innerHTML = "";
      for (let i = 0; i < n; i += 1) {
        const d = document.createElement("span");
        d.className = cls;
        if (i % 9 === 0) d.classList.add("is-bright");
        d.style.left = `${(Math.random() * 100).toFixed(2)}%`;
        d.style.top = `${(Math.random() * 100).toFixed(2)}%`;
        el.appendChild(d);
      }
      apiCall("debug", `stars baked ${sel} n=${n}`).catch(() => {});
    });
  }

  function renderOptions() {
    const p = state.payload;
    const box = $("#options");
    box.innerHTML = "";
    const dangerIds = new Set(p.danger_ids || []);
    const recommended = new Set(p.recommended_ids || []);

    (p.ids || []).forEach((id, i) => {
      const shell = document.createElement("div");
      shell.className = "option-shell";
      shell.dataset.id = id;
      shell.style.transitionDelay = `${100 + i * 70}ms`;
      if (dangerIds.has(id)) shell.classList.add("is-danger");
      if (state.selected.has(id)) shell.classList.add("is-selected");

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "option";
      btn.dataset.id = id;
      if (dangerIds.has(id)) btn.classList.add("is-danger");

      const rawLabel = stripHotkeyPrefix(p.labels?.[id] || id);
      const raw = rawLabel.replace(/\s*\(recommended\)\s*/gi, " ").trim() || rawLabel;
      const mark = dangerIds.has(id) ? '<span class="mark">⛔</span>' : "";
      const rec = recommended.has(id)
        ? '<span class="rec-pill">Recommended</span>'
        : "";
      btn.innerHTML = `
        <span class="hotkey">${i + 1}</span>
        <span class="option-label">${esc(raw)}</span>
        ${rec}
        ${mark}
        <span class="option-check" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg>
        </span>
      `;
      btn.addEventListener("click", () => onPick(id));
      shell.appendChild(btn);
      box.appendChild(shell);
    });
  }

  function syncSelectionUi() {
    document.querySelectorAll(".option-shell").forEach((el) => {
      el.classList.toggle("is-selected", state.selected.has(el.dataset.id));
    });
  }

  function onPick(id) {
    const multi = !!state.payload.allow_multiple;
    if (multi) {
      if (state.selected.has(id)) state.selected.delete(id);
      else state.selected.add(id);
    } else {
      state.selected = new Set([id]);
    }
    syncSelectionUi();
  }

  function freeformText() {
    return ($("#freeform-input")?.value || "").trim();
  }

  async function leaveGently() {
    const app = $("#app");
    if (!app || app.classList.contains("is-leaving")) return;
    app.classList.add("is-leaving");
    await new Promise((r) => setTimeout(r, 280));
  }

  async function submit() {
    if (!state.armed) return;
    const typed = freeformText();
    let ids = [...state.selected];
    if (typed) {
      const other = (state.payload.ids || []).find((id) => OTHER_IDS.has(id));
      if (other && !ids.includes(other)) ids = [other];
      if (!other) ids = ids.length ? ids : ["other"];
    }
    if (!ids.length) return;
    await leaveGently();
    try {
      await apiCall("submit", ids, typed || null);
    } catch (err) {
      console.error(err);
    }
    try {
      window.close();
    } catch (_) {
      /* Edge --app may ignore */
    }
  }

  async function cancel(reason = "user cancelled") {
    await leaveGently();
    try {
      await apiCall("cancel", reason);
    } catch (err) {
      console.error(err);
    }
    try {
      window.close();
    } catch (_) {
      /* ignore */
    }
  }

  function onKey(e) {
    const typing =
      document.activeElement &&
      document.activeElement.id === "freeform-input";
    if (e.key === "Escape") {
      e.preventDefault();
      cancel();
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      if (typing) {
        // Enter submits; Shift+Enter inserts a newline in the textarea.
        e.preventDefault();
        const other = (state.payload.ids || []).find((id) => OTHER_IDS.has(id));
        if (freeformText() && other) state.selected = new Set([other]);
        submit();
        return;
      }
      e.preventDefault();
      submit();
      return;
    }
    if (typing) return;
    if (/^[1-8]$/.test(e.key)) {
      const idx = Number(e.key) - 1;
      const id = state.payload.ids?.[idx];
      if (id) {
        e.preventDefault();
        onPick(id);
      }
    }
  }

  function mount(payload) {
    state.payload = payload;
    spawnDots();
    const theme = String(payload.theme || "glass").toLowerCase();
    const app = $("#app");
    if (app) {
      app.dataset.theme = ["glass", "ink", "signal", "hybrid"].includes(theme)
        ? theme
        : "glass";
    }
    const pre = payload.preselect || payload.recommended_ids || [];
    state.selected = new Set(
      pre.length ? pre.map(String) : payload.ids?.[0] ? [payload.ids[0]] : [],
    );

    const dangerous = !!(payload.dangerous || (payload.danger_ids || []).length);
    $("#eyebrow").textContent = dangerous ? "Confirm" : "Decide";
    $("#eyebrow").classList.toggle("is-danger", dangerous);
    $("#title-agent").textContent = payload.agent_hint || payload.title || "";
    $("#question").textContent = payload.question || "";

    const banner = $("#banner");
    banner.classList.toggle("is-on", dangerous);
    $("#banner-copy").textContent = dangerous
      ? `⛔ Confirm — ${payload.question || ""}`
      : "";

    const ok = $("#ok-btn");
    ok.classList.toggle("is-danger", dangerous);

    const showOther = payload.allow_other !== false;
    $("#freeform").hidden = !showOther;
    if (showOther) {
      $("#freeform-input").addEventListener("input", () => {
        const typed = freeformText();
        if (!typed) return;
        const other = (payload.ids || []).find((id) => OTHER_IDS.has(id));
        if (other) {
          state.selected = new Set([other]);
          syncSelectionUi();
        }
      });
    }

    renderOptions();

    const n = Math.min(8, (payload.ids || []).length);
    const hint = $("#hint");
    if (hint) {
      hint.textContent =
        n <= 1
          ? "Enter OK · Esc cancel"
          : `1–${n} select · Enter OK · Esc cancel · Shift+Enter newline`;
    }

    document.addEventListener("keydown", onKey);
    $("#cancel-btn").addEventListener("click", () => cancel());
    $("#close-btn").addEventListener("click", () => cancel());
    $("#ok-btn").addEventListener("click", () => submit());

    const armMs =
      typeof payload.arm_ms === "number"
        ? payload.arm_ms
        : dangerous
          ? 4000
          : 1000;
    armCountdown(armMs);
    apiCall("debug", `mount:arm_ms=${armMs}`).catch(() => {});

    // Visible before raise — opacity:0 + raise looked like a black void,
    // and Edge --app throttles rAF when unfocused.
    $("#app").classList.add("is-ready");
    apiCall("content_ready").catch(() => {});
    apiCall("debug", "mount:content_ready_sent").catch(() => {});
    requestAnimationFrame(() => fitWindow());

    if (payload.timeout_sec > 0) {
      setTimeout(() => cancel("timeout"), payload.timeout_sec * 1000);
    }
  }

  function fitWindow() {
    const chrome = document.querySelector(".chrome");
    const banner = document.getElementById("banner");
    const question = document.getElementById("question");
    const options = document.getElementById("options");
    const freeform = document.getElementById("freeform");
    const footer = document.querySelector(".footer");
    let h = 28;
    [chrome, question, freeform, footer].forEach((el) => {
      if (el && !el.hidden) h += el.offsetHeight;
    });
    if (banner && banner.classList.contains("is-on")) {
      h += banner.offsetHeight + 8;
    }
    // Gaps in .body
    h += 42;
    let optsH = 0;
    if (options) {
      options.querySelectorAll(".option").forEach((o) => {
        optsH += o.offsetHeight + 8;
      });
      // Scroll options beyond this — keep freeform + footer on screen.
      h += Math.min(optsH, 420);
    }
    const w = Math.max(520, Math.min(760, window.outerWidth || 560));
    apiCall("resize_to", w, Math.ceil(h)).catch(() => {});
  }

  async function boot() {
    const waitApi = () =>
      new Promise((resolve, reject) => {
        const tryNow = () => {
          if (window.__ASK_BRIDGE__) {
            resolve();
            return true;
          }
          if (window.pywebview && window.pywebview.api) {
            resolve();
            return true;
          }
          return false;
        };
        if (tryNow()) return;
        window.addEventListener("pywebviewready", () => tryNow());
        let n = 0;
        const iv = setInterval(() => {
          n += 1;
          if (tryNow()) {
            clearInterval(iv);
            return;
          }
          if (n > 100) {
            clearInterval(iv);
            reject(new Error("dialog bridge unavailable (pywebview / Edge)"));
          }
        }, 50);
      });

    await waitApi();
    apiCall("debug", "boot:api_ready").catch(() => {});
    const payload = await apiCall("get_payload");
    apiCall("debug", `boot:payload n=${(payload && payload.ids || []).length}`).catch(
      () => {},
    );
    mount(payload || {});
    apiCall("debug", "boot:mounted").catch(() => {});
  }

  boot().catch((err) => {
    console.error(err);
    document.body.innerHTML = `<pre style="color:#ff5c7a;padding:16px">${esc(
      String(err),
    )}</pre>`;
  });
})();