# Issue tracker: GitHub

本仓库使用 `ilksese/babanongchang` 的 GitHub Issues 管理规格与任务。
所有 GitHub 操作使用 `gh` CLI，并显式指定仓库。

## 操作约定

- 创建：`gh issue create --repo ilksese/babanongchang --title "..." --body-file <path>`。
- 读取：`gh issue view <number> --repo ilksese/babanongchang --json number,title,body,labels,comments`。
- 列表：`gh issue list --repo ilksese/babanongchang --state open --json number,title,body,labels`；按需添加标签筛选。
- 更新正文：`gh issue edit <number> --repo ilksese/babanongchang --body-file <path>`。
- 评论：`gh issue comment <number> --repo ilksese/babanongchang --body-file <path>`。
- 标签：使用 `gh issue edit` 的 `--add-label` 和 `--remove-label`；标签映射见 `triage-labels.md`。
- 关闭：先评论说明结果，再运行 `gh issue close <number> --repo ilksese/babanongchang`。
- 多行正文或评论写入临时文件后通过 `--body-file` 传入。

## 规格、任务与依赖

- 规格作为父 Issue，实现任务各自创建独立 Issue。
- 优先使用 GitHub 原生子 Issue 和依赖关系。
- 当前 CLI 或仓库不支持原生关系时，在子任务正文顶部写
  `Part of #<parent>` 和 `Blocked by: #<number>, #<number>`，
  并在父 Issue 的任务列表中链接子任务。
- 所有阻塞任务关闭后，任务才可开始。

## 技能接口

- 技能要求“发布到 Issue Tracker”时，创建或更新 GitHub Issue。
- 技能要求“获取相关任务”时，读取对应 Issue 及其评论。
- PRs as a request surface: no.

## Wayfinder

- Map：使用标记为 `wayfinder:map` 的父 Issue，记录 Notes、
  Decisions-so-far 和 Fog。
- 子任务：关联到 Map，使用 `wayfinder:<type>` 标签；
  type 为 research、prototype、grilling 或 task。
- Frontier：按 Map 中的顺序选择未关闭、无未关闭阻塞项且未分配的子任务。
- Claim：开始工作前，通过 `gh issue edit` 将任务分配给 `@me`。
- Resolve：评论记录结果，关闭任务，并在 Map 的 Decisions-so-far
  中追加结论摘要和链接。

## 本地文件与 Git 边界

- 规格与任务以 GitHub Issues 为准，不再使用 `.scratch/` 管理任务。
- 本地临时规格、计划及任务文件不加入暂存区或提交。
