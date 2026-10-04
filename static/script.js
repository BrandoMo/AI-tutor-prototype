const studentId = "test_student_1"; // hardcoded for prototype
const concept = "equivalent_fractions";
let currentProblem = null;

function addToChat(text) {
  const chat = document.getElementById("chat");
  chat.textContent += `\n${text}\n`;
  chat.scrollTop = chat.scrollHeight;
}

// Sends text to the tutor and shows its explanation in the chat
async function askTutor(question) {
  let res;
  try {
    res = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ student_id: studentId, concept: concept, question: question })
    });
  } catch (err) {
    addToChat("[Could not reach the tutor — network error. Try again.]");
    return;
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    addToChat(`[Tutor error: ${data.detail || "server error"}. Try again.]`);
    return;
  }
  addToChat(`Tutor: ${data.explanation}`);
}

async function ask() {
  const input = document.getElementById("question");
  const question = input.value.trim();
  if (!question) return;

  addToChat(`You: ${question}`);
  input.value = "";
  await askTutor(question);
}

async function loadProblem() {
  const problemEl = document.getElementById("problem");
  const answerEl = document.getElementById("answer");
  document.getElementById("result").textContent = "";
  document.getElementById("next-problem").style.display = "none";

  let res;
  try {
    res = await fetch(`/problem?student_id=${encodeURIComponent(studentId)}&concept=${encodeURIComponent(concept)}`);
  } catch (err) {
    problemEl.textContent = "[Could not load a problem — network error.]";
    return;
  }
  if (!res.ok) {
    problemEl.textContent = "[Could not load a problem — server error.]";
    return;
  }

  currentProblem = await res.json();
  problemEl.textContent = currentProblem.prompt;
  if (currentProblem.try > 1) {
    document.getElementById("result").textContent = "Second try at this one.";
  }
  answerEl.value = "";
  answerEl.placeholder = currentProblem.answer_format === "yes_no" ? "yes or no" : "e.g. 3/4";
  answerEl.disabled = false;
  document.getElementById("submit-answer").disabled = false;
  answerEl.focus();
}

async function submitAnswer() {
  const answerEl = document.getElementById("answer");
  const resultEl = document.getElementById("result");
  const submitEl = document.getElementById("submit-answer");
  const answer = answerEl.value.trim();
  if (!answer || !currentProblem) return;

  // Lock input while checking so Enter can't double-submit
  submitEl.disabled = true;
  answerEl.disabled = true;
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
    resultEl.textContent = "[Could not check your answer — network error. Try again.]";
    submitEl.disabled = false;
    answerEl.disabled = false;
    return;
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    // e.g. "Please answer with a fraction like 3/4." -- let them fix it
    resultEl.textContent = data.detail || "[Could not check your answer — server error.]";
    submitEl.disabled = false;
    answerEl.disabled = false;
    return;
  }

  if (data.correct) {
    resultEl.textContent = data.try > 1 ? "✅ Correct on your second try!" : "✅ Correct!";
    document.getElementById("next-problem").style.display = "inline-block";
    return;
  }

  if (data.finished) {
    // Out of tries: reveal the answer and have the tutor walk through it
    resultEl.textContent = `❌ Not quite. The answer was ${data.correct_answer}.`;
    document.getElementById("next-problem").style.display = "inline-block";
    addToChat(`You answered "${answer}" to: ${currentProblem.prompt}`);
    await askTutor(`I answered "${answer}" to the problem "${currentProblem.prompt}" and got it wrong again. The answer is ${data.correct_answer}. Can you walk me through it?`);
    return;
  }

  // First wrong try: give a hint (from the grader if it can explain the
  // mistake itself, otherwise from the tutor), then let them retry
  resultEl.textContent = data.feedback
    ? `❌ ${data.feedback} Try again.`
    : "❌ Not quite — read the tutor's hint below, then try again.";
  if (!data.feedback) {
    addToChat(`You answered "${answer}" to: ${currentProblem.prompt}`);
    await askTutor(`I answered "${answer}" to the problem "${currentProblem.prompt}" and got it wrong. Can I have a hint?`);
  }
  answerEl.value = "";
  answerEl.disabled = false;
  submitEl.disabled = false;
  answerEl.focus();
}

document.getElementById("answer").addEventListener("keydown", (e) => {
  if (e.key === "Enter") submitAnswer();
});
document.getElementById("question").addEventListener("keydown", (e) => {
  if (e.key === "Enter") ask();
});

loadProblem();
