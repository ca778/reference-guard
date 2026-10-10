# 运行、升级、诊断与回滚

## 一键方案

- 启用：start.bat。
- 此次关闭自动识别但保留代理：先 Ctrl+C，再 disable.bat。
- 恢复官方服务直连：先 Ctrl+C，再 restore-original.bat（读取配置，在原插件端口启动未修改的官方 server.py，不启动代理）。
- 检查：check.bat。
- 独立备份：PowerShell `powershell -NoProfile -ExecutionPolicy Bypass -File .\backup.ps1`。

备份保留源码、配置、日志、验收与测试输出；排除 .git、.venv 和递归 backups。备份可能含私人数据，仅保留本机。重建环境使用 requirements-lock.txt。
官方配置测试恢复备份在 backups/日期目录（可能含用户现有凭据，不上传或提交）。

## 官方升级

日常 start.bat 的官方 --check_update=True 保持更新询问；官方源码与插件正常升级。
当前 updater 只同步 server 根目录，独立同级 reference-guard 不在范围内。
实际调用官方 smart_file_sync 在隔离临时目录验证：替换官方 server 文件时，独立同级 guard 哨兵不变。
未为了测试执行真实官方升级，避免无必要修改生产安装。更新可用的证据为源码审计、原参数保留及隔离同步测试。
更新成功官方程序退出，启动器最多重新启动两次，每次重新检查源码及包版本。

启动器使用现有官方环境解释器，不自动升级包（--skip_install=True），避免在测试期间触发环境迁移。
需要升级翻译依赖时，先退出服务，按官方 manage_packages.py/update_packages.py 或原启动流程操作；不要在运行中改环境。
升级后如自动跳页关闭，原翻译请求会透传；明确警告，不静默宣称功能正常。
若任务 API 本身不兼容，处理请求返回明确 502，使用原版启动器回退。

## 兼容性门槛

检查 Server 版本、关键字段/选页配置、server/utils 源码与已安装引擎 Python 源码 SHA-256、包版本。
输出验收记录必须匹配当前指纹；Mono、左右 Dual、交替 Dual 的页面/文字/像素保留均须通过。
链接保留是单独的限制，不能把页面安全 PASS 当成链接 PASS。
启动时检查健康；HTTP 集成验收真实 /translate、配置映射、任务轮询、下载、Range 与 SSE。
未来版本要按顺序运行无成本 pytest/启动检查，再在授权下重新运行最小输出验收及实际 HTTP 集成。
不得仅手改 compatibility.json 声称通过。官方 main 会变化，请在本地保留审计的 commit 与文件哈希；机器相关验收证据不随公开仓库分发。

## 日志与诊断

- logs/guard.log：规则状态、页码、回退、后端失败；不记录文件名、PDF 正文、base64 或凭据。
- artifacts/engine-verification/report.json：真实三模式输出证据与已脱敏引擎日志。
- artifacts/http-verification/report.json：实际 Server 集成证据，官方配置恢复结果。
- artifacts/kgw-detection.json：本地真实 KGW 检测结果。
- /health：由官方服务提供原始版本/输出目录，代理不伪造成功。

端口占用：关闭已有原版/扩展窗口；不要通过查端口杀进程。
Backend unavailable：检查 8891、官方窗口错误、环境路径、接口是否已改变。
FALLBACK：查看 reason，不要强行跳页；扫描/无标题/附录本就不支持自动尾页跳过。
启动失败：最多三次启动，无无限重启；恢复原入口。
官方启动会按自己的 prepare_config_files 逻辑补默认配置字段，这是官方行为；扩展没有改写迁移源码。

## 安全边界

只监听 127.0.0.1，固定 loopback 后端；不支持任意 URL 转发。
官方源码、Zotero XPI、引擎源码、pip.ini 未修改；Zotero 数据目录未写入。
真实 HTTP 测试生成新文件，保留原翻译结果与缓存；不删除任何既有输出。
配置与鉴权请求原样转发，不持久化到扩展配置/文档。
参考文献识别失败只回退请求，后端失败返回错误，绝不报告翻译成功。
