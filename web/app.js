const form = document.querySelector("#question-form");
const input = document.querySelector("#question");
const sendButton = document.querySelector("#send-button");
const messages = document.querySelector("#messages");
const status = document.querySelector("#status");

function addMessage(role, text) {
  const message = document.createElement("article");
  message.className = `message message--${role}`;

  const label = document.createElement("span");
  label.className = "message__label";
  label.textContent = role === "user" ? "You" : "Assistant";
  message.append(label);

  if (role === "user") {
    const content = document.createElement("p");
    content.className = "message__text";
    content.textContent = text;
    message.append(content);
  } else {
    renderAnswer(message, text);
  }

  messages.append(message);
  messages.scrollTop = messages.scrollHeight;
}

function renderAnswer(message, answer) {
  const updatedMatch = answer.match(/(?:^|\n)(Last updated from sources:[^\n]*)\s*$/);
  const mainText = updatedMatch
    ? answer.slice(0, updatedMatch.index).trim()
    : answer.trim();
  const content = document.createElement("p");
  content.className = "message__answer";

  const linkMatch = mainText.match(/\[([^\]]+)\]\((https:\/\/[^)\s]+)\)/);
  if (linkMatch) {
    let sourceUrl;
    try {
      sourceUrl = new URL(linkMatch[2]);
    } catch {
      sourceUrl = null;
    }

    if (sourceUrl?.protocol === "https:") {
      content.append(document.createTextNode(mainText.slice(0, linkMatch.index)));
      const link = document.createElement("a");
      link.href = sourceUrl.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = linkMatch[1];
      content.append(link);
      content.append(document.createTextNode(mainText.slice(linkMatch.index + linkMatch[0].length)));
    } else {
      content.textContent = mainText;
    }
  } else {
    content.textContent = mainText;
  }
  message.append(content);

  if (updatedMatch) {
    const updated = document.createElement("p");
    updated.className = "message__updated";
    updated.textContent = updatedMatch[1];
    message.append(updated);
  }
}

function setStatus(message, isError = false) {
  status.textContent = message;
  status.classList.toggle("status--error", isError);
}

async function submitQuestion(question) {
  const normalized = question.trim();
  if (!normalized || sendButton.disabled) return;

  addMessage("user", normalized);
  input.value = "";
  sendButton.disabled = true;
  setStatus("Finding an answer in approved sources…");

  try {
    const response = await fetch("/api/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: normalized }),
    });
    const result = await response.json();
    if (!response.ok || typeof result.answer !== "string") {
      throw new Error("Answer service unavailable");
    }
    addMessage("assistant", result.answer);
    setStatus("");
  } catch {
    setStatus("The answer service is unavailable. Please try again later.", true);
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  submitQuestion(input.value);
});

document.querySelectorAll(".example").forEach((button) => {
  button.addEventListener("click", () => submitQuestion(button.textContent));
});