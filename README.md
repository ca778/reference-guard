# Reference Guard

面向 Zotero PDF2zh 的独立本地代理：保守识别纯参考文献页，将页码选择传给官方翻译引擎，并保留未翻译页面。支持参考文献后仍有附录的文档。

这是独立扩展，不是官方插件或官方 Server 的替代品。检测失败时保留原始翻译请求。

## 安装与启动

推荐 Windows、Python 3.12 和 uv。先按上游说明安装并验证官方 Zotero PDF2zh Server。
建议目录结构：

```text
pdf2zh/
  server/                 # 官方 Server，独立安装
  reference-guard/        # 本仓库
```

1. 将仓库克隆到独立目录，运行 `install.bat`，建立本项目的 `.venv`。
2. 默认 `server_dir = '../server'`，相对于扩展目录解析。默认使用官方目录下已有的 `zotero-pdf2zh-next-venv` 解释器。
3. 其他目录结构使用本机 `config.local.toml` 覆盖 `server_dir`、`server_python` 等选项；该文件被 Git 忽略。公开的 `config.toml` 不应填写私人路径或凭据。
4. 关闭已有原服务窗口，运行 `start.bat`，等待“就绪”。Zotero 插件地址保持 `http://127.0.0.1:8890`，引擎选择 `pdf2zh_next`，手动跳过末尾页数设为 `0`。
5. 保持启动窗口开启。任务完成后 Ctrl+C 退出。

启动器负责官方服务 8891 与代理 8890。端口冲突时退出，不结束占用端口的其他进程。
相对路径配置不依赖当前终端目录；机器本地覆盖文件不要上传。

## 新安装的安全门槛

仓库不附带用户 PDF、凭据、日志或机器相关的兼容性验收记录。
因此新克隆默认不会凭空宣称自动跳页已经通过验收：未通过门槛时明确警告并透传原请求。

