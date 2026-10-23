// Sends a business's removal request for a supplier listing.
(function () {
  "use strict";
  var form = document.querySelector(".removal-form");
  if (!form) return;
  var status = form.querySelector(".form-status");
  var button = form.querySelector("button[type=submit]");
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var data = {};
    new FormData(form).forEach(function (value, key) {
      data[key] = String(value).trim();
    });
    if (!data.requester_name || !data.requester_role || !data.email) {
      status.textContent = "Please add your name, your role and a work email.";
      status.className = "form-status error";
      return;
    }
    button.disabled = true;
    fetch("/api/suppliers/" + encodeURIComponent(form.dataset.supplier) + "/removal-requests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    })
      .then(function (res) {
        return res.json().then(function (body) { return { ok: res.ok, status: res.status, body: body }; });
      })
      .then(function (r) {
        if (r.ok) {
          form.reset();
          status.textContent = r.body.message;
          status.className = "form-status ok";
        } else {
          status.textContent = r.status === 429 ? "Too many requests. Please try again later." : "Please check your details and try again.";
          status.className = "form-status error";
        }
      })
      .catch(function () {
        status.textContent = "Couldn't send. Check your connection and try again.";
        status.className = "form-status error";
      })
      .then(function () { button.disabled = false; });
  });
})();
