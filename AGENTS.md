## 经营归因分析系统项目要求

需求文档，说明文档，UI设计都在 docs 中

前端包管理器使用本地的 pnpm

前端项目验证使用本地 agent-browser cli

大模型指定使用
api协议: Anthropic 的 /messages 接口
base_url: https://ws-a0x5jc6dusvyqin7.cn-beijing.maas.aliyuncs.com/apps/anthropic
api_key: 代码读取根目录 .env 环境变量 LLM_API_KEY
model: 代码读取根目录 .env 环境变量 LLM_MODEL