无费用检查：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe inspect_pdf.py "paper.pdf"
.\.venv\Scripts\python.exe launcher.py --check
.\.venv\Scripts\python.exe launcher.py --no-update --smoke-seconds 2
```

测试中的官方更新同步检查需要已安装的官方 Server；没有该安装时该项会明确跳过。其余检测和模拟 HTTP 测试不需要翻译服务。
确认本机翻译服务配置后，可**自行明确授权费用**并运行最小真实输出验收：

```powershell
.\.venv\Scripts\python.exe verify_outputs.py --allow-api
```

该命令会发送独立夹具的一页正文至已配置的 DeepSeek 服务，可能产生费用。
只有页面数量、文本、版式和像素验证通过，才写入本机兼容性记录。
`integration_check.py` 也是可能付费的开发工具：真实调用官方服务，先备份配置、测试后恢复，不能与用户翻译并行运行。
不要手工伪造验收结果或复制其他机器的兼容性记录。

## 检测规则与标题

BODY、MIXED、UNKNOWN 都参与翻译。只排除有标题与连续文献证据支持的 REFERENCES_ONLY 页，永不跳过整个 PDF。
混合页整页仍翻译，不做页内段落保护。参考文献后的附录继续翻译；遇到未知页面或新正文后结束该文献段的连续性，不将后续含年份的正文误当参考文献。扫描件、无标题和无法解释的文本保留翻译。

内置标题：References、Reference、Bibliography、Works Cited、Literature Cited、Reference List、List of References、Cited References、References Cited、Literature References、Cited Literature、Bibliographic References、Bibliography and References、References and Bibliography、参考文献、引用文献、文献目录。
支持章节编号、大小写、多个空格及末尾句点/冒号。必须结合独立标题行、字体、坐标、文献条目、年份与跨页连续性，正文出现同名单词不触发。

额外标题可以在本机配置中声明文字别名：

```toml
reference_heading_aliases = ["Selected Literature"]
```

别名按字面匹配，不解释为正则。Notes、Endnotes、Sources、References and Notes 可能包含正文说明，默认不自动跳页。
UNKNOWN 不视为纯文献。HIGH 是规则证据等级，不是经统计校准的概率。
公开结果页码从 1 开始；内部索引从 0 开始。

## 请求与输出

- `/translate`、`/compare`、`/crop-compare` 从原文开始翻译时执行相同的页码保护。检测异常保留原请求。
- `/crop` 只裁剪，不调用翻译引擎。对已经翻译的双语附件做对照或裁剪，不会撤销原有翻译；需要从原文重新执行才能保护参考文献。
- 手动 `skipLastPages > 0` 优先，连同 `onlyIncludeTranslatedPage` 原值保留。手动模式若只包含翻译页为 true，原引擎可能裁掉尾页，日志会显示该选项。
- 新启动器通过独立的内存适配器使用 `--pages` 支持中间文献段，例如 `1-10,15-27`；强制 onlyIncludeTranslatedPage=false。官方文件不改写。旧后端仅支持末尾 skipLastPages。
- 四个入口均沿用原任务、附件下载及进度协议。裁剪采用保守版式判断：单栏整页处理；仅无跨中线文字且有可靠双栏证据时分栏，裁剪留白不移除文字。
- 其他路由透明转发；SSE 与下载流式处理，支持 Range/HEAD，保留任务 ID 和同步/异步响应。
- 因官方共享配置文件，处理任务串行提交；状态查询、SSE 和下载并行。长任务排队可能超过客户端自身超时。
- 默认请求上限 256 MiB、待解析 PDF 128 MiB、2000 页、检测 30 秒。JSON/base64 请求需要有界缓存，下载和 SSE 使用流式背压。
- 固定 loopback 后端，不支持任意 URL 转发。检测不外发 PDF，翻译仍沿用用户选择的官方服务。

## 验证范围与已知限制

开发环境已验证 Server 4.1.7、pdf2zh_next 2.9.0、BabelDOC 0.6.2 的最小实际翻译。
Mono、左右 Dual、交替页 Dual 的尾页内容、DOI 字符、尺寸和像素保留通过；Zotero 实际生成的 Mono/左右 Dual 附件也已核对。

当前引擎在测试中丢失可点击 URI 链接注释，DOI 文本仍在。本扩展不进行链接注释修复。
四路由输出验证与最终 Zotero 附件验收分开记录；原先的裁剪/compare 模式未验收，不能将旧验证推广到这些入口。
0.2.0 已用 SiliconFlowFree 对独立真实论文夹具执行四入口验证，正文/附录翻译、参考文献原文与单栏排版通过；修改后的 Zotero UI 尚未重新执行。详见 [四入口修复验收](docs/FOUR_ROUTES.md)。
旧版本遇到后续附录会关闭整份文档的跳页；0.2.0 改为只排除已确认的文献页，保留后续正文翻译。
本机验收证据留在忽略的 artifacts/ 中，不分发真实科研论文。新环境需要独立重验。

## 更新、回退与备份

- `start.bat`：启用独立代理，保留官方源码更新询问。
- `disable.bat`：关闭自动检测，保留代理。
- `restore-original.bat`：先关闭扩展，再在原端口直接启动未修改的官方 Server。
- `check.bat`：查看本机兼容性门槛。
- `backup.ps1`：独立本机备份；备份可能有私人数据，不上传。

官方源码、包版本或协议发生变化时，门槛不匹配会明确关闭自动跳页。
当前更新隔离通过源代码审计及隔离同步测试验证；未承诺对所有未来版本兼容。
启动器不自动升级翻译环境，升级依赖需退出后按上游流程进行。
内存适配器在官方启动块之前挂接选页和裁剪，官方升级逻辑仍执行。兼容性门槛不通过时启动原后端并明确关闭自动保护；可用 restore-original.bat 回到完全原生流程。Windows exe 引擎的中间页选择未验证，会明确拒绝该自动选页请求。

## 发布与隐私

源码、无凭据的默认配置、依赖、脚本、测试与通用文档进入 Git。
私人路径放入 config.local.toml；PDF、翻译结果、日志、环境变量、虚拟环境、备份和本地验收报告不提交。
历史中的固定本机路径已从公开分支移除；本地旧历史备份仅留本机。

详细说明：[架构](docs/ARCHITECTURE.md)、[运行与回退](docs/OPERATIONS.md)、[安全](SECURITY.md)、[许可与依赖](NOTICE.md)。
