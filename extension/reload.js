(() => {
  const loadedVersion = chrome.runtime.getManifest().version;
  let targetVersion = loadedVersion;
  try { targetVersion = new URL(location.href).searchParams.get("target") || loadedVersion; } catch (_) {}
  document.body.textContent = `Reloading CATFOOD Atom + Boost ${loadedVersion} → ${targetVersion}…`;
  void (async () => {
    let tabId = null;
    try { const tab = await chrome.tabs.getCurrent(); if (Number.isInteger(tab?.id)) tabId = tab.id; } catch (_) {}
    try { await chrome.storage.local.set({
      catfoodReinjectAfterReloadV1:{target:targetVersion,from:loadedVersion,ts:Date.now()},
      catfoodBootstrapReloadTabV1:{tabId,target:targetVersion,from:loadedVersion,ts:Date.now()}
    }); } catch (_) {}
    chrome.runtime.reload();
  })();
})();
