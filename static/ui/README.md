# PPT Studio visual layer

This folder is the visual implementation of the function-preserving UI refactor
menu in `docs/plans/full_page_function_preserving_ui_refactor_menu.md`.

## Loading contract

`index.html` loads the files in this order:

1. `fonts.css` — application typography roles.
2. `tokens.css` — the single lavender / near-white / blue / coral token set.
3. `../style.css` — the existing compatibility stylesheet for feature selectors.
4. `components.css` — namespaced Workspace UI primitives and the final visual
   bridge over the compatibility selectors.
5. `../studio_polish.css` — existing interaction polish.

The legacy file remains because feature modules and saved projects depend on its
class names. New visual work belongs in this semantic layer; it must not change
DOM IDs, form names, API paths, script order, or workflow state.

## Page geometry

The two existing page roots keep their IDs and gain semantic hooks:

- `#page-home.wu-page[data-width="working"]` — 1050px working canvas.
- `#page-workspace.wu-page[data-width="wide"]` — 1280px wide workflow canvas.

The same layer is validated at 1440×900, 1024px and a narrow container under
680px. Dynamic dialogs remain feature-owned and receive only the shared dialog
surface, focus and scroll treatment here.
