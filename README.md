# Ziliao

让 Codex、Claude Code、Cursor 和 Workbuddy 查询 [资料库](https://www.pomi.me) 里的开源项目、AI 新闻和 GitHub 榜单。

Ziliao syncs the public library at [pomi.me](https://www.pomi.me) onto your machine. A coding agent can then search projects, read recent AI news, and check daily, weekly, and monthly rankings without opening the site or collecting repositories on its own.

## 安装

从 [Releases](https://github.com/zhaokunzhang6-sudo/ziliao/releases/tag/v1.0.0) 下载对应系统的压缩包，解压到任意位置。

- [Windows](https://github.com/zhaokunzhang6-sudo/ziliao/releases/download/v1.0.0/ziliao-windows.zip)
- [macOS](https://github.com/zhaokunzhang6-sudo/ziliao/releases/download/v1.0.0/ziliao-mac.zip)

新开一个对话，把解压后的文件夹路径交给 Codex、Claude Code、Cursor 或 Workbuddy，让它把插件装进当前软件。

装好之后，可以用插件查看资料库，也可以让助手直接读取里面的项目、新闻和榜单。

## 助手怎么查

在插件目录中运行：

```text
python skills/ziliao/ziliao.py status
python skills/ziliao/ziliao.py search 关键词 --limit 8
python skills/ziliao/ziliao.py card owner/name
python skills/ziliao/ziliao.py news --days 7
python skills/ziliao/ziliao.py ranks --board ai --period daily --limit 10
```

`status` 会说明本机资料是否需要从网站更新。搜索只返回少量结果。资料里没有的内容不会编造。

## 数据从哪来

项目、新闻和榜单来自 https://www.pomi.me 。助手先把文本资料同步到本机用户目录下的 `.ziliao`，再在本地查询。
