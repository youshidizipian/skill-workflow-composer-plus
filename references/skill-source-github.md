# GitHub 技能源（第三路扫描）

本文件定义 SWC1「技能市场发现」中 GitHub 这一路的扫描口径、检索方法、能力边界与安装流程。
与本地枚举（第一路）、WorkBuddy 市场采样（第二路）并列，构成三路扫描。

## 为什么需要这一路

WorkBuddy 市场与 SkillHub 覆盖的是「已上架」技能，中文语境强，但以下三类只能从 GitHub 拿到：

1. **英文原版技能**：anthropics/skills、obra/superpowers 等官方与高星仓库，更新快于任何镜像；
2. **长尾与实验性技能**：尚未被市场收录、但方法论成熟的仓库；
3. **可审阅的源码**：GitHub 能直接读 SKILL.md 原文，判断技能质量与真实边界，市场页只有摘要。

## 扫描工具

工具：`scripts/gh_skill_index.py`（Python 3，无第三方依赖）

| 命令 | 作用 | 典型 API 消耗 |
|---|---|---|
| `scan` | 扫描种子仓库，把所有 SKILL.md 路径写入本地索引 | 每仓库 2 次 |
| `scan --discover "claude-skills in:name"` | 用仓库搜索发现新仓库并纳入索引 | +1 次搜索 |
| `search "<需求>"` | 按中文意图扩展检索，命中后回读描述 | 仅 raw 读取，不占 API |
| `install --repo R --path P --as N` | 把某个技能整目录装到 `~/.workbuddy/skills/N` | 1~2 次 |
| `stats` | 查看索引新鲜度、仓库清单、限流状态 | 0 |

**默认种子仓库**（可按需增补，写进脚本 `SEED_REPOS`）：
anthropics/skills、obra/superpowers、ComposioHQ/awesome-claude-skills、
alirezarezvani/claude-skills、mattpocock/skills、addyosmani/agent-skills、
Jeffallan/claude-skills、zLanqing/codex-claude-academic-skills

## 检索方法（必须按这个顺序）

1. **中文意图先扩词**：GitHub 技能目录名几乎全是英文，直接用中文检索必然零命中。脚本内置 `LEXICON` 把「写作/文风/去AI味/表格/演示/排版/编排」等映射为英文词根，再匹配路径。
2. **词级优先**：命中叶子目录的整词（`humanizer` 命中 `humanizer/`）得分高于子串命中（`humanizer` 命中 `neuronwriter-automation/`）。
3. **噪音惩罚**：`-automation`、`composio-skills/`、`-mcp` 这类 API 连接器壳不是方法论技能，已内置负分。**人工复核时仍要再筛一遍**——它们描述里常带 "Always search tools first for such schemas"，属工具壳而非知识技能。
4. **描述层复核**：路径命中的候选必须回读 SKILL.md 头部再判断；只凭目录名不构成证据。
5. **零命中时如实说零命中**：脚本会打印「当前语料没有直接命中」，此时**不得**把 star 兜底结果包装成匹配结果；应提示用户换关键词或跑 `--discover` 扩语料。

## 能力边界（硬约束）

- **匿名限流**：核心 API 60 次/时，仓库搜索 10 次/分。设置 `GITHUB_TOKEN` 或 `GH_TOKEN` 后升到 5000 次/时。
- **GitHub 代码搜索必须带 token**（匿名返回 401）。因此**不要**用 `search/code` 找 SKILL.md，只用仓库搜索 + tree 枚举，这是本方案能匿名跑通的前提。
- **大仓库文件树可能被截断**：索引里 `truncated=true` 的仓库结果不完整，必须在展示时标注。
- **索引有 7 天 TTL**：过期或用户说「市场更新了」时强制 `scan --refresh`。搜索结果**不跨会话当作事实**，引用前看 `stats` 的新鲜度。
- **技能描述一律来自实际返回**：索引与描述均为抓取所得，严禁补写或推断技能能力。

## 安装流程（从 GitHub 落到本地可编排）

```
python scripts/gh_skill_index.py search "<需求>"        # 1. 找到候选
python scripts/gh_skill_index.py install \
  --repo owner/name --path skills/xxx --as xxx          # 2. 装到 ~/.workbuddy/skills/xxx
```

安装后该技能即进入第一路（本地枚举）的清单，可参与 L1 加载编排。**安装前必须做三件事并向用户说明**：

1. 读一遍 SKILL.md 与 `allowed-tools`，标注它会动哪些能力（写文件 / 执行命令 / 联网）；
2. 若技能目录含 `scripts/`，声明脚本会在本机执行——用户明确同意后才装；
3. 目标目录已存在时脚本默认拒绝覆盖，需 `--force`，覆盖前先确认是否要保留旧版。

## 已知偏差（诚实记录，勿掩盖）

- **语料偏工程**：高星仓库以软件开发方法论为主，中文写作类（去 AI 味、公众号腔、公文腔）在 GitHub 上本就稀有，命名也散（humanizer / natural / voice / no-slop 各路叫法不一），容易被漏检。
- **中文写作类需求，优先顺序应为**：WorkBuddy 本地已装 > WorkBuddy 市场 / SkillHub > GitHub。GitHub 这一路的价值在「读原文、找方法论、拿官方原版」，不在「覆盖中文场景」。
- **Composio 系仓库条目占比高**（864/1532），检索时必须靠惩罚项与人工复核双保险。
