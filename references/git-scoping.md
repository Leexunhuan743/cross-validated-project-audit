# Git 范围与拓扑命令字典

**按需读取**：审计对象是 Git 分支、PR、commit、指定作者提交、工作区，或 Git-backed 修复批次，且需要把候选范围解析成不可变 commit 时读本文件。非 Git 工件不读。

本文件只是**命令字典**。范围来源优先级、历史成立与当前状态的区分、Provenance 判定、supersession 规则都在 [../SKILL.md](../SKILL.md) 里（分别见 §3 步骤 1、§3 步骤 3、§6、§5），本文件不重复。

贯穿全文的一条：分别报告**历史拓扑**、**审查补丁**和**最终树状态**，不用其中一个替代另外两个。三者能对不上，且对不上的地方常常正是缺陷所在。

## 派发前预检

```bash
git rev-parse --show-toplevel
git branch --show-current
git status --short
git worktree list --porcelain
git for-each-ref --format='%(refname:short)' refs/remotes/
```

不要 `clean`、`stash`、`reset`、覆盖式 `checkout` 或删除工作区——已跟踪修改、暂存修改、未跟踪文件和其他 worktree 都是用户数据。默认不输出 `git remote -v` 或原始 remote URL；确需检查远端配置时，落盘前移除 userinfo、令牌和敏感查询参数。

派发前确认：目标 refs 可解析为 commit；base/head 与用户或 PR 元数据一致；范围不是因坏 ref 或错误比较方式意外为空；目标 worktree 与用户指定工件一致；本地脏状态既不会被误算进 PR、也不会被审计操作覆盖。

范围为空时区分"确实无内容 / 补丁已等价合入 / head 已是 base 祖先 / 比较方式错误 / 目标 worktree 错误"，不把空输出直接当结论。shallow clone 或缺对象导致 `merge-base` 失败时，回退到平台 PR 元数据或补丁并显式记录；无法解析的拓扑列为残留缺口，不推断。

## 模糊范围：先枚举候选，不要静默取数字

对"最近的提交""最近改的代码""近期 PR""这个作者最近的提交"，先枚举最少数量的**自然候选范围**，不要静默解释成"最近 5 个"或"7 天内"。

```bash
git log --format='%H%x09%ad%x09%s' --date=short <candidate-range>
```

询问用户前，给出每个候选范围的 commit 数量、起止时间和简短主题摘要。提交主题只帮助用户理解范围，**不是 Evidence**——最终范围仍要解析成不可变 commit。不同合理范围不会改变核心结论时，取最小可辩护范围并写 `basis=ASSUMED`。

## PR 与功能分支

```bash
git rev-parse <base>^{commit} <head>^{commit}
git merge-base <base> <head>
git log --oneline --decorate <base>..<head>
git diff --stat <base>...<head>
git diff --name-status <base>...<head>
git diff --find-renames=50% <base>...<head>
```

- **三点 diff（`base...head`）** 从 merge-base 起算，通常表示 PR 希望引入的补丁。
- **两点 diff（`base head`）** 比较当前两棵树，表示最终状态差异。
- base 已前进时两者会分叉：审查变更以平台 PR patch 或三点 diff 为主，评估集成状态时才看两点 diff。
- `--find-renames=50%` 是把默认相似度阈值写明。大规模重写会让 rename 检测失真，此时同时看 `--no-renames`，别让启发式把新增/删除藏起来。
- 平台 PR diff 通常不含未提交工作区内容，别把本地脏状态算进 PR。

## 单个 commit、范围与 merge commit

```bash
git show --stat --summary <commit>
git show --format=fuller --find-renames <commit>
git log --oneline --reverse <base>..<head>
```

根 commit 没有父提交，`git show <root>` 已能显示完整补丁——不要解析不存在的 `<root>^`。

merge commit 先问清审合并结果、某一父分支增量还是冲突解决：

```bash
git show --cc --stat <merge>       # 组合视图
git show --cc <merge>
git diff <merge>^1 <merge>         # 逐父对照
git diff <merge>^2 <merge>
```

octopus merge 枚举所有父提交。组合视图与逐父对照都要看：冲突解决缺陷常只出现在其中一个里。

## squash、rebase 与 cherry-pick 等价性

不从 commit 数量或空范围推断内容关系：

