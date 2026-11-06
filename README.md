# skill-workflow-composer-plus

技能工作流编排·多源版：扫描本地已安装技能、WorkBuddy 技能市场与 GitHub 三路来源，按需求组合技能为可执行工作流，并提供跨技能组合灵感建议。

## 致谢与派生说明

**衷心感谢原作者王教成（Wang Jiaocheng / 波动几何）创建并分享 `skill-workflow-composer` v1.0.0。**

本包派生自原作：

- 原技能：`skill-workflow-composer` v1.0.0
- 原作者：王教成 / 波动几何
- SkillHub：`@indiv-wangjiaocheng/skill-workflow-composer`

原包的七域结构、任务清单与范本为本项目奠定了核心基础。尊重原包「不覆盖、不修改原包」的内容权限要求，本项目以独立包名发布，仅新增 GitHub 技能来源及配套脚本，其余域结构与范本沿用原作。

## 主要能力

- 三路技能来源扫描：本地、WorkBuddy 技能市场、GitHub
- 三层技能组合：会话内编排（L1）、定时自动化（L2）、流程沉淀复用（L3）
- 跨技能组合灵感建议与可行性校验
- 中文需求扩词检索、GitHub 技能索引与安装辅助

## 安装

将完整目录放入 WorkBuddy 用户级技能目录：

```text
~/.workbuddy/skills/skill-workflow-composer-plus/
```

确保 `SKILL.md` 位于该目录根部，并保留 `references/`、`scripts/` 与 `templates/` 的目录结构。

## 依赖

- WorkBuddy 平台能力
- Python 3（仅使用标准库）

详细用法、任务拓扑与输出规范请参阅 `SKILL.md` 和 `references/`。
