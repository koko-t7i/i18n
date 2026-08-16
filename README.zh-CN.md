# i18n

**让译文与原文保持同步，不再悄无声息地腐烂。**

[English](README.md)

一个面向 [Claude Code](https://claude.com/claude-code) 的 agent 技能。子代理负责写译文；
脚本负责一切不能交给模型的事——分块、增量缓存、布局解析、链接重写，以及一道在坏结果进入你的
仓库之前就拦下它的结构门禁。不需要翻译 API，也不需要任何 API 密钥。

## 为什么不直接让模型翻译这个文件？

因为一次性翻译只在当下正确，之后就一直错下去。有三件事会出问题，而且三件都是无声的：

| 失效方式 | 实际会发生什么 |
|---|---|
| **漂移** | 你在 `README.md` 里改了个错别字。`README.zh-CN.md` 描述的还是上个月的行为，而没有任何东西提醒你。 |
| **结构损坏** | 模型把反引号里的参数名翻译了，或者把 `{count}` 渲染成 `{数量}`。文档看上去依然正常；但读者复制过去的命令跑不起来了。 |
| **术语漂移** | 「skill」在这一段是 技能，三段之后又成了 技巧。 |

本技能把这三件事都变成机械可查的：内容哈希发现漂移，校验器在结构损坏时让整次运行失败，
带 `forbid` 列表的术语表钉死译法。

## 快速开始

```bash
git clone --recurse-submodules git@github.com:koko-t7i/i18n.git ~/icode/skills/i18n
ln -s ~/icode/skills/i18n/i18n ~/.claude/skills/i18n
```

需要 `PATH` 中有 [`uv`](https://docs.astral.sh/uv/)。不做任何全局安装；首次运行会把依赖
解析进 uv 的缓存（仅第一次下载量较大）。

然后直接提出需求：

> 把 README 和 docs 翻译成中文

或者自己驱动脚本：

```bash
S=~/.claude/skills/i18n/scripts

$S/run.sh plan  --root . --lang zh-CN --paths 'README.md' 'docs/**/*.md'
#   ... a subagent translates each task in .claude/i18n/work/<run>/tasks/ ...
$S/run.sh apply  --root . --run <run_id>
$S/run.sh verify --root . --lang zh-CN
```

之后再跑 `plan`，凡是源文件未变动的都会被报告为 `up-to-date`。

## 覆盖范围

| | |
|---|---|
| **文档** | `.md`、`.mdx`、`.markdown` —— README、`docs/**`、`SKILL.md` |
| **资源文件** | `.json`、`.yaml`/`.yml`、`.properties`、`.po`/`.pot` |
| **不覆盖** | 源码注释、嵌在源码里的用户可见字符串、文档站配置（`mkdocs.yml` 的 nav、`docusaurus.config.js`） |

对于 Docusaurus，改为翻译 `i18n/<locale>/**.json` —— 那属于资源文件，完全支持。
详见 [`references/resources.md`](i18n/references/resources.md)。

## 「结构对等」具体指什么

校验器会比对原文与译文，任一项不通过即判定整次运行失败：

```
X-INLINE       inline code spans must be byte-identical      `--retries` stayed `--retries`
X-TOKEN        placeholders must match                       {count}, %s, ${VAR}, {{var}}
X-FENCE        fence count, language tags, and bodies        ```bash blocks unchanged
X-HTML         HTML tag multiset must match the source
X-LINK         external URLs verbatim; internal link count
X-HEADING      heading level sequence, element-wise
X-GLOSSARY     required terms present, forbidden ones absent
X-CHATTER      no "here is the translation" preamble
```

`X-INLINE` 是最物有所值的一项。把 `` `{count}` `` 译成 `` `{数量}` `` 能通过其余所有检查，
却会让读者复制走的命令失效。

## 状态文件存放位置

| 路径 | 是否提交 | 用途 |
|---|---|---|
| `.claude/i18n/state.json` | **是** | 翻译锁文件：源文件哈希与分块缓存 |
| `.claude/i18n/glossary.json` | **是** | 术语表，如果你用的话 |
| `.claude/i18n/work/` | 否 | 每次运行的临时目录 |

```gitignore
.claude/i18n/work/
```

> [!IMPORTANT]
> 一种常见的 `.gitignore` 写法是整体拒绝 `.claude/`，再逐个放行特定文件。
> 在这类仓库里，`state.json` 会被静默地排除在版本控制之外，下一次全新 clone 就会把所有内容
> 重新翻译一遍。`plan` 会执行 `git check-ignore` 并对此告警。要么把它放行：
>
> ```gitignore
> !.claude/i18n/
> .claude/i18n/work/
> ```
>
> 要么用 `--state-dir .i18n` 把状态目录挪到 `.claude/` 之外。

## 命令

| 命令 | 用途 |
|---|---|
| `plan` | 扫描、检测布局、与状态比对、产出子代理任务 |
| `apply` | 重组结果、修复 CJK 强调语法、重写链接、写入文件 |
| `verify` | 结构门禁；出现任何阻断项即以 1 退出 |
| `resource {plan,apply,verify}` | 键值文件的处理路径 |

常用参数：`--detect-layout-only`、`--all`（忽略缓存）、`--force`（覆盖人工编辑过的译文）、
`--layout` / `--layout-pattern`、`--state-dir`、
`--repair <verify.json>`、`--json`、`--strict`、`--run-review`。

## 工作原理

Markdown 分块、代码块保护与重组来自
[Azure/co-op-translator](https://github.com/Azure/co-op-translator)（MIT 许可），以 submodule
形式引入并锁定在 commit `f4f4b11`（v0.20.0）。它的 agent-assisted API 正是为这种形态设计的
—— 宿主 agent 提供译文，上游负责机械性工作。代码块**在任何模型看到文本之前**就已变成
`@@CODE_BLOCK_n@@` 标记，因此不可能被破坏。

> **PyPI 上的发布版无法使用。** 0.18.2 并未包含该 API —— 它的 entry points 只有
> `translate`、`evaluate`、`migrate-links`。这正是锁定 submodule 的原因。

本仓库补齐了上游未覆盖的部分：

- **布局检测** —— 上游一律写入 `translations/<lang>/`。本技能改为沿用你仓库既有的约定
  （`README.zh-CN.md`、`docs/zh-CN/`、`README_CN.md` 等），并重写相对链接以保持一致。
- **CJK 强调语法修复** —— 上游会在 CJK 目标语下静默地把 `**加粗**` 改写成 `<strong>加粗</strong>`，
  且 `warnings` 返回为空。拉丁语系目标语不受影响。`apply` 会把它改回来，
  但仅限于源文档自身未使用的标签。
- **增量缓存** —— 以每个分块的源文哈希为键，因此重新分块后复用依然有效。
- **校验** —— 即上文列出的各项检查。
- **资源文件** —— 在写入**之前**强制校验键集一致。

## 已知限制

- **分块粒度由上游决定。** 它按 token 预算分块，因此一篇短文档就是一个分块——改动其中一个词
  会重译整个正文。缓存的收益体现在长文档和多文件场景，而非短文档的小改动。
- **标题翻译后锚点会变。** 当文档链接到自身已不存在的锚点时 `verify` 会告警，
  但跨文件锚点不会被自动修复。
- **mkdocs 的 nav 不做翻译。** 请手工编辑。
- **YAML 需要 `pyyaml`。** 缺少它时资源路径会拒绝运行而不是去手工解析——
  猜错一次就会静默损坏一个配置文件。

## 开发

```bash
python3 -m unittest discover tests -v     # standard library only, nothing to install
```

升级 vendored 的翻译器：

```bash
git -C vendor/co-op-translator fetch --depth 1 origin main
git -C vendor/co-op-translator checkout <new-sha>
git add vendor/co-op-translator && python3 -m unittest discover tests
```

之后请重跑端到端冒烟测试。CJK 修复与分块契约都依赖上游的具体行为，
而这些行为并不在它自身的 API 保证范围内。

## 许可

MIT。`vendor/co-op-translator` 为 MIT 许可并保留其自有的 `LICENSE`。
