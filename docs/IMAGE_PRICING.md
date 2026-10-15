# 图片输入计价核验（0.1.4）

核验日期：2026-10-15。精确模型：`gpt-6.1-sol`、`gpt-6-astra`、`gpt-6-luna`。各模型页确认图片仅输入、文本输出，沿用其 Standard 短上下文及长上下文费率，不对未核验模型推断别名。

官方 [图片指南](https://developers.openai.com/api/docs/guides/images-vision#calculating-costs) 说明，视觉图片先转换为可计费输入 Token，随后应用模型输入价格。图片系数用于从尺寸换算 Token，不能再次作用于日志 Token 或价格。本文不计算图片尺寸、patch 或 detail，也不读取图片内容。

官方 [用量字段](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/completions) 确认 input_tokens 包含文本、图片以及缓存子项，input_cached_tokens 包含图片缓存。[缓存指南](https://developers.openai.com/api/docs/guides/prompt-caching) 的费用公式使用输入减缓存读取与写入后再分项计价。因此图片与文本混合时不需要拆出图片数量，仍可按已核验类别计价一次。

精确模型页：[Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol)、[Astra](https://developers.openai.com/api/docs/models/gpt-6-astra)、[Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)。超过 272,000 输入 Token 时对整次请求使用长上下文费率，图片计入该输入总量。核验没有改变各模型费率。

Codex 公开源码 `codex-rs/codex-api/src/sse/responses.rs` 的 `From<ResponseCompletedUsage> for TokenUsage` 将 API 的 input_tokens、cached_tokens 原样映射到日志计数，没有减掉图片或再次换算。官方版本及函数摘要见 image-pricing-evidence.json。

价格表对每个模型显式声明 imageInputPricing=included-in-input-tokens，缺少策略则不定价图片请求。解析器 5 会重建旧的模态缓存，仅把 input_image 视为可核验图片输入。音频、图片输出、video、不明 image 仍不定价；混合模态保持严格状态，直到明确压缩替换历史。未知版本、缓存分类缺失、身份冲突等其他错误不会被图片规则放行。

不包含独立图片生成或编辑工具费用、音频费用、搜索与其他工具费用、存储、地区附加费、税费、订阅费。金额始终是 API 等价估算，并非 Codex 订阅实际扣费。日志不提供图片的独立 Token 明细，因此不展示虚构的图片单独金额。

使用合成夹具验证图片输入、缓存、长上下文阈值及混合媒体。真实日志的数字交叉核验结果只保留本机，不随源码或发布包分发。
