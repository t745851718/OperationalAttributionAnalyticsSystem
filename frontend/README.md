# 经营归因分析前端

## 本地启动

在仓库根目录运行以下命令。前端默认将同源 `/api` 转发到 `http://127.0.0.1:8000`。

```sh
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend dev
```

打开 Vite 输出的本地地址。API 模式使用后端账户与角色，见[仓库运行说明](../README.md)。如需更换后端端口，启动时设置 `VITE_API_TARGET`。模型配置只由后端读取。

```sh
pnpm --dir frontend typecheck
pnpm --dir frontend test
pnpm --dir frontend build
pnpm --dir frontend preview
```

部署 `dist/` 时将页面路径回退至 `index.html`，将 `/api` 反向代理到 FastAPI。SSE 路径需要关闭代理缓冲。可以设置 `VITE_DATA_MODE=fixture` 在隔离的本地端口运行固定数据回归，使用 `analyst`、`manager` 或 `admin`，密码为 `demo123`。此选项仅用于离线界面回归。

## 接口适配

- `src/client.ts` 负责 Bearer 请求、会话任务流、报告下载与错误处理。请求参数和权限以[后端接口说明](../docs/backend.md)为准。
- `src/remote.ts` 将后端指标域、统计比例、数据结构和报告章节映射为界面模型。SSE 使用业务任务 ID 和递增事件序号，刷新时重放运行中任务以恢复阶段和假设状态，断开后从已收到的序号继续读取。
- 事件和报告保存至后端。指标依赖关系由后端公式校验，指标字典的可视父级排序保存在本地浏览器。

## 浏览器验收

使用本地 `agent-browser` 检查大盘、GMV 与净利率分析、切片、假设验证记录、情景对比、报告和三种导出。截图见 [docs/screenshots](../docs/screenshots)。
