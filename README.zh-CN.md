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
git clone git@github.com:koko-t7i/i18n.git ~/icode/skills/i18n
ln -s ~/icode/skills/i18n/i18n ~/.claude/skills/i18n
```

只有一个依赖：`markdown-it-py`。`PATH` 中有 [`uv`](https://docs.astral.sh/uv/) 时它会按次提供该依赖、
不做任何全局安装；已经装好该依赖的普通 `python3` 也可以直接用。

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
X-DEADLINK     relative links resolve from the translated file    (warning)
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
| `apply` | 重组结果、归一化锚点、重写链接、写入文件 |
| `verify` | 结构门禁；出现任何阻断项即以 1 退出 |
| `resource {plan,apply,verify}` | 键值文件的处理路径 |

常用参数：`--detect-layout-only`、`--all`（忽略缓存）、`--force`（覆盖人工编辑过的译文）、
`--layout` / `--layout-pattern`、`--state-dir`、
`--repair <verify.json>`、`--json`、`--strict`。

## 工作原理

**代码块在任何模型看到文本之前就已变成 `@@CODE_BLOCK_n@@` 标记**，并在重组时还原。
子代理在物理上无法破坏代码块，它只能破坏那个标记，而这是会被检查的。

最关键的不变式是：**把每个分块原样送回，必须逐字节复现原文。** 测试套件在真实文档、
引用块与列表项内的嵌套围栏，以及一个 4000 词的单段落上都断言了这一点。

`finish` 会拒绝的全部情形——每一种在被替换掉的那套实现里都会静默损坏内容：

| 情形 | 结果 |
|---|---|
| `@@CODE_BLOCK_n@@` 标记被删除、篡改或重复 | 拒绝，文件不写入 |
| 缺少某个分块，或某个分块 id 出现两次 | 拒绝 |

frontmatter 是**就地编辑而非重新序列化**：原始块逐字保留，标量值按行替换，
因此注释、键顺序与引号风格全部存活。多行值完全不动。不经过任何 YAML 序列化器往返。

布局沿用你仓库既有的约定（`README.zh-CN.md`、`docs/zh-CN/`、`README_CN.md` 等）
而非强加一种，并重写相对链接以保持一致。

<details>
<summary>曾经构建于 Azure/co-op-translator 之上</summary>

分块与重组过去来自 [Azure/co-op-translator](https://github.com/Azure/co-op-translator)（MIT 许可），
以锁定 commit 的 submodule 形式引入。为了调用三个函数，它的代价是 **182 个传递依赖包**——
整套 Azure AI SDK、semantic-kernel、openai、numpy——外加一个 20 MB、仅用于图片翻译的字体包。
它还会在 CJK 目标语下静默地把 `**加粗**` 改写成 `<strong>加粗</strong>`，
在占位符丢失时不加警告地丢掉代码块，并通过 `yaml.dump` 摧毁 frontmatter 里的注释。

替换方案的验证方式是：让两套实现跑同一批语料并逐项比对——代码块提取完全一致，
且全部差异都只是那三项被刻意舍弃的上游行为。
</details>

## 已知限制

- **短文档的分块粒度偏粗。** 采用字符预算并倾向于在 H1/H2 处切分，因此一篇短文档就是一个分块——
  改动其中一个词会重译整个正文。缓存的收益体现在长文档和多文件场景。
- **跨文件锚点不会被修复。** 标题翻译后会得到新的 slug；文档内部的 `[x](#frag)` 链接会被自动
  重新指向，但**其他文件**指向某个已翻译标题的链接不会，`verify` 只会告警。
- **mkdocs 的 nav 不做翻译。** 请手工编辑。
- **YAML 需要 `pyyaml`。** 缺少它时资源路径会拒绝运行而不是去手工解析——
  猜错一次就会静默损坏一个配置文件。

## 开发

```bash
python3 -m unittest discover tests -v     # standard library only, nothing to install
```

在一个什么都没装的裸 `python3` 上也能跑：`_md` 会回落到正则 Markdown 扫描器，
四个需要容器内嵌套围栏的测试会自行跳过。提交前请用两种方式都跑一遍：

```bash
uv run --with markdown-it-py python -m unittest discover tests
```

改变分块边界意味着要提升 `i18n/scripts/_job.py` 里的 `CHUNKER_VERSION`。这会让所有已缓存的
分块译文失效，而这是正确的——旧分块器产出的文本可能再也不会出现——并在下次 plan 时显示为 `stale`。

## 许可

MIT。
