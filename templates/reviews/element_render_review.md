# 元素渲染审核清单

审核对象：

- `render_preview.png`
- `visual_draft.png`
- `scene.json`

输出：`element_review.yaml`

检查项：

- 元素版页面是否接近已通过的视觉稿？
- 标题、正文、标签是否清晰可读？
- 坐标、层级、间距是否稳定？
- 元素是否适合按旁白逐步动画？
- 是否有遮挡、溢出、错位？

状态：

- `approved`: 进入语音和动画阶段。
- `revise`: 修改 `scene.json`。
- `rejected`: 回到视觉稿阶段。

