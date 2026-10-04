const concept = "equivalent_fractions";
let currentProblem = null;

const $ = (id) => document.getElementById(id);

// --- Talking to the server ---

// JSON request helper. The session cookie rides along automatically; a 401
// means the session has ended, so go back to the sign-in screen.
async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  };
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

let authMode = "login";

function setAuthMode(mode) {
  authMode = mode;
  const registering = mode === "register";
  $("mode-login").setAttribute("aria-pressed", String(!registering));
  $("mode-register").setAttribute("aria-pressed", String(registering));
  $("auth-title").textContent = registering ? "Make your account" : "Welcome back!";
  $("auth-submit").textContent = registering ? "Create account" : "Sign in";
  $("password").autocomplete = registering ? "new-password" : "current-password";
  $("auth-hint").hidden = !registering;
  setAuthError("");
}

function setAuthError(text) {
  $("auth-error").textContent = text;
  $("auth-error").hidden = !text;
}

function showAuth(message = "") {
  currentProblem = null;
  $("app-main").hidden = true;
  $("user-area").hidden = true;
  $("auth-card").hidden = false;
  $("password").value = "";
  setAuthError(message);
  $("username").focus();
}

function startApp(username) {
  $("auth-card").hidden = true;
  $("user-area").hidden = false;
  $("app-main").hidden = false;
  $("user-name").textContent = username;
  $("user-avatar").textContent = username[0].toUpperCase();
  $("chat").replaceChildren();
  addMessage("tutor", `Hi ${username}! Have a go at the problem above, or ask me anything about equivalent fractions.`);
  loadProblem();
}

$("mode-login").addEventListener("click", () => setAuthMode("login"));
$("mode-register").addEventListener("click", () => setAuthMode("register"));

$("auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = $("username").value.trim();
  const password = $("password").value;
  if (!username || !password) {
    setAuthError("Please enter a username and password.");
    return;
  }
  $("auth-submit").disabled = true;
  const { ok, data } = await api(authMode === "register" ? "/register" : "/login", { username, password });
  $("auth-submit").disabled = false;
  if (!ok) {
    setAuthError(data.detail || "Something went wrong — please try again.");
    return;
  }
  $("password").value = "";
  startApp(data.username);
});

$("sign-out").addEventListener("click", async () => {
  await api("/logout", {});
  showAuth();
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

(async () => {
  const { ok, data } = await api("/me");
  if (ok) startApp(data.username);
  else showAuth(data.detail && data.detail.startsWith("Network") ? data.detail : "");
})();
