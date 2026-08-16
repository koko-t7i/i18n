# i18n

一个为 Claude Code 打造的 agent 技能，用于翻译文档与 i18n 资源文件。

翻译由子代理完成；脚本负责一切必须确定性的环节——分块、增量缓存、布局解析、链接重写与结构校验。
不涉及任何翻译 API，也不需要任何 API 密钥。

## 覆盖范围

| 类别 | 格式 |
|---|---|
| 文档 | `.md`、`.mdx`、`.markdown` —— README、`docs/**`、`SKILL.md` |
| 资源文件 | `.json`、`.yaml`/`.yml`、`.properties`、`.po`/`.pot` |

不覆盖：源码注释、嵌在源码里的用户可见字符串，以及文档站配置（`mkdocs.yml` 的 nav、`docusaurus.config.js`）。
Docusaurus 的绕行方式见 `i18n/references/resources.md`。

## 安装

```bash
git clone <this repo> ~/icode/skills/i18n
cd ~/icode/skills/i18n
git submodule update --init --depth 1          # fetches the vendored translator
ln -s "$PWD/i18n" ~/.claude/skills/i18n
```

需要 `PATH` 中有 [`uv`](https://docs.astral.sh/uv/)。不会做任何全局安装；`run.sh`
会在首次运行时把依赖解析进 uv 的缓存（第一次下载量较大）。

## 使用

用日常语言提出即可——「把 README 翻译成中文」「同步日文文档」「检查译文是否还与原文一致」。
也可以直接驱动脚本：

```bash
S=~/.claude/skills/i18n/scripts

$S/run.sh plan  --root . --lang zh-CN --paths 'README.md' 'docs/**/*.md'
#   ... a subagent translates each file in .i18n/work/<run>/tasks/ ...
$S/run.sh apply  --root . --run <run_id>
$S/run.sh verify --root . --lang zh-CN
```

| 命令 | 用途 |
|---|---|
| `plan` | 扫描、检测布局、与状态比对、产出子代理任务 |
| `apply` | 重组结果、修复 CJK 强调语法、重写链接、写入文件 |
| `verify` | 结构门禁；出现任何阻断项即以 1 退出 |
| `resource {plan,apply,verify}` | 键值文件的处理路径 |

常用参数：`--detect-layout-only`、`--all`（忽略缓存）、`--force`（覆盖人工编辑过的译文）、
`--layout` / `--layout-pattern`、`--repair <verify.json>`、`--json`、`--strict`、`--run-review`。

## 它会在你仓库里创建的文件

| 路径 | 是否提交 | 用途 |
|---|---|---|
| `.i18n/state.json` | **是** | 翻译锁文件：源文件哈希与分块缓存 |
| `.i18n/glossary.json` | **是** | 术语表，如果你用的话 |
| `.i18n/work/` | 否 | 每次运行的临时目录；加进 `.gitignore` |

## 工作原理

Markdown 分块、代码块保护与重组来自
[Azure/co-op-translator](https://github.com/Azure/co-op-translator)（MIT 许可），以 submodule
形式引入并锁定在 commit `f4f4b11`（v0.20.0）。它的 `start_markdown_agent_translation` /
`finish_markdown_agent_translation` 这一对接口正是为这种形态设计的：宿主 agent 提供译文，
上游负责机械性工作。代码块在任何模型看到文本之前就已被替换成
`@@CODE_BLOCK_n@@` 标记，因此不可能被破坏。

**PyPI 上的发布版无法使用。** 0.18.2 并未包含该 API——它的 entry points 只有
`translate`、`evaluate`、`migrate-links`。这正是锁定 submodule 的原因。

本仓库补齐了上游未覆盖的部分：

- **布局** —— 上游一律写入 `translations/<lang>/`。本技能会检测仓库既有的约定
  （`README.zh-CN.md`、`docs/zh-CN/`、`README_CN.md` 等）并沿用它，同时重写相对链接以保持一致。
- **CJK 强调语法修复** —— 上游会在 CJK 目标语下静默地把 `**加粗**` 改写成 `<strong>加粗</strong>`
  （拉丁语系目标语不受影响，且 `warnings` 返回为空）。`apply` 会把它改回来，
  但仅限于源文档自身未使用的标签。
- **增量缓存** —— 以每个分块的源文哈希为键，因此未改动的分块永远不会送到子代理，
  且重新分块后复用依然有效。
- **校验** —— 行内代码一致性、占位符多重集、HTML 标签对等、代码围栏内容、链接 URL、
  标题层级序列、术语表合规性。
- **资源文件** —— JSON/YAML/properties/PO，写入前强制校验键集一致。

## 开发

```bash
python3 -m unittest discover tests -v     # standard library only, no install needed
```

升级到更新的上游版本：

```bash
git -C vendor/co-op-translator fetch --depth 1 origin main
git -C vendor/co-op-translator checkout <new-sha>
git add vendor/co-op-translator && python3 -m unittest discover tests
```

之后请重跑端到端冒烟测试——CJK 修复与分块契约都依赖上游的具体行为，
而这些行为并不在上游自身的 API 保证范围内。

## 许可

MIT。`vendor/co-op-translator` 为 MIT 许可并保留其自有的 `LICENSE`。
