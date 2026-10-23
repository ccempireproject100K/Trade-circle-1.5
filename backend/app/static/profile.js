// Public profile behavior: FaceTime button on Apple devices, and the quote form.
(function () {
  "use strict";

  // Macs have FaceTime too, and iPadOS reports itself as a Mac, so "Macintosh" covers both.
  var isApple = /iPhone|iPad|iPod|Macintosh/.test(navigator.userAgent);
  if (isApple) {
    document.querySelectorAll("[data-apple-only]").forEach(function (el) {
      el.hidden = false;
    });
  }

  document.querySelectorAll(".quote-form").forEach(function (form) {
    var status = form.querySelector(".form-status");
    var button = form.querySelector("button[type=submit]");

    function show(message, kind) {
      status.textContent = message;
      status.className = "form-status " + kind;
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var data = {};
      new FormData(form).forEach(function (value, key) {
        value = String(value).trim();
        if (value || key === "website") data[key] = value;
      });
      if (!data.name || !data.message) {
        show("Please add your name and some details about the job.", "error");
        return;
      }
      if (!data.phone && !data.email) {
        show("Please give a phone number or an email so they can reply.", "error");
        return;
      }
      button.disabled = true;
      show("Sending…", "");
      fetch("/api/p/" + encodeURIComponent(form.dataset.slug) + "/quote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      })
        .then(function (res) {
          if (res.ok) {
            form.reset();
            show("Sent. They'll get back to you soon.", "ok");
          } else if (res.status === 429) {
            show("Too many requests right now. Please try again later or call.", "error");
          } else if (res.status === 422) {
            show("Please check your phone number and email.", "error");
          } else {
            show("Something went wrong. Please try again or call.", "error");
          }
        })
        .catch(function () {
          show("Couldn't send. Check your connection and try again.", "error");
        })
        .then(function () {
          button.disabled = false;
        });
    });
  });
})();
