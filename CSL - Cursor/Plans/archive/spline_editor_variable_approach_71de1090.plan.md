---
name: Spline Editor Variable Approach
overview: Reconfigure the Spline scene in the editor to add a String variable with Variable Change events for each expression state, then simplify the runtime JavaScript to use the official `setVariable()` API, and fix the iframe race condition.
todos:
  - id: spline-editor
    content: "User: reconfigure Spline scene - add String variable 'expression' and 9 Variable Change events, re-export .splinecode"
    status: completed
  - id: simplify-index
    content: Rewrite index.html to use app.setVariable('expression', value) - remove all internal API hacking
    status: completed
  - id: fix-race
    content: Fix iframe race condition in spline_iframe_web.dart - queue expressions, replay on spline_ready
    status: completed
  - id: cleanup-logs
    content: Remove diagnostic console.log/print statements from index.html and Dart files
    status: pending
  - id: build-deploy-test
    content: Build, deploy, and verify expressions change visually
    status: pending
isProject: false
---

# Spline Editor Variable Approach

## Why This Approach

All JS-only approaches failed because the self-hosted `@splinetool/runtime` export does not expose a working programmatic state-transition API. The `transition()` method returns "Missing property", `updateState()` requires a variable system that doesn't exist, and `emitEvent()` has no configured event actions. The root cause is that the Spline scene has 9 states defined but **no variables** and **no event actions** to trigger transitions.

The official documented way to drive state changes from code is:

1. Create a **String variable** in the Spline editor
2. Add **Variable Change** events that listen for that variable and trigger **Transition** actions
3. Call `app.setVariable('expression', 'sad')` from JavaScript

## Step 1: Spline Editor Changes (User)

Open the scene in the Spline editor and make the following changes:

### 1a. Create a String Variable

- Right sidebar > Variables panel > click "+"
- Type: **String**
- Name: `**expression**`
- Default value: `**neutral**`

### 1b. Add 9 Variable Change Events

Select the `texturized (1)` object. In the Events panel, add one event per expression:

For each of these 9 expressions, create:

- **Event type**: Variable Change
- **Condition**: variable `expression` equals the short name
- **Action**: Transition to the matching state


| Expression | Condition value | Target state                                    |
| ---------- | --------------- | ----------------------------------------------- |
| neutral    | `neutral`       | `neutral_eyebrows_level_mouth_closed_eyes_open` |
| warm       | `warm`          | `warm_happy_eyebrows_slightly_raised...`        |
| attentive  | `attentive`     | `attentive_eyebrows_slightly_raised...`         |
| empathetic | `empathetic`    | `empathetic_eyebrows_inner_corners...`          |
| curious    | `curious`       | `curious_eyebrows_one_raised...`                |
| calming    | `calming`       | `calming_eyebrows_relaxed...`                   |
| proud      | `proud`         | `proud_eyebrows_raised_mouth_big_smile...`      |
| sad        | `sad`           | `sad_eyebrows_lowered_mouth_slight_frawn...`    |
| frustrated | `frustrated`    | `frustrated_eyebrows_centered_inward...`        |


### 1c. Re-export

- File > Export > Code (`.splinecode`)
- Replace `mobile/web/spline/scene.splinecode` with the new export

## Step 2: Simplify index.html

Replace [mobile/web/spline/index.html](mobile/web/spline/index.html) (currently 198 lines of complex internal API hacking) with a clean ~60-line file that uses only the official API:

```javascript
import { Application } from 'https://unpkg.com/@splinetool/runtime/build/runtime.js';

const app = new Application(document.getElementById('canvas3d'));
let splineApp = null;
let currentExpression = 'neutral';

function setAvatarState(expression) {
  if (!splineApp || expression === currentExpression) return;
  currentExpression = expression;
  splineApp.setVariable('expression', expression);
}

window.addEventListener('message', (event) => {
  if (event.data?.type === 'setExpression') {
    setAvatarState(event.data.expression);
  }
});

app.load(new URL('./scene.splinecode', location.href).href).then(() => {
  splineApp = app;
  window.parent.postMessage({ type: 'spline_ready' }, '*');
});
```

No UUID maps, no internal entity walking, no Proxy hacks. Just `setVariable`.

## Step 3: Fix the Iframe Race Condition

The logs consistently show:

```
[Flutter->Spline] Sending expression: neutral
[Flutter->Spline] WARNING: No Spline iframe found!
```

This happens because Flutter sends the initial expression before the Spline iframe is registered in the DOM. Fix in [mobile/lib/spline_iframe_web.dart](mobile/lib/spline_iframe_web.dart):

- Add a pending expression queue
- Listen for the `spline_ready` postMessage from the iframe
- Replay queued expressions when the iframe signals readiness

## Step 4: Cleanup

- Remove all diagnostic `console.log` / `print` statements from `index.html` and Dart files
- Remove the hardcoded UUID maps, `expressionToFullName`, and `EVENT_TARGET_UUID` constant
- Remove the now-unused local `runtime.js` from `mobile/web/spline/` (the CDN import is used instead)

## Files Changed


| File                                 | Change                                         |
| ------------------------------------ | ---------------------------------------------- |
| `mobile/web/spline/scene.splinecode` | Replaced with new export from Spline editor    |
| `mobile/web/spline/index.html`       | Rewritten to ~60 lines using `setVariable()`   |
| `mobile/lib/spline_iframe_web.dart`  | Add expression queue + `spline_ready` listener |


