const concept = "equivalent_fractions";
let currentProblem = null;

const $ = (id) => document.getElementById(id);

// --- Talking to the server ---

// JSON request helper: GET with no body, POST with one (or pass a method).
// The session cookie rides along automatically; a 401 means the session
// has ended, so go back to the sign-in screen.
async function api(path, body, method) {
  const options = { method: method || (body === undefined ? "GET" : "POST") };
  if (body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, options);
  } catch (err) {
    return { ok: false, status: 0, data: { detail: "Network error — check your connection and try again." } };
  }
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && path !== "/login" && path !== "/me") {
    showAuth("You've been signed out — please sign in again.");
  }
  // FastAPI validation errors come back as a list; show something readable
  if (Array.isArray(data.detail)) data.detail = "Please check what you typed and try again.";
  return { ok: res.ok, status: res.status, data };
}

// --- Colour theme ---

const PALETTES = ["sunny", "neon", "ocean", "berry"];

function applyPalette(name) {
  if (!PALETTES.includes(name)) name = "sunny";
  document.documentElement.dataset.palette = name;
  document.querySelector(`input[name="palette"][value="${name}"]`).checked = true;
  try { localStorage.setItem("palette", name); } catch (e) {} // nice-to-have only
}

document.querySelectorAll('input[name="palette"]').forEach((radio) => {
  radio.addEventListener("change", () => applyPalette(radio.value));
});
applyPalette(document.documentElement.dataset.palette);

// --- Signing in ---

let me = null;          // {username, role, class} for whoever is signed in
let authMode = "login"; // "login", "register" or "reset"
let practiceStarted = false;

function setAuthMode(mode) {
  authMode = mode;
  const registering = mode === "register";
  const resetting = mode === "reset";
  $("mode-login").setAttribute("aria-pressed", String(mode === "login"));
  $("mode-register").setAttribute("aria-pressed", String(registering));
  $("auth-title").textContent =
    resetting ? "Choose a new password" : registering ? "Make your account" : "Welcome back!";
  $("auth-submit").textContent =
    resetting ? "Save new password" : registering ? "Create account" : "Sign in";
  $("password-label").textContent = resetting ? "New password" : "Password";
  $("password").autocomplete = mode === "login" ? "current-password" : "new-password";
  $("reset-code-field").hidden = !resetting;
  $("teacher-fields").hidden = !registering;
  $("auth-hint").hidden = mode === "login";
  $("auth-hint").textContent = resetting
    ? "Your new password needs at least 8 characters."
    : "3-20 letters, numbers or underscores. Password: at least 8 characters.";
  $("forgot-link").hidden = mode !== "login";
  $("back-to-signin").hidden = !resetting;
  setAuthError("");
}

function setAuthError(text) {
  $("auth-error").textContent = text;
  $("auth-error").hidden = !text;
}

function showAuth(message = "") {
  me = null;
  currentProblem = null;
  practiceStarted = false;
  for (const id of ["app-main", "teacher-main", "user-area", "view-toggle"]) $(id).hidden = true;
  $("auth-card").hidden = false;
  $("password").value = "";
  setAuthError(message);
  $("username").focus();
}

function renderClassChip() {
  const cls = me && me.class;
  $("class-chip").textContent = cls ? cls.name : "";
  $("class-chip").hidden = !cls;
}

function startApp(meData) {
  me = meData;
  $("auth-card").hidden = true;
  $("user-area").hidden = false;
  $("user-name").textContent = me.username;
  $("user-avatar").textContent = me.username[0].toUpperCase();
  renderClassChip();

  const teacher = me.role === "teacher";
  $("view-toggle").hidden = !teacher;
  let dismissed = false;
  try { dismissed = sessionStorage.getItem("join-later") === "1"; } catch (e) {}
  $("join-card").hidden = teacher || Boolean(me.class) || dismissed;
  showView(teacher ? "dashboard" : "practice");
}

