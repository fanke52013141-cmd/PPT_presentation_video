# Known Integration Limit

`static/config_effectiveness.js` is committed in this branch, but it must be loaded by `static/index.html` after `app.js` to take effect.

Required hook:

```html
<script src="app.js?v=2.0.14"></script>
<script src="config_effectiveness.js?v=1.0.0"></script>
```

The branch intentionally avoids a whole-file rewrite of `static/index.html` until the one-line hook can be applied safely.
