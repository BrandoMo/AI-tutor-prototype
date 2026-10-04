// Teacher dashboard. Uses api() and $() from script.js, which loads first.
// All text goes in via textContent, never innerHTML.

let classes = [];
let selectedClass = null; // join code of the class being shown

// Small DOM helper: el("span", "badge", "Locked")
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function timeAgo(seconds) {
  if (!seconds) return "Not started";
  const mins = Math.floor((Date.now() / 1000 - seconds) / 60);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "Yesterday" : `${days} days ago`;
}

function setNote(id, text, kind = "") {
  $(id).textContent = text;
  $(id).className = `result ${kind}`;
  $(id).hidden = !text;
}

// --- Class list ---

async function startTeacher() {
  const { ok, data } = await api("/classes");
  if (!ok) return;
  classes = data.classes;
  if (!classes.some((c) => c.code === selectedClass)) {
    selectedClass = classes.length ? classes[0].code : null;
  }
  renderClassTabs();
  if (selectedClass) loadClass(selectedClass);
  else $("class-card").hidden = true;
}

function renderClassTabs() {
  const tabs = $("class-tabs");
  tabs.replaceChildren();
  for (const c of classes) {
    const tab = el("button", "class-tab");
    tab.type = "button";
    tab.setAttribute("aria-pressed", String(c.code === selectedClass));
    tab.append(el("span", "", c.name), el("span", "count", String(c.students)));
    tab.addEventListener("click", () => {
      selectedClass = c.code;
      renderClassTabs();
      loadClass(c.code);
    });
    tabs.appendChild(tab);
  }
  $("no-classes").hidden = classes.length > 0;
}

$("new-class-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("new-class-name").value.trim();
  if (!name) return;
  const { ok, data } = await api("/classes", { name });
  if (!ok) {
    setNote("new-class-result", data.detail || "Could not create the class.", "bad");
    return;
  }
  $("new-class-name").value = "";
  setNote("new-class-result", `Made "${data.name}". Students join with ${data.code}.`, "good");
  selectedClass = data.code;
  startTeacher();
});

// --- One class ---

async function loadClass(code) {
  const { ok, data } = await api(`/classes/${encodeURIComponent(code)}`);
  if (!ok) return;
  $("class-card").hidden = false;
  $("class-name").textContent = data.name;
  $("class-code").textContent = data.code;
  $("copy-code").textContent = "Copy";
  renderTiles(data.summary);
  renderMistakes(data.summary);
  renderStudents(data.students, data.code);
}

$("refresh-class").addEventListener("click", () => startTeacher());

$("copy-code").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("class-code").textContent);
    $("copy-code").textContent = "Copied!";
  } catch (e) {
    $("copy-code").textContent = "Copy it by hand";
  }
});

function renderTiles(summary) {
  const tiles = $("tiles");
  tiles.replaceChildren();
  for (const [value, label] of [
    [summary.students, "students"],
    [summary.practising, "have practised"],
    [summary.mastered, "mastered"],
  ]) {
    const tile = el("div", "tile");
    tile.append(el("span", "tile-value", String(value)), el("span", "tile-label", label));
    tiles.appendChild(tile);
  }
}

// One bar per misconception: how many students in the class have made it
function renderMistakes(summary) {
  const list = $("mistake-bars");
  list.replaceChildren();
  for (const m of summary.mistakes) {
    const share = summary.students ? m.students / summary.students : 0;
    const item = el("li", "bar-row");
    item.title = `${m.students} of ${summary.students} students, ${m.times} time${m.times === 1 ? "" : "s"} in total`;
    const head = el("div", "bar-head");
    head.append(el("span", "bar-label", m.label),
                el("span", "bar-value", `${m.students} of ${summary.students} student${summary.students === 1 ? "" : "s"}`));
    const track = el("div", "bar-track");
    const fill = el("div", "bar-fill");
    fill.style.width = `${Math.max(share * 100, 2)}%`;
    track.appendChild(fill);
    item.append(head, track);
    list.appendChild(item);
  }
  $("no-mistakes").hidden = summary.mistakes.length > 0;
}

function renderStudents(students, code) {
  const list = $("student-list");
  list.replaceChildren();
  for (const s of students) {
    const row = el("li", "student");

    const who = el("div", "student-who");
    const avatar = el("span", "user-avatar", s.username[0].toUpperCase());
    avatar.setAttribute("aria-hidden", "true");
    const name = el("div", "student-name");
    name.appendChild(el("strong", "", s.username));
    if (s.mastered) name.appendChild(el("span", "badge-text", "★ Mastered"));
    if (s.locked) name.appendChild(el("span", "badge-text locked", "🔒 Locked"));
    name.appendChild(el("span", "student-when", timeAgo(s.last_active)));
    who.append(avatar, name);

    const stats = el("div", "student-stats");
    stats.append(
      el("span", "", `${s.solved} solved`),
      el("span", "", `Streak ${s.streak}`),
      el("span", "", s.top_mistake ? `Most often: ${s.top_mistake}` : "No mistakes yet"),
    );

    const actions = el("div", "student-actions");
    const reset = el("button", "link", "Reset password");
    reset.type = "button";
    reset.addEventListener("click", () => issueResetCode(code, s.username, row));
    actions.appendChild(reset);
    if (s.locked) {
      const unlock = el("button", "link", "Unlock");
      unlock.type = "button";
      unlock.addEventListener("click", async () => {
        const { ok } = await api(`/classes/${encodeURIComponent(code)}/students/${encodeURIComponent(s.username)}/unlock`, {});
        if (ok) loadClass(code);
      });
      actions.appendChild(unlock);
    }
    const remove = el("button", "link", "Remove");
    remove.type = "button";
    remove.addEventListener("click", async () => {
      if (!confirm(`Remove ${s.username} from this class? Their progress is kept.`)) return;
      const { ok } = await api(`/classes/${encodeURIComponent(code)}/students/${encodeURIComponent(s.username)}`, undefined, "DELETE");
      if (ok) startTeacher();
    });
    actions.appendChild(remove);

    row.append(who, stats, actions);
    list.appendChild(row);
  }
  $("no-students").hidden = students.length > 0;
}

async function issueResetCode(code, username, row) {
  const { ok, data } = await api(`/classes/${encodeURIComponent(code)}/students/${encodeURIComponent(username)}/reset-code`, {});
  row.querySelector(".reset-note")?.remove();
  const note = el("p", "result reset-note");
  if (!ok) {
    note.textContent = data.detail || "Could not make a reset code.";
    note.classList.add("bad");
  } else {
    note.append(
      "Give this code to ", el("strong", "", data.username), ": ",
      el("strong", "reset-code", data.code),
      ` It works once, for ${data.expires_in_hours} hours. They choose "Forgot your password?" on the sign-in screen.`,
    );
  }
  row.appendChild(note);
}
