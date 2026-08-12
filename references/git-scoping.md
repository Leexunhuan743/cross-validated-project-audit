# Git 工件范围界定

只在审计 Git 分支、PR、commit、工作区或修复批次时读取本文件。目标是同时回答两个问题：本次变更引入了什么，以及目标分支与当前工件的最终树状态有什么差异。

## 通用预检

先读取仓库指令，再运行安全的只读查询：

```bash
git status --short
git rev-parse --show-toplevel
git branch --show-current
git remote
git for-each-ref --format='%(refname:short)' refs/remotes/
```

不要清理、stash、reset 或覆盖工作区。把已跟踪修改、暂存修改和未跟踪文件都视为用户数据。

默认不要输出 `git remote -v` 或原始 remote URL；HTTPS URL 可能包含 userinfo、令牌或敏感查询参数。只有任务确实需要检查远端配置时才读取 URL，并在写入日志、共享上下文或报告前移除凭据和敏感参数。

## PR 或功能分支

优先从用户、PR 元数据或托管平台获得准确的 base 与 head。若仍有多个合理基线且选择会改变结果，先询问用户。

```bash
merge_base=$(git merge-base <base> <head>)
git log --oneline --decorate <base>..<head>
git diff --stat <base>...<head>
git diff --name-status <base>...<head>
git diff --find-renames <base>...<head>
```

- 三点 diff（`base...head`）从 merge-base 开始，通常表示 PR 希望引入的变更集。
- 两点 diff（`base head`）比较当前两棵树，表示若把它们视作最终状态时的差异。
- base 已前进时，两者可能明显不同。审计变更本身以三点 diff 或平台提供的 PR patch 为主；评估集成状态时再检查两点 diff。
- 同时检查新增、删除、重命名、mode 变化、子模块指针、LFS 指针、生成文件及未被 diff 捕捉的发布配置。

不要写死 `origin/master`、`origin/main` 或远端名称。不要仅因 `base..head` 为空就判断没有变更。

## 单个 commit 或 commit 范围

审计普通 commit：

```bash
git show --stat --summary <commit>
git diff <commit>^ <commit>
```

根 commit 没有父提交，改用：

```bash
git show --root <commit>
```

审计范围时区分提交集合和补丁范围：

```bash
git log --oneline <base>..<head>
git diff <base>...<head>
```

若用户给出合并 commit，先确认是要审计合并结果、某个父分支的改动，还是冲突解决；不同父提交需要不同 diff。

## 工作区改动

分别检查：

```bash
git diff
git diff --cached
git status --short
```

`git diff` 不包含未跟踪文件。读取与任务相关的未跟踪文件，但不要自动加入、删除或改名。若用户要求审计“全部本地修改”，三类都要覆盖。

## 已合并、rebase 或 squash 的工件

不要从提交数量或空范围推断内容关系。组合使用：

```bash
git merge-base <base> <head>
git merge-base --is-ancestor <head> <base>
git diff --stat <base> <head>
git rev-parse <base>^{tree} <head>^{tree}
```

再结合 PR 元数据、合并方式和实际 tree diff 判断。典型 squash merge 不保留原分支提交的祖先关系；空的 `base..head` 也可能只是 head 已成为 base 的祖先。把历史拓扑与内容差异分别报告。

## 基线归因

候选问题涉及“以前是否如此”时，读取基线版本而不是猜测：

```bash
git show <base>:<path>
git blame <head> -- <path>
```

`blame` 只用于定位历史线索，不用于判断责任。若问题早已存在，但新变更使其可达、扩大影响或阻碍恢复，分别描述既有根因和本次变更的增量影响。
