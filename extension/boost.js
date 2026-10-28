(() => {
  if(globalThis.__CATFOOD_BOOST_ACTIVE_V1__)return;
  globalThis.__CATFOOD_BOOST_ACTIVE_V1__=true;
  const STYLE_ID = "catfood-boost-style";
  const CULLED_ATTR = "data-catfood-offscreen";
  const ROLE_SELECTOR = "[data-message-author-role]";
  const COMPLEX_SELECTOR = [
    "pre", "code", "img", "picture", "video", "audio", "canvas", "svg", "iframe",
    "table", "input", "textarea", "select", "button", "[role=button]", "[contenteditable=true]",
    "[aria-expanded=true]", "dialog", "[role=dialog]", "[data-state=open]"
  ].join(",");
  const OFFSCREEN_MESSAGES_RUNTIME_ENABLED = false;
  const DEFAULTS = {
    enabled: false,
    reduceMotion: false,
    reduceBlur: false,
    instantScroll: false,
    offscreenMessages: false
  };

  const tracked = new Set();
  let blocked = new WeakSet();
  let observer = null;
  let mutationObserver = null;
  let shellObserver = null;
  let observedRoot = null;
  let recentLive = new Set();
  let reconcilePending = false;
  let reconcileHandle = null;
  let settingsEpoch = 0;
  let focusHandler = null;
  let resizeObserver = null;
  let resizeRoot = null;
  let resizeWidth = null;
  let resizeHandle = null;
  const pendingCull = new Map();
  let cullDrainHandle = null;
  const ADAPTIVE_MOTION_STYLE_ID = "catfood-adaptive-motion-style";
  const ADAPTIVE_MOTION_HOLD_MS = 1500;
  let adaptiveMotionTimer = null;

  function adaptiveMotionOff() {
    document.getElementById(ADAPTIVE_MOTION_STYLE_ID)?.remove();
    adaptiveMotionTimer = null;
  }
  function adaptiveMotionOn() {
    let style = document.getElementById(ADAPTIVE_MOTION_STYLE_ID);
    if (!style) {
      style = document.createElement("style");
      style.id = ADAPTIVE_MOTION_STYLE_ID;
      style.textContent = "*,*::before,*::after{animation-delay:0s!important;animation-duration:.001ms!important;animation-iteration-count:1!important;transition-delay:0s!important;transition-duration:.001ms!important}";
      document.documentElement?.appendChild(style);
    }
    if (adaptiveMotionTimer !== null) clearTimeout(adaptiveMotionTimer);
    adaptiveMotionTimer = setTimeout(adaptiveMotionOff, ADAPTIVE_MOTION_HOLD_MS);
  }
  document.addEventListener("catfood:adaptive-motion-pressure", adaptiveMotionOn);

  function cssFor(cfg) {
    const rules = [];
    if (cfg.reduceMotion) {
      rules.push(`
        *, *::before, *::after {
          animation-delay: 0s !important;
          animation-duration: 0.001ms !important;
          animation-iteration-count: 1 !important;
          transition-delay: 0s !important;
          transition-duration: 0.001ms !important;
        }
      `);
    }
    if (cfg.instantScroll) {
      rules.push(`
        html, body, main,
        [class*="overflow-y-auto"], [class*="overflow-auto"] {
          scroll-behavior: auto !important;
        }
      `);
    }
    if (cfg.reduceBlur) {
      rules.push(`
        [class*="backdrop-blur"] {
          backdrop-filter: none !important;
          -webkit-backdrop-filter: none !important;
        }
      `);
    }
    rules.push(`
      [${CULLED_ATTR}] {
        content-visibility: auto !important;
        contain-intrinsic-block-size: var(--catfood-boost-intrinsic-block-size) !important;
      }
      @media print {
        [${CULLED_ATTR}] {
          content-visibility: visible !important;
          contain-intrinsic-block-size: none !important;
        }
      }
    `);
    return rules.join("\n");
  }

  function intrinsicContentHeight(el, borderBoxHeight) {
    const cs = getComputedStyle(el);
    const px = value => Number.parseFloat(value) || 0;
    const chrome = px(cs.paddingTop) + px(cs.paddingBottom) + px(cs.borderTopWidth) + px(cs.borderBottomWidth);
    return Math.max(1, Math.round(borderBoxHeight - chrome));
  }

  function applyCullIntrinsic(el, intrinsic) {
    el.setAttribute(CULLED_ATTR, "1");
    el.style.setProperty("--catfood-boost-intrinsic-block-size", `${intrinsic}px`);
  }

  function clearCull(el) {
    pendingCull.delete(el);
    el.removeAttribute(CULLED_ATTR);
    el.style.removeProperty("--catfood-boost-intrinsic-block-size");
  }

  function untrack(el, {block = false} = {}) {
    if (block) blocked.add(el);
    if (tracked.has(el)) {
      observer?.unobserve(el);
      tracked.delete(el);
    }
    recentLive.delete(el);
    clearCull(el);
  }

  function cancelReconcile() {
    if (!reconcilePending || reconcileHandle == null) return;
    clearTimeout(reconcileHandle);
    reconcilePending = false;
    reconcileHandle = null;
  }

  function cancelCullDrain() {
    if (cullDrainHandle != null) clearTimeout(cullDrainHandle);
    cullDrainHandle = null;
    pendingCull.clear();
  }

  function cancelResizeRefresh() {
    if (resizeHandle != null) clearTimeout(resizeHandle);
    resizeHandle = null;
  }

  function disableCull() {
    cancelReconcile();
    cancelResizeRefresh();
    cancelCullDrain();
    mutationObserver?.disconnect();
    mutationObserver = null;
    shellObserver?.disconnect();
    shellObserver = null;
    observedRoot = null;
    resizeObserver?.disconnect();
    resizeObserver = null;
    resizeRoot = null;
    resizeWidth = null;
    if (focusHandler) {
      document.removeEventListener("focusin", focusHandler, true);
      focusHandler = null;
    }
    observer?.disconnect();
    observer = null;
    for (const el of tracked) clearCull(el);
    tracked.clear();
    recentLive = new Set();
    blocked = new WeakSet();
  }

  function isComplex(el) {
    return !!el.querySelector(COMPLEX_SELECTOR);
  }

  function eligible(el) {
    if (!(el instanceof HTMLElement) || !el.isConnected) return false;
    if (recentLive.has(el) || blocked.has(el) || el.matches(":focus-within")) return false;
    if (isComplex(el)) {
      blocked.add(el);
      return false;
    }
    return true;
  }

  function roleNodes() {
    const raw = [...document.querySelectorAll(ROLE_SELECTOR)];
    const hasNestedRole = new Set();
    for (const el of raw) {
      const parentRole = el.parentElement?.closest(ROLE_SELECTOR);
      if (parentRole) hasNestedRole.add(parentRole);
    }
    return raw.filter(el => !hasNestedRole.has(el));
  }

  function scheduleReconcile() {
    if (reconcilePending) return;
    reconcilePending = true;
    const run = () => {
      reconcilePending = false;
      reconcileHandle = null;
      reconcile();
    };
    reconcileHandle = setTimeout(run, 100);
  }

  function reconcile() {
    if (!observer) return;
    attachMutationRoot();
    const all = roleNodes();
    const live = new Set(all);
    const previousRecent = recentLive;
    recentLive = new Set(all.slice(-6));

    for (const el of [...tracked]) {
      if (!live.has(el)) untrack(el);
    }

    for (const el of all) {
      if (tracked.has(el) || blocked.has(el)) continue;
      if (isComplex(el)) {
        blocked.add(el);
        continue;
      }
      tracked.add(el);
      observer.observe(el);
    }

    // Recent messages stay fully rendered. When one ages out, re-observe it so
    // IntersectionObserver immediately gives it a fresh eligibility decision.
    for (const el of recentLive) clearCull(el);
    for (const el of previousRecent) {
      if (recentLive.has(el) || !tracked.has(el)) continue;
      observer.unobserve(el);
      observer.observe(el);
    }
  }

  function roleOwner(node) {
    if (!(node instanceof Element)) return null;
    if (node.matches(ROLE_SELECTOR)) return node;
    return node.closest?.(ROLE_SELECTOR) || null;
  }

  function mutationTouchesRoleSubtree(node) {
    return node instanceof Element && (node.matches?.(ROLE_SELECTOR) || !!node.querySelector?.(ROLE_SELECTOR));
  }

  function mutationCallback(records) {
    let structureChanged = false;
    for (const r of records) {
      if (r.type === "attributes") {
        if (r.attributeName === "data-message-author-role") {
          structureChanged = true;
          if (tracked.has(r.target) && !r.target.matches(ROLE_SELECTOR)) untrack(r.target);
          continue;
        }
        const owner = roleOwner(r.target);
        if (owner && tracked.has(owner) && isComplex(owner)) untrack(owner, {block: true});
        continue;
      }

      if (r.type !== "childList") continue;
      const owner = roleOwner(r.target);
      if (owner && tracked.has(owner) && r.addedNodes.length) {
        // Old messages changing after completion are correctness-sensitive.
        // Stop culling that message rather than repeatedly reevaluating it.
        untrack(owner, {block: true});
      }

      if (!structureChanged) {
        structureChanged = [...r.addedNodes, ...r.removedNodes].some(mutationTouchesRoleSubtree);
      }
    }
    if (structureChanged) scheduleReconcile();
  }

  function desiredMutationRoot() {
    const firstRole = document.querySelector(ROLE_SELECTOR);
    return firstRole?.closest("main") || document.querySelector("main") || document.body || document.documentElement;
  }

  function reobserveTrackedAfterResize() {
    resizeHandle = null;
    if (!observer || !resizeRoot?.isConnected) return;
    // With culling removed, one geometry read gives the browser a chance to
    // settle message heights at the new width before we cache them again.
    void resizeRoot.offsetHeight;
    for (const el of tracked) {
      if (!el.isConnected || recentLive.has(el) || blocked.has(el)) continue;
      observer.unobserve(el);
      observer.observe(el);
    }
  }

  function onConversationWidth(width) {
    if (!Number.isFinite(width) || width <= 0) return;
    if (resizeWidth == null) {
      resizeWidth = width;
      return;
    }
    if (Math.abs(width - resizeWidth) < 2) return;
    resizeWidth = width;
    // Cached intrinsic block sizes are width-dependent. During a width change,
    // prefer correct scroll geometry over culling. Re-enable after it settles.
    cancelCullDrain();
    for (const el of tracked) clearCull(el);
    cancelResizeRefresh();
    resizeHandle = setTimeout(reobserveTrackedAfterResize, 180);
  }

  function attachResizeRoot(root) {
    if (typeof ResizeObserver !== "function") return;
    if (resizeRoot === root && resizeObserver) return;
    resizeObserver?.disconnect();
    resizeRoot = root;
    resizeWidth = null;
    resizeObserver = new ResizeObserver(entries => {
      for (const entry of entries) {
        if (entry.target !== resizeRoot) continue;
        onConversationWidth(entry.contentRect?.width || resizeRoot.getBoundingClientRect().width);
      }
    });
    resizeObserver.observe(root);
  }

  function attachMutationRoot() {
    const nextRoot = desiredMutationRoot();
    if (!nextRoot || nextRoot === observedRoot) return;
    mutationObserver?.disconnect();
    observedRoot = nextRoot;
    mutationObserver = new MutationObserver(mutationCallback);
    mutationObserver.observe(observedRoot, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["data-message-author-role", "contenteditable", "aria-expanded", "role", "data-state"]
    });
    attachResizeRoot(observedRoot);
  }

  function ensureShellObserver() {
    if (shellObserver || !document.body) return;
    shellObserver = new MutationObserver(() => {
      if (!observedRoot?.isConnected) {
        observedRoot = null;
        attachMutationRoot();
        scheduleReconcile();
      }
    });
    shellObserver.observe(document.body, {childList: true});
  }

  function scheduleCullDrain() {
    if (cullDrainHandle != null || !pendingCull.size) return;
    cullDrainHandle = setTimeout(drainCullQueue, 0);
  }

  function drainCullQueue() {
    cullDrainHandle = null;
    if (!observer || !pendingCull.size) return;

    const batch = [];
    for (const [el, borderBoxHeight] of pendingCull) {
      pendingCull.delete(el);
      batch.push([el, borderBoxHeight]);
      if (batch.length >= 32) break;
    }

    const toClear = [];
    const toCull = [];
    // Read phase for one bounded slice.
    for (const [el, borderBoxHeight] of batch) {
      if (!eligible(el)) {
        toClear.push(el);
        continue;
      }
      toCull.push([el, intrinsicContentHeight(el, borderBoxHeight)]);
    }

    // Write phase for the same slice.
    for (const el of toClear) clearCull(el);
    for (const [el, intrinsic] of toCull) {
      if (!el.isConnected || recentLive.has(el) || blocked.has(el) || el.matches(":focus-within")) continue;
      applyCullIntrinsic(el, intrinsic);
    }

    if (pendingCull.size) scheduleCullDrain();
  }

  function ensureObserver() {
    if (observer || !CSS.supports("content-visibility", "auto")) return;
    observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        const el = entry.target;
        if (entry.isIntersecting) {
          clearCull(el);
          continue;
        }
        const borderBoxHeight = Math.max(1, entry.boundingClientRect.height || 1);
        pendingCull.set(el, borderBoxHeight);
      }
      scheduleCullDrain();
    }, {root: null, rootMargin: "2000px 0px 2000px 0px", threshold: 0});
  }

  function ensureFocusSafety() {
    if (focusHandler) return;
    focusHandler = e => {
      const owner = roleOwner(e.target);
      if (owner) clearCull(owner);
    };
    document.addEventListener("focusin", focusHandler, true);
  }

  function enableCull() {
    ensureObserver();
    if (!observer) return;
    attachMutationRoot();
    ensureShellObserver();
    ensureFocusSafety();
    reconcile();
  }

  function setCullEnabled(on) {
    if (!on) {
      disableCull();
      return;
    }
    enableCull();
  }

  function apply(cfg) {
    let style = document.getElementById(STYLE_ID);
    if (!cfg.enabled) {
      style?.remove();
      document.documentElement?.removeAttribute("data-catfood-boost");
      setCullEnabled(false);
      return;
    }
    if (!style) {
      style = document.createElement("style");
      style.id = STYLE_ID;
      document.documentElement.appendChild(style);
    }
    style.textContent = cssFor(cfg);
    document.documentElement.setAttribute("data-catfood-boost", "active");
    setCullEnabled(OFFSCREEN_MESSAGES_RUNTIME_ENABLED && !!cfg.offscreenMessages);
  }

  function loadAndApply() {
    const epoch = ++settingsEpoch;
    chrome.storage.local.get(DEFAULTS).then(cfg => {
      if (!OFFSCREEN_MESSAGES_RUNTIME_ENABLED && cfg.offscreenMessages) {
        cfg = {...cfg, offscreenMessages:false};
        chrome.storage.local.set({offscreenMessages:false}).catch(()=>{});
      }
      if (epoch === settingsEpoch) apply(cfg);
    }).catch(() => {
      if (epoch === settingsEpoch) apply(DEFAULTS);
    });
  }

  function start() {
    loadAndApply();
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area !== "local") return;
      if (!Object.keys(changes).some(k => k in DEFAULTS)) return;
      loadAndApply();
    });
  }

  if (document.documentElement) {
    start();
  } else {
    const bootObserver = new MutationObserver(() => {
      if (!document.documentElement) return;
      bootObserver.disconnect();
      start();
    });
    bootObserver.observe(document, {childList: true});
  }
})();
