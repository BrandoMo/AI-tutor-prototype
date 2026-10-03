const studentId = "test_student_1"; // hardcoded for prototype
const concept = "equivalent_fractions";
let lastQuestion = null; // saved with the attempt so the tutor sees what was typed

async function ask() {
  const input = document.getElementById("question");
  const chat = document.getElementById("chat");
  const question = input.value.trim();
  if (!question) return;

  chat.textContent += `\nYou: ${question}\n`;
  input.value = "";

  let res;
  try {
    res = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ student_id: studentId, concept: concept, question: question })
    });
  } catch (err) {
    chat.textContent += `\n[Could not reach the tutor — network error. Try again.]\n`;
    return;
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    chat.textContent += `\n[Tutor error: ${data.detail || "server error"}. Try again.]\n`;
    chat.scrollTop = chat.scrollHeight;
    return;
  }

  lastQuestion = question;
  chat.textContent += `\nTutor: ${data.explanation}\n`;
  chat.scrollTop = chat.scrollHeight;

  // Show the right/wrong feedback buttons after every explanation
  document.getElementById("feedback").style.display = "block";
}

async function logAttempt(wasCorrect) {
  const chat = document.getElementById("chat");

  // For the prototype, error_type is only asked when the answer was wrong
  let errorType = null;
  if (!wasCorrect) {
    errorType = prompt("Optional: briefly describe the mistake (or leave blank)") || null;
  }

  let res;
  try {
    res = await fetch("/attempt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        student_id: studentId,
        concept: concept,
        correct: wasCorrect,
        error_type: errorType,
        answer: lastQuestion
      })
    });
  } catch (err) {
    chat.textContent += `\n[Could not save — network error. Try again.]\n`;
    return;
  }

  if (!res.ok) {
    chat.textContent += `\n[Could not save — server error. Try again.]\n`;
    return;
  }

  chat.textContent += `\n[Logged: ${wasCorrect ? "correct" : "incorrect"}]\n`;
  chat.scrollTop = chat.scrollHeight;

  document.getElementById("feedback").style.display = "none";
}
