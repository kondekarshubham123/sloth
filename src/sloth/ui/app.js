/* Sloth UI — vanilla JS, no network, no build step. */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };

  const app = {
    status: null,
    plan: null,
    selected: new Set(),
    busy: false,
    lastRun: null,
    warning: "",
  };

  const BUCKETS = ["Documents", "Images", "Screenshots", "Audio", "Video", "Archives", "Code", "Finance", "Travel", "Health", "School", "Unsorted"];

  /* ---------- inline illustrations (no external assets) ---------- */
  const SLOTH_MARK = `
  <svg viewBox="0 0 64 64" aria-hidden="true">
    <g fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round">
      <path d="M7 15c14 5 36 5 50 0" opacity=".55"/>
      <path d="M22 18c-5 6-5 13 0 18"/><path d="M42 18c5 6 5 13 0 18"/>
      <path d="M19 17l-2-3M24 17l0-3M45 17l2-3M40 17l0-3" opacity=".7"/>
    </g>
    <g class="slothface">
      <ellipse cx="32" cy="40" rx="17" ry="15.5" fill="#fbf8ef" stroke="currentColor" stroke-width="1.7"/>
      <ellipse cx="25.5" cy="38.5" rx="5.6" ry="7" fill="currentColor" opacity=".85"/>
      <ellipse cx="38.5" cy="38.5" rx="5.6" ry="7" fill="currentColor" opacity=".85"/>
      <circle cx="26" cy="38" r="1.5" fill="#fbf8ef"/>
      <circle cx="39" cy="38" r="1.5" fill="#fbf8ef"/>
      <ellipse cx="32" cy="45" rx="3.4" ry="2.6" fill="currentColor"/>
      <path d="M28.5 49.5c2 1.8 5 1.8 7 0" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
    </g>
  </svg>`;

  const SLEEPY = `
  <svg viewBox="0 0 180 132" aria-hidden="true">
    <g fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" opacity=".65">
      <path d="M10 22c40 7 120 7 160 0"/>
      <path d="M142 22c6-5 12-5 16-1-4 6-11 7-16 1z" fill="currentColor" opacity=".18"/>
      <path d="M54 24c-8 8-8 18 0 25"/><path d="M114 24c8 8 8 18 0 25"/>
      <path d="M50 23l-2-4M57 23l0-4M111 23l-2-4M118 23l0-4" opacity=".8"/>
    </g>
    <g class="body">
      <ellipse cx="84" cy="71" rx="36" ry="28" fill="currentColor" opacity=".1"/>
      <ellipse cx="84" cy="71" rx="36" ry="28" fill="none" stroke="currentColor" stroke-width="1.8"/>
      <ellipse cx="73" cy="68" rx="9.5" ry="12" fill="currentColor" opacity=".78"/>
      <ellipse cx="95" cy="68" rx="9.5" ry="12" fill="currentColor" opacity=".78"/>
      <path d="M67 67q6 4.5 12 0" fill="none" stroke="#f1ecdf" stroke-width="1.7" stroke-linecap="round"/>
      <path d="M89 67q6 4.5 12 0" fill="none" stroke="#f1ecdf" stroke-width="1.7" stroke-linecap="round"/>
      <ellipse cx="84" cy="77.5" rx="4" ry="3" fill="currentColor"/>
      <path d="M79 84c3 2.8 7 2.8 10 0" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
      <path d="M114 96c6 2 14 2 20-2" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" opacity=".35"/>
    </g>
    <g fill="currentColor" font-family="Georgia, serif" font-style="italic" opacity=".55">
      <text class="z1" x="126" y="46" font-size="13">z</text>
      <text class="z2" x="136" y="34" font-size="10">z</text>
    </g>
  </svg>`;

  const LEAF_CHECK = `
  <svg viewBox="0 0 120 120" aria-hidden="true">
    <path d="M22 96C10 66 26 28 96 20c4 58-28 84-60 82" fill="currentColor" opacity=".08"/>
    <path d="M22 96C10 66 26 28 96 20c4 58-28 84-60 82" fill="none" stroke="currentColor" stroke-width="2"/>
    <path d="M22 96C40 70 60 52 90 34" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".4"/>
    <path d="M48 72l10 10 22-26" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;

  /* ---------- tiny markdown (for the local morning note) ---------- */
  const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function inline(s) {
    return esc(s)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/_([^_]+)_/g, "<em>$1</em>");
  }

  function miniMarkdown(md) {
    const out = [];
    let inList = false;
    const closeList = () => { if (inList) { out.push("</ul>"); inList = false; } };
    for (const raw of md.split(/\r?\n/)) {
      const line = raw.trimEnd();
      if (!line.trim()) { closeList(); continue; }
      if (line.startsWith("## ")) { closeList(); out.push("<h2>" + inline(line.slice(3)) + "</h2>"); }
      else if (line.startsWith("# ")) { closeList(); out.push("<h1>" + inline(line.slice(2)) + "</h1>"); }
      else if (line.startsWith("> ")) { closeList(); out.push("<blockquote>" + inline(line.slice(2)) + "</blockquote>"); }
      else if (line.startsWith("- ")) {
        if (!inList) { out.push("<ul>"); inList = true; }
        out.push("<li>" + inline(line.slice(2)) + "</li>");
      } else { closeList(); out.push("<p>" + inline(line) + "</p>"); }
    }
    closeList();
    return out.join("");
  }

  /* ---------- status / posture ---------- */
  function shortModel(name) {
    const base = (name || "").replace(/\.gguf$/i, "");
    const m = base.match(/([a-z0-9.]+?-\d+(?:\.\d+)?b)/i);
    const quant = base.match(/(q\d+_k_[ms]|q\d+_\d+|q\d+_k)/i);
    const family = m ? m[1] : base;
    return family + (quant ? " · " + quant[1] : "");
  }

  function renderStatus(status) {
    app.status = status;
    const pill = $("#modelpill");
    pill.textContent = shortModel(status.model) + " · " + status.backend.toLowerCase();
    pill.title = status.model + " · " + status.model_gb + " GB · sha256 " + status.sha;

    const ag = $("#airgap");
    const on = status.netguard && status.netguard.active;
    ag.classList.toggle("off", !on);
    ag.title = on
      ? "Outbound connections are blocked in this process. Only localhost is allowed."
      : "Airgap is off";
    ag.innerHTML = '<span class="dot"></span> ' + (on ? "offline by design" : "airgap off");

    const dl = $("#posture");
    dl.replaceChildren();
    const rows = [
      ["model", status.model, status.model_path],
      ["size", status.model_gb + " GB · " + status.sha, "sha256 (short)"],
      ["engine", status.engine + " · " + status.backend, status.engine_path],
      ["endpoint", status.endpoint.replace("http://", ""), "loopback only"],
      ["airgap", on ? "on · " + (status.netguard.blocked || 0) + " blocked" : "off", "socket-level guard"],
      ["kept in", (status.settings && status.settings.home) || "~/.sloth", "plans, runs, notes"],
    ];
    for (const [k, v, title] of rows) {
      const div = el("div");
      div.append(el("dt", "", k));
      const dd = el("dd", "", v || "—");
      if (title) dd.title = title;
      div.append(dd);
      dl.append(div);
    }
  }

  function renderState(data) {
    if (data.status) renderStatus(data.status);

    const briefing = $("#briefing");
    if (data.briefing && data.briefing.text) {
      briefing.classList.remove("empty");
      briefing.innerHTML = miniMarkdown(data.briefing.text);
    } else {
      briefing.classList.add("empty");
      briefing.textContent = "Your first quiet pass will leave a note here.";
    }

    const runs = $("#runs");
    runs.replaceChildren();
    if (!data.runs || !data.runs.length) {
      runs.className = "runlist empty";
      runs.textContent = "No files moved yet. Good things take time.";
      return;
    }
    runs.className = "runlist";
    for (const run of data.runs) {
      const row = el("div", "run" + (run.undone ? " undone" : ""));
      const left = el("div");
      left.append(el("div", "when", run.undone ? run.moved + " files · undone" : run.moved + " files tucked in"));
      if (run.note) {
        const note = el("div", "tiny", run.note);
        note.style.color = "var(--ink-faint)";
        note.style.marginTop = "3px";
        left.append(note);
      }
      const right = el("div", "meta", new Date(run.at).toLocaleString([], {
        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
      }));
      if (!run.undone) {
        const btn = el("button", "undo-one", "undo");
        btn.type = "button";
        btn.addEventListener("click", () => doUndo(run.id));
        right.append(btn);
      }
      row.append(left, right);
      runs.append(row);
    }
  }

  async function refresh() {
    try {
      const res = await fetch("/api/state?t=" + Date.now(), { cache: "no-store" });
      renderState(await res.json());
    } catch (e) {
      console.warn("state refresh failed", e);
    }
  }

  /* ---------- toast ---------- */
  let toastTimer = null;
  function toast(message, isError = false) {
    const t = $("#toast");
    t.textContent = message;
    t.classList.toggle("error", isError);
    t.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.add("hidden"), isError ? 9000 : 4200);
  }

  /* ---------- scanning ---------- */
  function show(node, yes) { node.classList.toggle("hidden", !yes); }

  function resetToHero() {
    show($("#plan"), false);
    show($("#receipt"), false);
    show($("#scanning"), false);
    app.plan = null;
    app.selected.clear();
  }

  function resetScanUI(path) {
    app.warning = "";
    show($("#plan"), false);
    show($("#receipt"), false);
    show($("#scanning"), true);
    $("#stage").textContent = "Waking the sloth…";
    $("#stage").classList.remove("error");
    $("#progress").textContent = "0 / 0";
    $("#barfill").style.width = "3%";
    $("#chips").replaceChildren();
    $("#scanbtn").disabled = true;
    $("#path").value = path;
    $("#scanning").scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function addChips(names) {
    const wrap = $("#chips");
    for (const name of names || []) {
      const chip = el("span", "chip", name);
      chip.title = name;
      wrap.append(chip);
    }
    while (wrap.children.length > 5) wrap.firstChild.remove();
  }

  function handleEvent(evt) {
    if (evt.stage === "error") {
      $("#stage").textContent = "The sloth got stuck.";
      $("#stage").classList.add("error");
      $("#pace").textContent = "nothing was moved";
      $("#scanbtn").disabled = false;
      toast(evt.message || "Something went wrong.", true);
      return;
    }
    if (evt.stage === "warn") {
      app.warning = evt.message || "";
      return;
    }
    if (evt.stage === "sort") {
      $("#stage").textContent = evt.message;
      addChips(evt.names);
      if (evt.total) {
        $("#barfill").style.width = Math.max(4, (evt.done / evt.total) * 100) + "%";
      }
      return;
    }
    if (evt.stage === "progress" && evt.total) {
      $("#progress").textContent = evt.done + " / " + evt.total;
      $("#barfill").style.width = Math.max(4, (evt.done / evt.total) * 100) + "%";
      return;
    }
    if (evt.stage === "wake" || evt.stage === "scan" || evt.stage === "read") {
      $("#stage").textContent = evt.message;
      if (evt.total) $("#progress").textContent = "0 / " + evt.total;
      return;
    }
    if (evt.stage === "done") {
      $("#barfill").style.width = "100%";
      renderPlan(evt.plan);
    }
  }

  async function scan(event) {
    event.preventDefault();
    if (app.busy) return;
    const path = $("#path").value.trim();
    if (!path) { $("#path").focus(); return; }

    app.busy = true;
    resetScanUI(path);
    try {
      const res = await fetch("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, limit: 60 }),
      });
      if (!res.ok || !res.body) throw new Error("Scan request failed (" + res.status + ")");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finished = false;

      while (!finished) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          try { handleEvent(JSON.parse(line)); } catch (e) { console.warn("bad event", line); }
        }
        finished = $("#stage").classList.contains("error");
      }
    } catch (e) {
      $("#stage").textContent = "Could not reach the local sloth.";
      $("#stage").classList.add("error");
      toast(String(e.message || e), true);
    } finally {
      app.busy = false;
      $("#scanbtn").disabled = false;
      $("#pace").textContent = "reading slowly is the point";
      if (app.plan) updateCounts();
      refresh();
    }
  }

  /* ---------- plan ---------- */
  function renderPlan(plan) {
    app.plan = plan;
    app.selected = new Set(plan.files.filter((f) => !f.flagged).map((f) => f.id));

    show($("#scanning"), false);
    show($("#receipt"), false);
    show($("#plan"), true);

    $("#note").textContent = plan.note || "A plan is ready.";
    const when = new Date(plan.created).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const modelLabel = plan.model_used
      ? shortModel(plan.model && plan.model.model)
      : "careful rules (no model)";
    const meta = $("#planmeta");
    meta.replaceChildren();
    meta.append(document.createTextNode(plan.root + "  ·  " + modelLabel + "  ·  " + when));
    $("#stampnum").textContent = plan.stats.files;

    const sure = $("#sureness");
    sure.replaceChildren();
    if (plan.stats.flagged) {
      const b = el("b", "", plan.stats.flagged + " need a look");
      sure.append(b, document.createTextNode(" — they start unticked, so you can keep the maybe pile messy."));
    } else {
      sure.append(document.createTextNode("Every file looks straightforward. You still approve each move."));
    }
    if (!plan.model_used) {
      sure.append(document.createTextNode(" "));
      const warn = el("span", "", "No local model was found; these are careful rules.");
      warn.style.color = "var(--clay)";
      sure.append(warn);
    }
    if (app.warning) {
      sure.append(document.createTextNode(" "));
      sure.append(el("span", "tiny", app.warning));
    }

    const groups = $("#groups");
    groups.replaceChildren();
    let delay = 0;
    for (const bucket of BUCKETS) {
      const files = plan.files.filter((f) => f.bucket === bucket);
      if (!files.length) continue;
      groups.append(buildGroup(bucket, files, delay));
      delay += 0.05;
    }

    updateCounts();
    const top = $("#plan").getBoundingClientRect().top + window.scrollY - 24;
    window.scrollTo({ top, behavior: "smooth" });
  }

  function buildGroup(bucket, files, delay) {
    const group = el("section", "group");
    group.style.animationDelay = delay + "s";

    const head = el("div", "grouphead");
    const box = el("input");
    box.type = "checkbox";
    box.setAttribute("aria-label", "Select all " + bucket + " files");
    head.append(box);
    head.append(el("span", "gname", bucket));
    head.append(el("span", "gcount", String(files.length)));
    head.append(el("span", "gspacer"));

    const all = el("button", "gall", "select pile");
    all.type = "button";
    head.append(all);

    const rows = el("div", "rows");
    const boxes = [];
    for (const f of files) {
      const row = el("label", "row" + (f.flagged ? " flagged" : ""));
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = app.selected.has(f.id);
      cb.dataset.id = f.id;
      cb.setAttribute("aria-label", "Move " + f.name + " to " + bucket + " as " + f.new_name);
      cb.addEventListener("change", () => {
        if (cb.checked) app.selected.add(f.id);
        else app.selected.delete(f.id);
        row.classList.toggle("unchecked", !cb.checked);
        syncGroupBox();
        updateCounts();
      });
      boxes.push(cb);

      const names = el("div", "names" + (f.name === f.new_name ? " same" : ""));
      const nn = el("span", "newname", f.new_name);
      nn.title = f.new_name;
      names.append(nn);
      if (f.name !== f.new_name) {
        const on = el("span", "oldname", f.name);
        on.title = "was " + f.name;
        names.append(on);
      }

      const why = el("span", "why", f.why || "no reason given");
      why.title = f.why || "";

      const conf = el("span", "conf" + (f.confidence < 0.55 ? " low" : ""));
      conf.append(el("i"));
      conf.append(document.createTextNode(Math.round(f.confidence * 100) + "%"));
      conf.title = f.source === "model" ? "model confidence" : "rule-of-thumb confidence";

      row.append(cb, names, why, conf);
      if (!cb.checked) row.classList.add("unchecked");
      rows.append(row);
    }

    const syncGroupBox = () => {
      const on = boxes.filter((b) => b.checked).length;
      box.checked = on === boxes.length;
      box.indeterminate = on > 0 && on < boxes.length;
      all.textContent = on === boxes.length ? "clear pile" : "select pile";
    };
    syncGroupBox();

    box.addEventListener("change", () => {
      for (const cb of boxes) {
        cb.checked = box.checked;
        if (cb.checked) app.selected.add(cb.dataset.id);
        else app.selected.delete(cb.dataset.id);
        cb.closest(".row").classList.toggle("unchecked", !cb.checked);
      }
      box.indeterminate = false;
      updateCounts();
    });

    all.addEventListener("click", () => {
      box.checked = !boxes.every((b) => b.checked);
      box.dispatchEvent(new Event("change"));
    });

    group.append(head, rows);
    return group;
  }

  function updateCounts() {
    const total = app.plan ? app.plan.files.length : 0;
    const n = app.selected.size;
    $("#selcount").textContent = String(n);
    $("#totalcount").textContent = String(total);
    const countChip = $("#applycount");
    if (countChip) countChip.textContent = n ? "(" + n + ")" : "";
    $("#apply").disabled = n === 0 || app.busy;
    const flagged = app.plan ? app.plan.files.filter((f) => f.flagged).length : 0;
    if (flagged && n === total - flagged) {
      $("#sureness").dataset.state = "safe";
    }
  }

  /* ---------- apply / undo ---------- */
  async function apply() {
    if (!app.plan || !app.selected.size || app.busy) return;
    app.busy = true;
    $("#apply").disabled = true;
    $("#applylabel").textContent = "Tucking in…";
    try {
      const res = await fetch("/api/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_id: app.plan.id, ids: [...app.selected] }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not apply the plan");
      if (!data.moved) {
        toast("Nothing moved — the files may have changed since the plan.", true);
        return;
      }
      app.lastRun = data.run;
      show($("#plan"), false);
      show($("#receipt"), true);
      $("#receipttitle").textContent = data.moved + " files, quietly tucked away.";
      $("#receiptsub").replaceChildren();
      $("#receiptsub").append(document.createTextNode(
        "Into Sloth Sorted/ inside " + (app.plan.root || "the folder") + ". A morning note was written."
      ));
      $("#undo").textContent = "Put all " + data.moved + " back";
      $("#receipt").scrollIntoView({ behavior: "smooth", block: "center" });
      toast("Done. Nothing left this laptop.");
      refresh();
    } catch (e) {
      toast(String(e.message || e), true);
    } finally {
      app.busy = false;
      $("#applylabel").textContent = "Tuck away";
      updateCounts();
    }
  }

  async function doUndo(runId) {
    try {
      const res = await fetch("/api/undo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId || "last" }),
      });
      const data = await res.json();
      if (data.error) { toast(data.error, true); return; }
      toast("Put " + data.restored + " files back where they were.");
      show($("#receipt"), false);
      show($("#plan"), false);
      app.lastRun = null;
      refresh();
    } catch (e) {
      toast(String(e.message || e), true);
    }
  }

  /* ---------- boot ---------- */
  $("#brandmark").innerHTML = SLOTH_MARK;
  $("#sleepy").innerHTML = SLEEPY;
  $("#receiptmark").innerHTML = LEAF_CHECK;

  $("#scanform").addEventListener("submit", scan);
  $("#usedemo").addEventListener("click", () => {
    if (app.status && app.status.settings) $("#path").value = app.status.settings.demo_root;
    $("#path").focus();
  });
  $("#path").addEventListener("keydown", (e) => { if (e.key === "Enter") scan(e); });
  $("#apply").addEventListener("click", apply);
  $("#undo").addEventListener("click", () => doUndo(app.lastRun ? app.lastRun.id : "last"));
  $("#discard").addEventListener("click", () => {
    resetToHero();
    window.scrollTo({ top: 0, behavior: "smooth" });
    toast("Left everything exactly where it was.");
  });
  $("#another").addEventListener("click", () => {
    resetToHero();
    $("#path").focus();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  fetch("/api/status?t=" + Date.now(), { cache: "no-store" })
    .then((r) => r.json())
    .then((status) => {
      renderStatus(status);
      if (status.settings) {
        $("#path").value = status.settings.demo_root;
        $("#path").title = status.settings.demo_root;
      }
    })
    .catch(() => toast("The local backend is not answering.", true))
    .finally(refresh);
})();