// Teachers can switch between their dashboard and trying the practice
function showView(view) {
  const dashboard = view === "dashboard";
  $("teacher-main").hidden = !dashboard;
  $("app-main").hidden = dashboard;
  $("view-dashboard").setAttribute("aria-pressed", String(dashboard));
  $("view-practice").setAttribute("aria-pressed", String(!dashboard));
  if (dashboard) {
    startTeacher(); // teacher.js
  } else if (!practiceStarted) {
    practiceStarted = true;
    $("chat").replaceChildren();
    addMessage("tutor", `Hi ${me.username}! Have a go at the problem above, or ask me anything about equivalent fractions.`);
    loadProblem();
  }
}

$("mode-login").addEventListener("click", () => setAuthMode("login"));
$("mode-register").addEventListener("click", () => setAuthMode("register"));
$("forgot-link").addEventListener("click", () => setAuthMode("reset"));
$("back-to-signin").addEventListener("click", () => setAuthMode("login"));
$("is-teacher").addEventListener("change", () => {
  $("teacher-code-field").hidden = !$("is-teacher").checked;
});
$("view-dashboard").addEventListener("click", () => showView("dashboard"));
$("view-practice").addEventListener("click", () => showView("practice"));

$("auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = $("username").value.trim();
  const password = $("password").value;
  if (!username || !password) {
    setAuthError("Please enter a username and password.");
    return;
  }

  let path, body;
  if (authMode === "reset") {
    const code = $("reset-code").value.trim();
    if (!code) {
      setAuthError("Please enter the reset code from your teacher.");
      return;
    }
    path = "/reset-password";
    body = { username, code, new_password: password };
  } else if (authMode === "register") {
    path = "/register";
    body = { username, password };
    if ($("is-teacher").checked) body.teacher_code = $("teacher-code").value;
  } else {
    path = "/login";
    body = { username, password };
  }

  $("auth-submit").disabled = true;
  const { ok, data } = await api(path, body);
  $("auth-submit").disabled = false;
  if (!ok) {
    setAuthError(data.detail || "Something went wrong — please try again.");
    return;
  }
  $("password").value = "";
  $("reset-code").value = "";
  $("teacher-code").value = "";
  setAuthMode("login");
  startApp(data);
});

$("sign-out").addEventListener("click", async () => {
  await api("/logout", {});
  showAuth();
});

// --- Joining a class (students) ---

$("join-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const code = $("join-code").value.trim();
  if (!code) return;
  const { ok, data } = await api("/join", { code });
  const result = $("join-result");
  result.hidden = false;
  if (!ok) {
    result.textContent = data.detail || "Could not join — try again.";
    result.className = "result bad";
    return;
  }
  me.class = data.class;
  renderClassChip();
  $("join-card").hidden = true;
  addMessage("note", `You joined ${data.class.name}.`);
});

$("join-later").addEventListener("click", () => {
  $("join-card").hidden = true;
  try { sessionStorage.setItem("join-later", "1"); } catch (e) {}
});

// --- Chat ---

// role is "me", "tutor" or "note" (for errors and status messages)
function addMessage(role, text) {
  const row = document.createElement("div");
  row.className = `msg ${role}`;
  if (role === "tutor") {
    const avatar = document.createElement("span");
    avatar.className = "avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = "AI";
    row.appendChild(avatar);
  }
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  // Tutor replies get safe Markdown formatting (see markdown.js); everything
  // else is plain text. Never innerHTML: LLM output is untrusted.
  if (role === "tutor") renderMarkdown(bubble, text);
  else bubble.textContent = text;
  row.appendChild(bubble);

  const chat = $("chat");
  chat.appendChild(row);
  chat.scrollTop = chat.scrollHeight;
  return row;
}

function showTyping() {
  const row = addMessage("tutor", "");
  row.classList.add("typing");
  const bubble = row.querySelector(".bubble");
  bubble.setAttribute("aria-label", "Tutor is typing");
  bubble.innerHTML = "<span></span><span></span><span></span>";
  return row;
}

