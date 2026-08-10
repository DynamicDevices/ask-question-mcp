(() => {
  // Port of theoriginalcheese Windows Nebula dialog.js, with Linux-only
  // bridge fixes (boot TDZ, native paste inject, snappy closing, paste cap).
  const OTHER_IDS = new Set(["other", "something_else", "something-else"]);
  const MAX_PASTED = 4;
  // Keep clipboard stills small — huge data-URLs blank/freeze WebView2 under Cursor.
  const PASTE_MAX_EDGE = 1280;
  const PASTE_JPEG_QUALITY = 0.82;
  const PASTE_MAX_B64_CHARS = 1_800_000; // ~1.3 MiB decoded
  const state = {
    payload: null,
    selected: new Set(),
    focusIdx: 0,
    armed: false,
    typing: false,
    pasted: [],
    timeoutId: null,
    engaged: false,
    closing: false,
    voice: null,
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

  /** Match dialog_keys.format_confirm_body — dense " · " packs become lines. */
  function formatConfirmBody(question) {
    const q = String(question || "").trim();
    if (!q) return q;
    if (q.includes("\n")) return q;
    if (q.includes(" · ")) {
      const parts = q
        .split(" · ")
        .map((p) => p.trim())
        .filter(Boolean);
      if (parts.length >= 2) return parts.join("\n");
    }
    return q;
  }

  /** Match dialog_keys.split_lead_detail — first line = ask/referent lead. */
  function splitLeadDetail(body) {
    const text = String(body || "").replace(/^\n+|\n+$/g, "");
    if (!text.trim()) return ["", ""];
    const lines = text.split("\n");
    let i = 0;
    while (i < lines.length && !lines[i].trim()) i += 1;
    if (i >= lines.length) return ["", ""];
    const lead = lines[i];
    const rest = lines.slice(i + 1);
    while (rest.length && !rest[0].trim()) rest.shift();
    return [lead, rest.join("\n").replace(/\n+$/g, "")];
  }

  function renderQuestion(rawQuestion) {
    const body = formatConfirmBody(rawQuestion);
    const [lead, detail] = splitLeadDetail(body);
    const qEl = $("#question");
    const dEl = $("#question-detail");
    if (qEl) qEl.textContent = lead || body || "";
    if (dEl) {
      if (detail) {
        dEl.hidden = false;
        dEl.textContent = detail;
      } else {
        dEl.hidden = true;
        dEl.textContent = "";
      }
    }
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function apiCall(name, ...args) {
    // Edge --app / Linux WebKit localhost bridge (no pywebview — killable).
    const bridge = window.__ASK_BRIDGE__;
    if (bridge && typeof bridge === "string") {
      if (
        name === "content_ready" ||
        name === "resize_to" ||
        name === "hold_timeout" ||
        name === "closing" ||
        name === "begin_move" ||
        name === "maximize"
      ) {
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

    // pywebview injects api:{} before finish.js binds methods — retry briefly.
    for (let i = 0; i < 80; i += 1) {
      const api = window.pywebview && window.pywebview.api;
      if (api && typeof api[name] === "function") {
        return api[name](...args);
      }
      await sleep(25);
    }
    throw new Error(`pywebview api.${name} unavailable`);
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
    const ids = state.payload?.ids || [];
    document.querySelectorAll(".option-shell").forEach((el) => {
      el.classList.toggle("is-selected", state.selected.has(el.dataset.id));
      const idx = ids.indexOf(el.dataset.id);
      el.classList.toggle("is-focused", idx === state.focusIdx);
    });
  }

  function onPick(id) {
    const multi = !!state.payload.allow_multiple;
    const ids = state.payload.ids || [];
    const idx = ids.indexOf(id);
    if (idx >= 0) state.focusIdx = idx;
    if (multi) {
      if (state.selected.has(id)) state.selected.delete(id);
      else state.selected.add(id);
    } else {
      state.selected = new Set([id]);
    }
    syncSelectionUi();
  }

  function moveOptionFocus(delta) {
    const ids = state.payload?.ids || [];
    if (!ids.length) return;
    let idx = state.focusIdx;
    if (idx == null || idx < 0 || idx >= ids.length) {
      const cur = [...state.selected][0];
      idx = Math.max(0, ids.indexOf(cur));
    }
    idx = Math.max(0, Math.min(ids.length - 1, idx + delta));
    state.focusIdx = idx;
    if (!state.payload.allow_multiple) {
      state.selected = new Set([ids[idx]]);
    }
    syncSelectionUi();
    const shells = document.querySelectorAll(".option-shell");
    const shell = shells[idx];
    if (shell) shell.scrollIntoView({ block: "nearest" });
  }

  function freeformText() {
    return ($("#freeform-input")?.value || "").trim();
  }

  function markEngaged() {
    if (state.engaged) return;
    state.engaged = true;
    if (state.timeoutId != null) {
      clearTimeout(state.timeoutId);
      state.timeoutId = null;
    }
    apiCall("hold_timeout").catch(() => {});
  }

  function dataUrlToPayload(dataUrl) {
    const m = /^data:(image\/[a-z0-9.+-]+);base64,(.+)$/i.exec(dataUrl || "");
    if (!m) return null;
    let mime = m[1].toLowerCase();
    if (mime === "image/jpg") mime = "image/jpeg";
    if (!["image/png", "image/jpeg", "image/webp", "image/gif"].includes(mime)) {
      return null;
    }
    const data = m[2];
    if (data.length > PASTE_MAX_B64_CHARS) return null;
    return { mime, data };
  }

  function loadImageFromUrl(url) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("image decode failed"));
      img.src = url;
    });
  }

  async function compactFileToDataUrl(file) {
    // Decode via blob URL (not a giant data: string) then JPEG-downscale.
    const blobUrl = URL.createObjectURL(file);
    try {
      const img = await loadImageFromUrl(blobUrl);
      let w = img.naturalWidth || img.width || 0;
      let h = img.naturalHeight || img.height || 0;
      if (w < 1 || h < 1) return null;
      const scale = Math.min(1, PASTE_MAX_EDGE / Math.max(w, h));
      w = Math.max(1, Math.round(w * scale));
      h = Math.max(1, Math.round(h * scale));
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      if (!ctx) return null;
      ctx.drawImage(img, 0, 0, w, h);
      let out = canvas.toDataURL("image/jpeg", PASTE_JPEG_QUALITY);
      let q = PASTE_JPEG_QUALITY;
      while (out.length > PASTE_MAX_B64_CHARS && q > 0.45) {
        q -= 0.12;
        out = canvas.toDataURL("image/jpeg", q);
      }
      if (out.length > PASTE_MAX_B64_CHARS) return null;
      return out;
    } catch (_) {
      return null;
    } finally {
      try {
        URL.revokeObjectURL(blobUrl);
      } catch (_) {
        /* ignore */
      }
    }
  }

  function renderRefs() {
    const box = $("#refs");
    const strip = $("#refs-strip");
    if (!box || !strip) return;
    strip.innerHTML = "";
    if (!state.pasted.length) {
      box.hidden = true;
      requestAnimationFrame(() => fitWindow());
      return;
    }
    box.hidden = false;
    state.pasted.forEach((item, i) => {
      const tile = document.createElement("div");
      tile.className = "ref-tile";
      tile.setAttribute("role", "listitem");
      const img = document.createElement("img");
      img.src = item.dataUrl;
      img.alt = `Reference ${i + 1}`;
      const rm = document.createElement("button");
      rm.type = "button";
      rm.className = "ref-remove";
      rm.setAttribute("aria-label", `Remove reference ${i + 1}`);
      rm.textContent = "×";
      rm.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        state.pasted.splice(i, 1);
        renderRefs();
      });
      tile.appendChild(img);
      tile.appendChild(rm);
      strip.appendChild(tile);
    });
    // Options area flex-shrinks; footer stays. Still ask host to grow when possible.
    requestAnimationFrame(() => fitWindow());
  }

  function addPastedDataUrl(dataUrl) {
    if (state.pasted.length >= MAX_PASTED) return false;
    const payload = dataUrlToPayload(dataUrl);
    if (!payload) return false;
    state.pasted.push({ ...payload, dataUrl });
    markEngaged();
    renderRefs();
    return true;
  }

  async function onPaste(e) {
    const cd = e.clipboardData;
    if (!cd) return;
    const files = [];
    if (cd.files && cd.files.length) {
      for (const f of cd.files) {
        if (f && String(f.type || "").startsWith("image/")) files.push(f);
      }
    }
    if (!files.length && cd.items) {
      for (const item of cd.items) {
        if (item.kind === "file" && String(item.type || "").startsWith("image/")) {
          const f = item.getAsFile();
          if (f) files.push(f);
        }
      }
    }
    if (!files.length) return;
    e.preventDefault();
    for (const file of files) {
      if (state.pasted.length >= MAX_PASTED) break;
      try {
        const compact = await compactFileToDataUrl(file);
        if (!compact) continue;
        addPastedDataUrl(compact);
      } catch (_) {
        /* skip unreadable clipboard items */
      }
    }
  }

  function markLeaving() {
    const app = $("#app");
    if (app) app.classList.add("is-leaving");
  }

  function pastedPayload() {
    const items = state.pasted.map(({ mime, data }) => ({ mime, data }));
    // Linux HTTP bridge can carry more than Win pywebview; keep as many as fit.
    const maxChars = 700000;
    const kept = [];
    for (const item of items) {
      const trial = JSON.stringify([...kept, item]).length;
      if (trial > maxChars) {
        console.warn(
          `dropping pasted still(s) after ${kept.length}; bridge payload would be ${trial} chars`,
        );
        const hint = $("#hint");
        if (hint) {
          hint.textContent = `Paste too large — kept ${kept.length}/${items.length} · Enter OK`;
        }
        break;
      }
      kept.push(item);
    }
    return kept;
  }

  async function submit() {
    if (!state.armed || state.closing) return;
    const typed = freeformText();
    let ids = [...state.selected];
    if (typed) {
      const other = (state.payload.ids || []).find((id) => OTHER_IDS.has(id));
      if (other && !ids.includes(other)) ids = [other];
      if (!other) ids = ids.length ? ids : ["other"];
    }
    if (!ids.length) return;
    state.closing = true;
    // Instant visual + host hide — do not await closing (felt like laggy Enter).
    markLeaving();
    apiCall("closing").catch(() => {});
    try {
      await apiCall("submit", ids, typed || null, pastedPayload());
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
    if (state.closing) return;
    state.closing = true;
    markLeaving();
    apiCall("closing").catch(() => {});
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

  function applyVoiceUi(snap) {
    if (!snap || typeof snap !== "object") return;
    state.voice = { ...(state.voice || {}), ...snap };
    const bar = $("#voice-bar");
    const status = $("#voice-status");
    const recover = $("#voice-recover");
    const recoverLbl = $("#voice-recover-label");
    const useThis = $("#voice-use-this-btn");
    const audioChk = $("#audio-chk");
    const alwaysLbl = $("#always-listen-label");
    const alwaysChk = $("#always-listen-chk");
    const replay = $("#replay-btn");
    const listen = $("#listen-btn");
    const showBar = !!(snap.speak_enabled || snap.voice_answer || audioChk);
    if (bar) bar.hidden = !showBar;
    if (status) {
      const text = String(snap.status_text || "");
      status.hidden = !text;
      status.textContent = text;
      status.dataset.state = snap.status_state || "idle";
      status.title = text;
    }
    if (recover) {
      recover.hidden = !snap.recover_visible;
    }
    if (recoverLbl && snap.recover_label != null) {
      recoverLbl.textContent = String(snap.recover_label || "");
    }
    if (useThis) {
      useThis.hidden = !snap.use_this_visible;
    }
    if (audioChk && typeof snap.audio_enabled === "boolean") {
      audioChk.checked = snap.audio_enabled;
    }
    if (replay) {
      replay.hidden = !snap.speak_enabled;
    }
    if (listen) {
      listen.hidden = !snap.voice_answer;
    }
    if (alwaysLbl) {
      alwaysLbl.hidden = !snap.voice_answer;
    }
    if (alwaysChk && typeof snap.always_listen === "boolean") {
      alwaysChk.checked = snap.always_listen;
    }
    if (snap.select_id) {
      onPick(String(snap.select_id));
    }
    if (snap.freeform_text != null) {
      const input = $("#freeform-input");
      if (input) input.value = String(snap.freeform_text);
    }
    if (snap.request_submit) {
      submit();
    }
    updateHint();
    requestAnimationFrame(() => fitWindow());
  }

  function wireVoiceControls() {
    const audioChk = $("#audio-chk");
    const alwaysChk = $("#always-listen-chk");
    const replay = $("#replay-btn");
    const listen = $("#listen-btn");
    const repeat = $("#voice-repeat-btn");
    const useThis = $("#voice-use-this-btn");
    if (audioChk) {
      audioChk.addEventListener("change", () => {
        apiCall("set_audio_enabled", !!audioChk.checked).catch(() => {});
      });
    }
    if (alwaysChk) {
      alwaysChk.addEventListener("change", () => {
        apiCall("set_always_listen", !!alwaysChk.checked).catch(() => {});
      });
    }
    if (replay) {
      replay.addEventListener("click", () => {
        markEngaged();
        apiCall("voice_replay").catch(() => {});
      });
    }
    if (listen) {
      listen.addEventListener("click", () => {
        markEngaged();
        apiCall("voice_listen").catch(() => {});
      });
    }
    if (repeat) {
      repeat.addEventListener("click", () => {
        markEngaged();
        apiCall("voice_recover_repeat").catch(() => {});
      });
    }
    if (useThis) {
      useThis.addEventListener("click", () => {
        markEngaged();
        apiCall("voice_use_this").catch(() => {});
      });
    }
    window.__ASK_VOICE_UPDATE__ = (snap) => applyVoiceUi(snap || {});
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
    if (e.key === "ArrowDown") {
      e.preventDefault();
      markEngaged();
      moveOptionFocus(1);
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      markEngaged();
      moveOptionFocus(-1);
      return;
    }
    if (/^[1-8]$/.test(e.key)) {
      const idx = Number(e.key) - 1;
      const id = state.payload.ids?.[idx];
      if (id) {
        e.preventDefault();
        onPick(id);
      }
      return;
    }
    const v = state.voice || {};
    if (v.speak_enabled && (e.key === "r" || e.key === "R")) {
      e.preventDefault();
      markEngaged();
      apiCall("voice_replay").catch(() => {});
      return;
    }
    if (v.voice_answer && (e.key === "l" || e.key === "L")) {
      e.preventDefault();
      markEngaged();
      apiCall("voice_listen").catch(() => {});
    }
  }

  function updateHint() {
    const n = Math.min(8, (state.payload.ids || []).length);
    const hint = $("#hint");
    if (!hint) return;
    const v = state.voice || {};
    let base =
      n <= 1
        ? "Enter OK · Esc cancel"
        : `↑↓ / 1–${n} select · Enter OK · Esc cancel · Shift+Enter newline`;
    if (v.speak_enabled) base += " · R replay";
    if (v.voice_answer) base += " · L listen";
    hint.textContent = `${base} · Ctrl+V image`;
  }

  function wireChromeDrag() {
    const chrome = document.querySelector(".chrome");
    if (!chrome || chrome.dataset.dragWired === "1") return;
    chrome.dataset.dragWired = "1";
    chrome.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      if (e.target.closest("button, a, input, textarea, select, label")) return;
      // WebKitGTK ignores pywebview-drag-region — ask the Gtk host to move.
      if (window.__ASK_BRIDGE__) {
        e.preventDefault();
        // GDK button numbers are 1-based (left = 1).
        apiCall("begin_move", e.button + 1, e.screenX, e.screenY).catch(
          () => {},
        );
      }
    });
    chrome.addEventListener("dblclick", (e) => {
      if (e.target.closest("button, a, input, textarea, select, label")) return;
      apiCall("maximize").catch(() => {});
    });
  }

  function mount(payload) {
    state.payload = payload;
    spawnDots();
    const theme = String(payload.theme || "glass").toLowerCase();
    const app = $("#app");
    if (app) {
      const allowed = ["glass", "ink", "signal", "hybrid", "light"];
      app.dataset.theme = allowed.includes(theme) ? theme : "glass";
      const scheme = app.dataset.theme === "light" ? "light" : "dark";
      try {
        document.documentElement.style.colorScheme = scheme;
        document.body.style.colorScheme = scheme;
      } catch (_) {
        /* ignore */
      }
    }
    const pre = payload.preselect || payload.recommended_ids || [];
    state.selected = new Set(
      pre.length ? pre.map(String) : payload.ids?.[0] ? [payload.ids[0]] : [],
    );
    const ids = payload.ids || [];
    const focusId = [...state.selected][0];
    state.focusIdx = Math.max(0, ids.indexOf(focusId));

    const dangerous = !!(payload.dangerous || (payload.danger_ids || []).length);
    const band =
      String(payload.action_class || "").toLowerCase() ||
      (dangerous ? "destructive" : "");
    const bandClass = band ? `is-${band}` : "";
    const eyebrowEl = $("#eyebrow");
    const BANDS = ["file", "secrets", "comms", "destructive", "policy", "danger"];
    eyebrowEl.textContent =
      payload.eyebrow || (dangerous ? "Confirm" : "Decide");
    for (const b of BANDS) eyebrowEl.classList.remove(`is-${b}`);
    if (bandClass) eyebrowEl.classList.add(bandClass);
    else if (dangerous) eyebrowEl.classList.add("is-danger");
    $("#title-agent").textContent = payload.agent_hint || payload.title || "";
    renderQuestion(payload.question || "");

    const banner = $("#banner");
    banner.classList.toggle("is-on", dangerous);
    for (const b of BANDS) banner.classList.remove(`is-${b}`);
    if (bandClass) banner.classList.add(bandClass);
    else if (dangerous) banner.classList.add("is-danger");
    // Band strip only — never paste the question here (eyebrow + #question
    // already carry the ask; repeating it made dangerous MCQs look doubled).
    const prefix = String(
      payload.banner_prefix || (dangerous ? "⛔ Confirm" : ""),
    )
      .replace(/\s*[—\-–:]\s*$/, "")
      .trim();
    $("#banner-copy").textContent = dangerous ? prefix : "";

    const ok = $("#ok-btn");
    for (const b of BANDS) ok.classList.remove(`is-${b}`);
    ok.classList.toggle("is-danger", dangerous && (!band || band === "destructive"));
    if (bandClass && band !== "destructive") ok.classList.add(bandClass);
    else if (dangerous) ok.classList.add("is-danger");

    const showOther = payload.allow_other !== false;
    $("#freeform").hidden = !showOther;
    if (showOther) {
      const input = $("#freeform-input");
      if (input) {
        if (payload.entry_seed) input.value = String(payload.entry_seed);
        input.addEventListener("input", () => {
          markEngaged();
          const typed = freeformText();
          if (!typed) return;
          const other = (payload.ids || []).find((id) => OTHER_IDS.has(id));
          if (other) {
            state.selected = new Set([other]);
            syncSelectionUi();
          }
        });
      }
    }

    renderOptions();
    syncSelectionUi();
    wireVoiceControls();
    wireChromeDrag();
    const hasVoiceHost =
      payload.voice_ui != null ||
      typeof payload.audio_enabled === "boolean" ||
      !!payload.speak_enabled ||
      !!payload.voice_answer;
    const bar = $("#voice-bar");
    if (bar) bar.hidden = !hasVoiceHost;
    if (hasVoiceHost) {
      const voiceUi = payload.voice_ui || {
        speak_enabled: !!payload.speak_enabled,
        voice_answer: !!payload.voice_answer,
        audio_enabled:
          typeof payload.audio_enabled === "boolean"
            ? payload.audio_enabled
            : true,
        always_listen: !!payload.always_listen,
        status_state: "idle",
        status_text: "",
        recover_visible: false,
        recover_label: "",
        use_this_visible: false,
      };
      applyVoiceUi(voiceUi);
    }
    updateHint();

    document.addEventListener("keydown", onKey);
    document.addEventListener("paste", (e) => {
      onPaste(e).catch(() => {});
    });
    // Native Linux host injects clipboard textures when WebKit paste is empty.
    window.__ASK_ADD_PASTED__ = (dataUrl) => addPastedDataUrl(String(dataUrl || ""));
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
    // Poll once in case push arrived before the page wired __ASK_VOICE_UPDATE__.
    apiCall("get_voice_state")
      .then((snap) => {
        if (snap) applyVoiceUi(snap);
      })
      .catch(() => {});

    if (payload.timeout_sec > 0) {
      state.timeoutId = setTimeout(
        () => cancel("timeout"),
        payload.timeout_sec * 1000,
      );
    }
  }

  function fitWindow() {
    const chrome = document.querySelector(".chrome");
    const banner = document.getElementById("banner");
    const questionBlock = document.getElementById("question-block");
    const question = document.getElementById("question");
    const options = document.getElementById("options");
    const refs = document.getElementById("refs");
    const freeform = document.getElementById("freeform");
    const footer = document.querySelector(".footer");
    // Titlebar + breathing room; too-tight budgets clip OK/Cancel on scaled monitors.
    let h = 36;
    const qMeasure = questionBlock || question;
    [chrome, qMeasure, refs, freeform, footer].forEach((el) => {
      if (el && !el.hidden) h += el.offsetHeight;
    });
    // Voice recover chrome can grow after mount — keep Cancel/OK on-screen.
    const voiceBar = document.getElementById("voice-bar");
    if (voiceBar && !voiceBar.hidden && footer && !footer.contains(voiceBar)) {
      h += voiceBar.offsetHeight;
    }
    if (banner && banner.classList.contains("is-on")) {
      h += banner.offsetHeight + 8;
    }
    // Gaps in .body + slack so the last option isn't flush with freeform.
    h += 56;
    let optsH = 0;
    if (options) {
      options.querySelectorAll(".option").forEach((o) => {
        optsH += o.offsetHeight + 8;
      });
      // Scroll options beyond this — keep freeform + footer on screen.
      h += Math.min(optsH, 480);
    }
    const w = Math.max(560, Math.min(760, window.outerWidth || 600));
    // Never ask the host for a window taller than the usable screen — laptop
    // / scaled monitors used to clip OK/Cancel under the taskbar.
    const avail = Math.max(
      420,
      Math.floor((window.screen && window.screen.availHeight) || 900) - 48,
    );
    apiCall("resize_to", w, Math.min(Math.ceil(h) + 8, avail)).catch(() => {});
  }

  function bridgeReady() {
    if (window.__ASK_BRIDGE__) return true;
    // pywebview sets api:{} early; methods appear only after finish.js _createApi.
    const api = window.pywebview && window.pywebview.api;
    return !!(api && typeof api.get_payload === "function");
  }

  async function boot() {
    const waitApi = () =>
      new Promise((resolve, reject) => {
        let settled = false;
        // Declare before done() — Linux __ASK_BRIDGE__ is ready immediately, so
        // tryNow→done runs before setInterval assigns iv (TDZ crash).
        let iv = null;
        const done = (ok, err) => {
          if (settled) return;
          settled = true;
          if (iv != null) clearInterval(iv);
          window.removeEventListener("pywebviewready", onReady);
          if (ok) resolve();
          else reject(err || new Error("dialog bridge unavailable (pywebview / Edge)"));
        };
        const tryNow = () => {
          if (bridgeReady()) {
            done(true);
            return true;
          }
          return false;
        };
        const onReady = () => tryNow();
        if (tryNow()) return;
        window.addEventListener("pywebviewready", onReady);
        let n = 0;
        iv = setInterval(() => {
          n += 1;
          if (tryNow()) return;
          // ~10s — WebView2 cold start under Cursor can be slow.
          if (n > 200) {
            done(false, new Error("dialog bridge unavailable (pywebview / Edge)"));
          }
        }, 50);
      });

    await waitApi();
    try {
      sessionStorage.removeItem("askq_boot_reloads");
    } catch (_) {
      /* ignore */
    }
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
    // Keep trying — a hard pink error page makes MCQs look "broken" when the
    // bridge was only a beat late. Reload once after a short pause.
    const msg = esc(String(err));
    let reloads = 0;
    try {
      reloads = Number(sessionStorage.getItem("askq_boot_reloads") || "0") || 0;
    } catch (_) {
      /* ignore */
    }
    if (reloads < 2) {
      try {
        sessionStorage.setItem("askq_boot_reloads", String(reloads + 1));
      } catch (_) {
        /* ignore */
      }
      document.body.innerHTML = `<pre style="color:#ff5c7a;padding:16px">${msg}\n\nRetrying…</pre>`;
      setTimeout(() => {
        try {
          location.reload();
        } catch (_) {
          /* ignore */
        }
      }, 400);
      return;
    }
    document.body.innerHTML = `<pre style="color:#ff5c7a;padding:16px">${msg}</pre>`;
  });
})();