```bash
git merge-base <base> <head>
git merge-base --is-ancestor <head> <base>
git diff --stat <base> <head>
git rev-parse <base>^{tree} <head>^{tree}
git cherry -v <base> <head>
git range-diff <old-base>..<old-head> <new-base>..<new-head>
```

- 典型 squash merge 不保留原分支的祖先关系；原范围通常仍非空，但补丁可能已等价进入 base。
- `base..head` 为空通常只是 head 已是 base 祖先或两者相同，**不是** squash 的通用特征。
- `git cherry` 靠 patch-id 识别等价补丁，但对 squash、多提交重排、部分 cherry-pick 和冲突改写会失效——必须回落到 tree diff 和实际行为。
- `range-diff` 比较两轮 rebase/cherry-pick 序列的对应关系，不替代最终 tree diff、测试或运行时验证。

## 指定作者提交

默认按 Git **author identity** 归因，不把 committer、reviewer 或 merge 执行者混为作者。

```bash
git log --format='%H%x09%an%x09%ae' <base>..<head>
git show --format=fuller --find-renames <selected-commit>
```

`--author` 是正则匹配，只能作候选过滤：重名、多邮箱、机器人代提交时必须核对真实 identity，不靠显示名猜测。对命中的每个提交读真实 patch 与父提交关系，并在目标 `head` 上检查当前实际状态。

不得把"该作者改过这个文件"等同于"文件中的所有问题都由该作者引入"。报告列出作者身份、范围、命中提交集合和被排除的歧义 identity。审计"该作者全部历史提交"而仓库过大时，先把时间/分支/版本范围写进 `Audit scope`，无法可靠穷尽就明确标为部分审计。

## 工作区、多 worktree 与未提交状态的身份

```bash
git diff              # 工作区 vs 索引，不含未跟踪文件
git diff --cached     # 索引 vs HEAD
git status --short
git worktree list --porcelain
```

`git diff` 不含未跟踪文件——用户要"全部本地修改"时读取相关未跟踪文件，但不自动 `add`、删除或改名。多 worktree 的分支、HEAD 和脏状态相互独立，所有命令都从目标 worktree 运行。

需要用 `snapshot.kind=git-worktree` 固定未提交的 PRE/POST 状态时，两个时点必须用**同一 scope 与排除规则**生成确定性 manifest：按规范化相对路径排序，逐项记录 tracked/staged/unstaged/untracked/deleted 类型、文件模式或链接类型、内容 SHA-256，并记录排除项及原因；manifest 自身以 UTF-8 LF 序列化后再算 SHA-256。

不跟随 symlink/junction 读取 scope 外内容，不读 `.env`、`credentials` 或项目明确排除的生成目录，也**不得用 `git add`、临时 commit 或写 object database 来换取一个身份**。PRE/POST HEAD 记在 snapshot 的 `base`/`head`——即使两者相同，`initialSha256`/`finalSha256` 仍能证明未提交内容确实发生了转换。manifest 生成后再次检查 scope 文件状态，发生外部漂移就重新固定或接替审计，不沿用旧 hash。

## 子模块、LFS、生成文件与交付卫生

```bash
git diff --submodule=log <base>...<head>
git submodule status --recursive
git lfs ls-files
git diff --check <base>...<head>       # 冲突标记 / 空白错误
git diff --numstat -- <path>           # 二进制/大文件变更
```

先看 `.gitattributes` 再判断 LFS；没有 Git LFS 就记未验证，不安装。子模块 pointer 变化要核对目标 commit 可获取、来源可信、上层代码兼容。

核对计划/提交集合与变更文件是否一致：遗漏文件、杂散文件、冲突标记、patch 标记、vendor 修改、lockfile/workspace、导出表、生成物、`.gitignore`。生成物若应提交就确认与源文件同步，若不应提交就确认没污染交付树。无法逐行审查的二进制/大文件变更列为残留缺口——不默认跳过，也不默认放行。

## 基线归因

涉及"以前是否如此"时读基线版本：

```bash
git show <base>:<path>
git blame <head> -- <path>
```

`blame` 只定位历史线索，**不判断责任**。这里只负责收集 base/head、历史实现、可达性和增量影响的 DIRECT Evidence；Provenance 分类由 §6 的唯一规范定义裁决，本文件不重复枚举语义。