// Sends text to the tutor and shows its explanation in the chat
async function askTutor(question) {
  const typing = showTyping();
  const { ok, data } = await api("/ask", { concept: concept, question: question });
  typing.remove();
  if (!ok) {
    addMessage("note", `Tutor error: ${data.detail || "server error"}. Try again.`);
    return;
  }
  addMessage("tutor", data.explanation);
}

$("ask-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("question");
  const question = input.value.trim();
  if (!question) return;
  addMessage("me", question);
  input.value = "";
  await askTutor(question);
});

// --- Practice problem ---

function setResult(text, kind = "") {
  const el = $("result");
  el.textContent = text;
  el.className = `result ${kind}`;
  el.hidden = !text;
}

function setAnswerEnabled(enabled) {
  document.querySelectorAll("#fraction-form input, #fraction-form button, #yesno-buttons button")
    .forEach((el) => { el.disabled = !enabled; });
}

// Draws a fraction like "2/3" as a pie with that many slices shaded
function drawPie(fraction) {
  const pie = $("pie");
  const chart = $("pie-chart");
  chart.replaceChildren();
  const match = /^(\d+)\/(\d+)$/.exec(fraction || "");
  const n = match ? Number(match[1]) : 0;
  const d = match ? Number(match[2]) : 0;
  if (!match || d < 1 || d > 24 || n > d) {
    pie.hidden = true;
    return;
  }

  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "-1.1 -1.1 2.2 2.2");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${n} out of ${d} equal parts shaded`);
  for (let i = 0; i < d; i++) {
    let slice;
    if (d === 1) {
      slice = document.createElementNS(ns, "circle");
      slice.setAttribute("r", "1");
    } else {
      // Angles start at 12 o'clock and go clockwise
      const a0 = (i / d) * 2 * Math.PI - Math.PI / 2;
      const a1 = ((i + 1) / d) * 2 * Math.PI - Math.PI / 2;
      const largeArc = a1 - a0 > Math.PI ? 1 : 0;
      slice = document.createElementNS(ns, "path");
      slice.setAttribute("d",
        `M0 0 L${Math.cos(a0)} ${Math.sin(a0)} A1 1 0 ${largeArc} 1 ${Math.cos(a1)} ${Math.sin(a1)} Z`);
    }
    slice.setAttribute("class", i < n ? "slice filled" : "slice");
    svg.appendChild(slice);
  }
  chart.appendChild(svg);
  $("pie-label").textContent = fraction;
  pie.hidden = false;
}

// Solved count, plus one dot per answer in the current right-first-time streak
function renderProgress(progress) {
  $("solved-count").textContent = progress.solved;
  const filled = Math.min(progress.streak, progress.streak_goal);
  const dots = $("dots");
  dots.replaceChildren();
  for (let i = 0; i < progress.streak_goal; i++) {
    const dot = document.createElement("span");
    dot.className = i < filled ? "dot done" : "dot";
    dots.appendChild(dot);
  }
  $("mastery").classList.toggle("mastered", progress.mastered);
  $("mastery-label").textContent = progress.mastered ? "★ Mastered" : "Streak";
  $("mastery").setAttribute("aria-label",
    `${progress.mastered ? "Mastered. " : ""}Streak: ${filled} of ${progress.streak_goal} right first time`);
}

// A burst of little circles from the given element
function celebrate(fromEl, count = 18) {
  const box = fromEl.getBoundingClientRect();
  const colors = ["--primary", "--accent", "--good", "--decor-1", "--decor-2", "--decor-3"];
  for (let i = 0; i < count; i++) {
    const dot = document.createElement("span");
    dot.className = "confetti";
    const angle = (i / count) * 2 * Math.PI;
    const distance = 70 + Math.random() * (count > 18 ? 140 : 60);
    dot.style.left = `${box.left + box.width / 2 - 7}px`;
    dot.style.top = `${box.top + box.height / 2 - 7}px`;
    dot.style.background = `var(${colors[i % colors.length]})`;
    dot.style.setProperty("--dx", `${Math.cos(angle) * distance}px`);
    dot.style.setProperty("--dy", `${Math.sin(angle) * distance}px`);
    document.body.appendChild(dot);
    dot.addEventListener("animationend", () => dot.remove());
  }
}

async function loadProblem() {
  setResult("");
  $("next-problem").hidden = true;

  const { ok, data } = await api(`/problem?concept=${encodeURIComponent(concept)}`);
  if (!ok) {
    $("problem").textContent = `Could not load a problem — ${data.detail || "server error"}`;
    return;
  }

  currentProblem = data;
  $("problem").textContent = data.prompt;
  drawPie(data.given);
  renderProgress(data.progress);
  $("focus").textContent = data.focus ? `Practising: ${data.focus}` : "";
  $("focus").hidden = !data.focus;

  const yesNo = data.answer_format === "yes_no";
  $("fraction-form").hidden = yesNo;
  $("yesno-buttons").hidden = !yesNo;
  $("answer").value = "";
  setAnswerEnabled(true);
  if (!yesNo) $("answer").focus();

  if (data.try > 1) setResult("Second try at this one.");
}

async function submitAnswer(answer, fromEl) {
  if (!answer || !currentProblem) return;

  // Lock input while checking so it can't be double-submitted
  setAnswerEnabled(false);
  const { ok, status, data } = await api("/answer", {
    concept: concept,
    problem_id: currentProblem.id,
    answer: answer
  });
  if (status === 401) return; // back on the sign-in screen
  if (!ok) {
    // e.g. "Please answer with a fraction like 3/4." -- let them fix it
    setResult(data.detail || "Could not check your answer — server error.", status === 400 ? "" : "bad");
    setAnswerEnabled(true);
    return;
  }

  renderProgress(data.progress);

  if (data.correct) {
    if (data.just_mastered) {
      setResult(`Correct! That's ${data.progress.streak_goal} right first time in a row — you've mastered equivalent fractions! ★`, "good");
      celebrate(fromEl, 36);
    } else {
      setResult(data.try > 1 ? "Correct on your second try!" : "Correct!", "good");
      celebrate(fromEl);
    }
    $("next-problem").hidden = false;
    $("next-problem").focus();
    return;
  }

  if (data.finished) {
    // Out of tries: reveal the answer and have the tutor walk through it
    setResult(`Not quite. The answer was ${data.correct_answer}.`, "bad");
    $("next-problem").hidden = false;
    addMessage("me", `My answer: ${answer}`);
    await askTutor(`I answered "${answer}" to the problem "${currentProblem.prompt}" and got it wrong again. The answer is ${data.correct_answer}. Can you walk me through it?`);
    return;
  }

  // First wrong try: give a hint (from the grader if it can explain the
  // mistake itself, otherwise from the tutor), then let them retry
  setResult(data.feedback ? `${data.feedback} Try again.` : "Not quite — read the tutor's hint, then try again.", "bad");
  if (!data.feedback) {
    addMessage("me", `My answer: ${answer}`);
    await askTutor(`I answered "${answer}" to the problem "${currentProblem.prompt}" and got it wrong. Can I have a hint?`);
  }
  $("answer").value = "";
  setAnswerEnabled(true);
  if (currentProblem.answer_format !== "yes_no") $("answer").focus();
}

$("fraction-form").addEventListener("submit", (e) => {
  e.preventDefault();
  submitAnswer($("answer").value.trim(), $("submit-answer"));
});
document.querySelectorAll("#yesno-buttons button").forEach((button) => {
  button.addEventListener("click", () => submitAnswer(button.dataset.answer, button));
});
$("next-problem").addEventListener("click", loadProblem);

// --- Start: signed in already? ---

// Runs after every script has loaded (teacher.js comes after this file)
document.addEventListener("DOMContentLoaded", async () => {
  const { ok, data } = await api("/me");
  if (ok) startApp(data);
  else showAuth(data.detail && data.detail.startsWith("Network") ? data.detail : "");
});
