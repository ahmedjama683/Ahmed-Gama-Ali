/*
 * Shares the collector's location while a duty shift is open.
 * Loaded on every page for collectors who are on shift.
 *
 * - Sends a point at most once a minute, or sooner after moving 30 m.
 * - Points that fail to send (no signal) are queued on the phone and sent later.
 * - Browsers stop location updates when the screen is locked or the app is
 *   closed; a native Android app would be needed for background tracking.
 */
(function () {
  var cfg = document.getElementById("tracking-config");
  var indicator = document.getElementById("tracking-indicator");
  if (!cfg || !navigator.geolocation) return;

  var URL = cfg.dataset.url, CSRF = cfg.dataset.csrf;
  var MIN_INTERVAL = 60 * 1000, MIN_MOVE_M = 30, MIN_GAP = 15 * 1000;
  var QUEUE_KEY = "tax-tracking-queue", MAX_QUEUE = 500;
  var last = null, lastSent = 0, sending = false;

  function setStatus(text, ok) {
    if (!indicator) return;
    indicator.textContent = text;
    indicator.className = "tracking " + (ok ? "ok" : "warn");
  }
  function readQueue() {
    try { return JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]"); } catch (e) { return []; }
  }
  function writeQueue(q) {
    try { localStorage.setItem(QUEUE_KEY, JSON.stringify(q.slice(-MAX_QUEUE))); } catch (e) {}
  }
  function metres(a, b) {
    var R = 6371000, toRad = Math.PI / 180;
    var dLat = (b.latitude - a.latitude) * toRad, dLon = (b.longitude - a.longitude) * toRad;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(a.latitude * toRad) * Math.cos(b.latitude * toRad) *
      Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 2 * R * Math.asin(Math.sqrt(h));
  }

  function flush() {
    var queue = readQueue();
    if (!queue.length || sending) return;
    sending = true;
    fetch(URL, {
      method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRFToken": CSRF},
      body: JSON.stringify({pings: queue.slice(0, 500)})
    }).then(function (r) {
      sending = false;
      if (r.ok) {
        writeQueue(readQueue().slice(queue.length > 500 ? 500 : queue.length));
        setStatus("● On duty · location shared " + new Date().toTimeString().slice(0, 5), true);
      } else if (r.status === 409) {
        writeQueue([]);  // shift was ended elsewhere
        location.reload();
      } else {
        setStatus("● On duty · location not sent (" + r.status + ")", false);
      }
    }).catch(function () {
      sending = false;
      setStatus("● On duty · no internet, " + readQueue().length + " points waiting", false);
    });
  }

  function onPosition(pos, force) {
    var c = pos.coords, now = Date.now();
    var moved = last ? metres(last, c) : Infinity;
    if (!force && now - lastSent < MIN_INTERVAL && (moved < MIN_MOVE_M || now - lastSent < MIN_GAP)) return;
    last = {latitude: c.latitude, longitude: c.longitude};
    lastSent = now;
    var q = readQueue();
    q.push({
      latitude: c.latitude.toFixed(6), longitude: c.longitude.toFixed(6),
      altitude: c.altitude == null ? null : c.altitude.toFixed(1),
      accuracy: c.accuracy == null ? null : c.accuracy.toFixed(1),
      recorded_at: new Date(pos.timestamp || now).toISOString()
    });
    writeQueue(q);
    flush();
  }
  function onError(err) {
    setStatus("● On duty · turn on location/GPS (" + err.message + ")", false);
  }

  var opts = {enableHighAccuracy: true, maximumAge: 15000, timeout: 30000};
  navigator.geolocation.watchPosition(function (p) { onPosition(p, false); }, onError, opts);
  // watchPosition only fires on movement; also report every 2 minutes when standing still.
  setInterval(function () {
    navigator.geolocation.getCurrentPosition(function (p) { onPosition(p, true); }, onError, opts);
  }, 2 * 60 * 1000);
  window.addEventListener("online", flush);
  flush();
})();
