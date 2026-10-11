# 初始审计与架构（2026-10-10）

以下记录初始方案；0.2.0 对中间参考文献与四入口的调整见 [四入口修复验收](FOUR_ROUTES.md)。初始尾页验收不代表裁剪/对照入口已通过。

本地实测：Python 3.12.13；Server 4.1.7；pdf2zh_next 2.9.0；BabelDOC 0.6.2。
扩展与官方 server 目录独立；默认通过相对路径定位同级官方 Server，私人路径可使用不提交的 config.local.toml 覆盖。

Server `/translate` 接受 JSON fileContent（可带 data:application/pdf;base64, 前缀）、fileName、engine。
Config 对 skipLastPages 转整数，负数归零；Server 未防止 skip>=总页数，会产生 1-0 等非法范围。
自动检测永不跳过全部页面。用户手动范围保持原样，其边界属于原服务行为。
pdf2zh_next 的 --pages 使用 1 起始且闭区间；内部索引使用 0 起始。
onlyIncludeTranslatedPage 映射至 config.toml 的 [pdf].only_include_translated_page。
Config.update_config_file 在异步工作线程运行，共享配置存在并发覆盖风险；扩展需串行提交翻译/裁剪处理任务直到前一任务结束，轮询和 SSE 保持并行。

当前路由：/、/translate、/crop、/compare、/crop-compare、/translatedFile/<path>、/translatedInfo、/health、/events、/api/history、/api/tasks、/api/config、/favicon.svg、/bo.mp3。
翻译任务后台执行并返回任务 ID；插件轮询任务和下载附件。代理不重写任务响应。

启动参数 --host/--port/--check_update/--skip_install/--enable_mirror 均存在。
auto_update.smart_file_sync 同步 root_path（server）内部文件；独立同级目录不在当前更新范围。
更新成功 SystemExit(0)，启动器最多重启两次，每次重新审计，不无限循环。

方案：独立 aiohttp 流式代理（8890）→ 官方 Server（8891）。PyMuPDF 规则检测。
原生引擎输出经真实测试验证后复用；不修改或拼接已有输出，不修改官方源码/XPI/引擎/pip.ini。
请求 JSON 因 base64 协议需有界缓存；下载和 SSE 流式转发。检测在有超时限制的子进程执行。
源文件/包版本 fingerprint 与输出验收记录共同决定是否启用自动跳页；变化时显著警告并透传原行为。

风险：启发式不可能证明任意 PDF 无正文，故采用严格规则，扫描/无标题/附录/含糊内容默认放弃。
只能跳连续尾页；不能页内保护。未来版本必须重新输出验收，不能宣称永久兼容。
实测最终 Zotero 附件需要用户正常操作插件；只读 Local API 不创建附件。

官方来源（访问日期 2026-10-10）：https://github.com/guaguastandup/zotero-pdf2zh 。
以本地版本与记录的文件哈希为验收基线，不以未来 main 为基线。
