---
name: Fix DOJO Mobile Gating
overview: Fix the DOJO mobile dropdown showing all 6 modes instead of only subscribed dojos, by making the gating more robust and adding cache-busting.
todos:
  - id: fix-mobile-gating
    content: Replace modeSel.remove(i) with modeSel.options[i] = null in night_school_dojo.html and add diagnostic logging
    status: completed
  - id: cache-bust-dojo-url
    content: Add timestamp cache-buster to DOJO iframe URL in updated_screens.dart for both web and mobile paths
    status: completed
  - id: deploy-and-test
    content: Deploy updated night_school_dojo.html and Flutter web build to server, restart containers
    status: completed
isProject: false
---

# Fix DOJO Mobile Mode Gating

## Problem

Desktop DOJO tab buttons correctly hide unsubscribed modes, but the mobile `<select>` dropdown (`#mobileModeSel`) shows all 6 modes regardless of the coach's `selected_dojos`.

## Root Cause Analysis

The gating code at lines 989-996 of [night_school_dojo.html](dashboard/night_school_dojo.html) uses `modeSel.remove(i)` which can be ambiguous on WebKit browsers (iOS Safari/Chrome) between `HTMLSelectElement.remove(index)` and `ChildNode.remove()`. Additionally, there is no diagnostic logging to confirm the mobile branch actually executes.

## Fix Strategy

### 1. Robust mobile option removal in `night_school_dojo.html` (lines 989-997)

Replace `modeSel.remove(i)` with the more portable `modeSel.options[i] = null` pattern, and add a global `gatedDojos` variable so the gating can be re-applied if needed:

```javascript
// Store globally for re-application
window._gatedDojos = selectedDojos;

// Hide mobile mode dropdown options not in selected_dojos
var modeSel = document.getElementById("mobileModeSel");
console.log(">>> Mobile gating: modeSel found:", !!modeSel, 
            "options:", modeSel ? modeSel.options.length : 0,
            "selectedDojos:", selectedDojos);
if (modeSel) {
    for (var i = modeSel.options.length - 1; i >= 0; i--) {
        if (selectedDojos.indexOf(modeSel.options[i].value) === -1) {
            console.log(">>> Removing mobile option:", modeSel.options[i].value);
            modeSel.options[i] = null;  // Most portable removal
        }
    }
}
```

### 2. Add cache-busting to DOJO iframe URL in Flutter

In [updated_screens.dart](mobile/lib/updated_screens.dart), append a timestamp query param to the DOJO URL to prevent browser/WebView caching of old HTML:

- Line ~6592 (web path): Add `'v': DateTime.now().millisecondsSinceEpoch.toString()` to query params
- Line ~6599 (mobile path): Same cache-buster param

### 3. Deploy and verify

- Copy updated `night_school_dojo.html` to server
- Rebuild Flutter web (skip index.html)
- rsync web build to server (no --delete)
- Docker restart backend container
- Test on iPhone Chrome with console open to verify gating logs

