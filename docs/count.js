/* One POST per page view, and nothing else: the same count jugalm.com keeps, to
   the same self-hosted Umami (stats.jugalm.com) under the same website id, so the
   whole domain reads as one site and song is the rows whose URL begins /song/.
   This is the WEBSITE's counter, for this page and the live demo. The tool itself
   has none and never will: nothing leaves your machine. No cookies, no storage, no
   identifier; Do Not Track and Global Privacy Control are honoured; anything that
   is not jugalm.com is not a visit. text/plain is load-bearing: sendBeacon always
   sends credentials, application/json would force a preflight, and a credentialed
   preflight refuses Umami's wildcard allow-origin. */
(function () {
  var n = navigator;
  if (location.hostname !== 'jugalm.com' || n.webdriver || !n.sendBeacon) return;
  if (n.doNotTrack === '1' || window.doNotTrack === '1' || n.globalPrivacyControl === true) return;
  try {
    n.sendBeacon('https://stats.jugalm.com/api/send', new Blob([JSON.stringify({ type: 'event', payload: {
      website: '0a907e1e-2783-4515-b2bf-d5a2b7d8db57', hostname: location.hostname, url: location.pathname,
      title: document.title, referrer: document.referrer, screen: screen.width + 'x' + screen.height, language: n.language
    } })], { type: 'text/plain;charset=UTF-8' }));
  } catch (e) { /* counting is never worth an error in the console */ }
})();
