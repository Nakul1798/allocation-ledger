(function () {
  var log = document.getElementById("chat-log");
  var form = document.getElementById("chat-form");
  var input = document.getElementById("chat-input");
  if (!form) return;

  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var csrfToken = csrfMeta ? csrfMeta.content : "";

  function addMessage(role, text) {
    var el = document.createElement("div");
    el.className = "chat-msg chat-msg-" + role;
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
  }

  form.addEventListener("submit", function (evt) {
    evt.preventDefault();
    var question = input.value.trim();
    if (!question) return;
    addMessage("user", question);
    input.value = "";
    input.disabled = true;

    fetch("/assistant/ask", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken
      },
      body: JSON.stringify({ question: question })
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        if (result.ok && result.data.answer) {
          addMessage("assistant", result.data.answer);
        } else {
          addMessage("error", result.data.error || "Something went wrong.");
        }
      })
      .catch(function () {
        addMessage("error", "Couldn't reach the server.");
      })
      .finally(function () {
        input.disabled = false;
        input.focus();
      });
  });
})();
