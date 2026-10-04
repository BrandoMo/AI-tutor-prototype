const studentId = "test_student_1"; // hardcoded for prototype
const concept = "equivalent_fractions";
let currentProblem = null;

const $ = (id) => document.getElementById(id);

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
  bubble.textContent = text; // textContent, never innerHTML: LLM output is untrusted
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
  let res;
  try {
    res = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ student_id: studentId, concept: concept, question: question })
    });
  } catch (err) {
    typing.remove();
    addMessage("note", "Could not reach the tutor — network error. Try again.");
    return;
  }

  const data = await res.json().catch(() => ({}));
  typing.remove();
  if (!res.ok) {
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

function drawDots(number, total) {
  const dots = $("dots");
  dots.replaceChildren();
  for (let i = 1; i <= total; i++) {
    const dot = document.createElement("span");
    dot.className = "dot" + (i < number ? " done" : i === number ? " current" : "");
    dots.appendChild(dot);
  }
}

// A burst of little circles from the given element
function celebrate(fromEl) {
  const box = fromEl.getBoundingClientRect();
  const colors = ["--primary", "--accent", "--good", "--decor-1", "--decor-2", "--decor-3"];
  for (let i = 0; i < 18; i++) {
    const dot = document.createElement("span");
    dot.className = "confetti";
    const angle = (i / 18) * 2 * Math.PI;
    const distance = 70 + Math.random() * 60;
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

  let res;
  try {
    res = await fetch(`/problem?student_id=${encodeURIComponent(studentId)}&concept=${encodeURIComponent(concept)}`);
  } catch (err) {
    $("problem").textContent = "Could not load a problem — network error.";
    return;
  }
  if (!res.ok) {
    $("problem").textContent = "Could not load a problem — server error.";
    return;
  }

  currentProblem = await res.json();
  $("problem").textContent = currentProblem.prompt;
  $("problem-number").textContent = currentProblem.number;
  drawDots(currentProblem.number, currentProblem.total);
  drawPie(currentProblem.given);

  const yesNo = currentProblem.answer_format === "yes_no";
  $("fraction-form").hidden = yesNo;
  $("yesno-buttons").hidden = !yesNo;
  $("answer").value = "";
  setAnswerEnabled(true);
  if (!yesNo) $("answer").focus();

  if (currentProblem.try > 1) setResult("Second try at this one.");
}

async function submitAnswer(answer, fromEl) {
  if (!answer || !currentProblem) return;

  // Lock input while checking so it can't be double-submitted
  setAnswerEnabled(false);
  let res;
  try {
    res = await fetch("/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        student_id: studentId,
        concept: concept,
        problem_id: currentProblem.id,
        answer: answer
      })
    });
  } catch (err) {
    setResult("Could not check your answer — network error. Try again.", "bad");
    setAnswerEnabled(true);
    return;
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    // e.g. "Please answer with a fraction like 3/4." -- let them fix it
    setResult(data.detail || "Could not check your answer — server error.");
    setAnswerEnabled(true);
    return;
  }

  if (data.correct) {
    setResult(data.try > 1 ? "Correct on your second try!" : "Correct!", "good");
    celebrate(fromEl);
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

addMessage("tutor", "Hi! Have a go at the problem above, or ask me anything about equivalent fractions.");
loadProblem();
