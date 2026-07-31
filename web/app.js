// Convene dashboard. Read-only: pulls live conflicts and recommendations from
// the public GET routes. The write routes (/sync, /recommend) are API-key
// gated and never called from the browser, so no secret ships to the client.
(function () {
  "use strict";
  var API = (window.CV_API_BASE || "").replace(/\/$/, "");
  document.getElementById("api-note").textContent = API ? "live" : "no API configured";

  function fmt(iso) {
    if (!iso) return "?";
    var d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.toLocaleString(undefined, {
      weekday: "short", month: "short", day: "numeric",
      hour: "numeric", minute: "2-digit",
    });
  }
  function timeOnly(iso) {
    var d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function get(path) {
    return fetch(API + path).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
  }

  function renderFreshness(lastSync) {
    var node = document.getElementById("freshness");
    if (!lastSync || !Object.keys(lastSync).length) {
      node.textContent = "No calendar sync yet.";
      return;
    }
    var parts = Object.keys(lastSync).map(function (k) {
      var s = lastSync[k];
      return k + " " + (s.events != null ? s.events + " events" : "") + " · synced " + fmt(s.at);
    });
    node.textContent = parts.join("   |   ");
  }

  function renderConflicts(data) {
    var box = document.getElementById("conflicts");
    box.innerHTML = "";
    var list = (data && data.conflicts) || [];
    if (!list.length) {
      box.appendChild(el("p", "empty", "No conflicts detected between your two calendars. "
        + "Nothing is colliding right now."));
      return;
    }
    list.forEach(function (c) {
      var card = el("div", "card");
      var row = el("div", "conflict-row");
      row.appendChild(el("span", "conflict-when", fmt(c.academic && c.academic.start)));
      var badge = el("span", "badge " + c.type, c.type === "hard" ? "hard conflict" : "same day");
      row.appendChild(badge);
      card.appendChild(row);

      var vs = el("div", "conflict-vs");
      [["Academic", c.academic], ["Community", c.community]].forEach(function (pair) {
        var ev = el("div", "ev");
        ev.appendChild(el("span", "tag", pair[0]));
        ev.appendChild(el("span", "title", (pair[1] && pair[1].summary) || "(untitled)"));
        var t = pair[1] && pair[1].all_day ? "all day"
          : timeOnly(pair[1] && pair[1].start) + "–" + timeOnly(pair[1] && pair[1].end);
        ev.appendChild(el("span", "time", t));
        vs.appendChild(ev);
      });
      card.appendChild(vs);
      box.appendChild(card);
    });
  }

  function sourceBadge(source) {
    if (!source || source === "pending") return el("span", "badge pending", "thinking…");
    if (source.indexOf("FALLBACK") === 0 || source.indexOf("error") === 0)
      return el("span", "badge fallback", "no AI (fallback)");
    if (source === "no-slots") return el("span", "badge fallback", "no free slot");
    return el("span", "badge model", source);
  }

  function renderRecos(data) {
    var box = document.getElementById("recos");
    box.innerHTML = "";
    var list = (data && data.recommendations) || [];
    if (!list.length) {
      box.appendChild(el("p", "empty", "No recommendations yet."));
      return false;
    }
    var anyPending = false;
    list.forEach(function (r) {
      if (r.status === "pending") anyPending = true;
      var card = el("div", "card");
      var title = el("div", "reco-title");
      title.appendChild(el("span", null, r.title || "New event"));
      title.appendChild(sourceBadge(r.source));
      card.appendChild(title);

      card.appendChild(el("div", "reco-meta",
        (r.duration_min ? r.duration_min + " min" : "") +
        (r.total_free != null ? " · " + r.total_free + " free slots, " + (r.candidate_count || 0) + " shortlisted" : "") +
        " · " + fmt(r.requested_at)));

      if (r.status === "pending") {
        card.appendChild(el("div", "reco-reasoning", "Gemini is weighing your calendars… this refreshes automatically."));
      } else if (r.reasoning) {
        card.appendChild(el("div", "reco-reasoning", r.reasoning));
      }

      var ranked = r.ranked || [];
      if (ranked.length) {
        var slots = el("div", "reco-slots");
        ranked.slice(0, 4).forEach(function (s, i) {
          var slot = el("div", "slot" + (i === 0 ? " best" : ""));
          slot.appendChild(el("span", "rank", i + 1));
          slot.appendChild(el("span", "when", fmt(s.start)));
          slot.appendChild(el("span", "why", s.why || ""));
          slots.appendChild(slot);
        });
        card.appendChild(slots);
      }
      box.appendChild(card);
    });
    return anyPending;
  }

  function loadConflicts() {
    get("/conflicts").then(function (d) {
      renderConflicts(d);
      renderFreshness(d.last_sync);
    }).catch(function () {
      document.getElementById("conflicts").innerHTML =
        '<p class="empty">Could not reach the API.</p>';
    });
  }

  function loadRecos() {
    get("/recommendations?limit=6").then(function (d) {
      var pending = renderRecos(d);
      if (pending) setTimeout(loadRecos, 4000);  // poll while any reco is still thinking
    }).catch(function () {
      document.getElementById("recos").innerHTML =
        '<p class="empty">Could not reach the API.</p>';
    });
  }

  if (!API) {
    document.getElementById("conflicts").innerHTML = '<p class="empty">No API configured.</p>';
    document.getElementById("recos").innerHTML = "";
    return;
  }
  loadConflicts();
  loadRecos();
})();
