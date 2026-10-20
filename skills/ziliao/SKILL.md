---
name: ziliao
description: 查询本机资料库插件中的开源项目、AI 新闻和 GitHub 榜单。用户要找项目、看新闻、看日榜周榜月榜、打开资料库，或提到资料库插件时使用。
---

# 资料库

资料先从 https://www.pomi.me 更新到本机，再在本机查询。不要另外打开网页，也不要自己抓 GitHub。用户要看资料库时运行 `python ziliao.py open`，那是客户端窗口，下载按钮只出现在这个窗口里。窗口开着时每 30 秒对照公网，有变化就重新载入。

脚本和本说明在同一目录，文件名是 `ziliao.py`。用本说明文件所在目录运行它，不要到当前项目里另找一份。多个 AI 软件共用用户主目录下的 `.ziliao`。

查询前先运行 `python ziliao.py status`。

- `needs_update` 为 true：运行 `python ziliao.py update`。更新时不要换话题，也不要让用户离开正在看的内容。本机已有资料时，先用现有资料回答，更新完成后再用新结果。
- 公网暂时连不上、但 `ready` 为 true：直接查本机资料。
- 不要向用户索要账号或密码。

搜索只返回少量结果，不要把整份资料读进对话。

```text
python ziliao.py search 关键词 --limit 8
python ziliao.py search 关键词 --group AI专项 --limit 5
python ziliao.py card owner/name
python ziliao.py news --days 7
python ziliao.py ranks --board ai --period daily --limit 10
```

`--group` 可以填专栏、二级分类或三级分类。榜单 `--board` 用 `github` 或 `ai`，`--period` 用 `daily`、`weekly` 或 `monthly`。

用返回的中文名、摘要、分类、星标和链接回答。用户要某一条的细节时再运行 `card`。资料里没有的内容就说没有，不要补编。
