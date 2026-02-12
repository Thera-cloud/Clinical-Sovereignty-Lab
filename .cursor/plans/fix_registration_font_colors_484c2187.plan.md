---
name: Fix registration font colors
overview: Fix the dark/invisible text color in the client registration form fields by adding explicit white text styling to all TextFields and the Theme wrapper in _buildForm().
todos:
  - id: theme-fix
    content: Update ThemeData in _buildForm() with textSelectionTheme and hintStyle
    status: completed
  - id: textfield-styles
    content: "Add explicit style: TextStyle(color: Colors.white) to all TextFields in the registration form"
    status: completed
  - id: rebuild
    content: Rebuild Flutter web
    status: completed
isProject: false
---

# Fix Registration Form Font Colors

## Problem

In `_buildForm()` in [mobile/lib/main.dart](mobile/lib/main.dart) (line 4841), the `TextField` widgets don't have an explicit `style:` parameter for text color. While `ThemeData.dark()` is applied, the typed text can still appear dark/invisible on Flutter web.

## Fix

Two changes in [mobile/lib/main.dart](mobile/lib/main.dart):

### 1. Add explicit text style to the Theme wrapper (line 4843)

Update the `ThemeData.dark().copyWith(...)` to include `textSelectionTheme` and ensure the input text style is white:

```dart
data: ThemeData.dark().copyWith(
  inputDecorationTheme: InputDecorationTheme(
    labelStyle: const TextStyle(color: Colors.white70),
    hintStyle: const TextStyle(color: Colors.white38),
    enabledBorder: const OutlineInputBorder(borderSide: BorderSide(color: Colors.white24)),
    focusedBorder: const OutlineInputBorder(borderSide: BorderSide(color: Colors.blueAccent)),
  ),
  textTheme: const TextTheme(bodyMedium: TextStyle(color: Colors.white)),
  textSelectionTheme: const TextSelectionThemeData(
    cursorColor: Colors.blueAccent,
    selectionColor: Colors.blueAccent,
    selectionHandleColor: Colors.blueAccent,
  ),
),
```

### 2. Add `style: TextStyle(color: Colors.white)` to every TextField

Add the explicit style to:

- Full Name field (line 4856)
- Username field (line 4999)
- Password field (line 5001)
- Parent username field (line 4889)
- All W-9 fields in the coach section (lines 4906-4989)

### 3. Rebuild Flutter web

Run `flutter build web` from the `mobile/` directory.