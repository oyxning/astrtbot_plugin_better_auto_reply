# -*- coding: utf-8 -*-

import asyncio
import json
from pathlib import Path

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import (
    filter,
    AstrMessageEvent,
)
from astrbot.api.star import Context, Star, register

# 插件元数据
PLUGIN_METADATA = {
    "name": "更好的自动回复 (Better Auto-Reply)",
    "author": "LumineStory",
    "description": "主动或被动分析群聊消息，由LLM决定是否回复，并输出思考过程。",
    "version": "0.1.0",
    "repo": "https://github.com/oyxning/astrtbot_plugin_better_auto_reply",
}

# 默认的决策Prompt
DEFAULT_DECISION_PROMPT = """
你是一个名为AstrBot的AI助手的决策核心。你的任务是判断是否应该对用户的消息进行回复。

你需要分析以下信息：
1.  **用户消息**: {user_message}
2.  **是否@机器人**: {is_at}
3.  **历史对话（如果可用）**: {history}

你的决策原则是：
-   **直接提问或指令**: 如果用户明确向机器人提问或发出指令，应该回复。
-   **寻求帮助**: 如果用户表现出需要帮助的意图，应该回复。
-   **闲聊/搭话**: 如果用户只是想闲聊，并且话题有趣或积极，可以考虑回复以增强互动。
-   **无意义或负面内容**: 如果用户消息无意义、含糊不清、是垃圾信息或负面内容，则不应回复。
-   **只是在讨论机器人**: 如果用户只是在第三方视角讨论机器人，而不是直接与机器人互动，通常不需要回复。

请以JSON格式输出你的决策，包含两个字段：
-   `should_reply` (boolean): `true` 表示应该回复, `false` 表示不应回复。
-   `reasoning` (string): 解释你做出这个决策的详细思考过程。

---
用户消息: "{user_message}"
---
你的决策 (JSON格式):
"""

@register(
    PLUGIN_METADATA["name"],
    PLUGIN_METADATA["author"],
    PLUGIN_METADATA["description"],
    PLUGIN_METADATA["version"],
    PLUGIN_METADATA["repo"],
)
class BetterAutoReplyPlugin(Star):
    """
    更好的自动回复插件主类
    """

    def __init__(self, context: Context, config: AstrBotConfig):
        """插件初始化"""
        super().__init__(context)
        self.config = config
        self.enabled = self.config.get("enabled", True)
        self.trigger_keywords = self.config.get("trigger_keywords", [])
        self.decision_prompt_template = self.config.get("decision_making_prompt", DEFAULT_DECISION_PROMPT)
        logger.info(f"[{PLUGIN_METADATA['name']}] 插件已加载。")

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=999)
    async def group_message_handler(self, event: AstrMessageEvent):
        """
        监听群聊消息，使用低优先级（高数字）确保在其他指令插件之后执行
        """
        self.enabled = self.config.get("enabled", True)
        if not self.enabled:
            return
        
        # 检查消息是否@了机器人，或者包含触发关键词
        is_at = event.is_at_or_wake_command
        message_text = event.message_str.strip()
        
        is_triggered_by_keyword = any(keyword.lower() in message_text.lower() for keyword in self.trigger_keywords)

        if not is_at and not is_triggered_by_keyword:
            return

        logger.info(f"[{PLUGIN_METADATA['name']}] 收到潜在相关消息: \"{message_text}\"")
        
        # 停止事件继续传播，因为我们已经接管了处理权
        event.stop_event()

        try:
            # 1. 调用LLM进行决策
            # 暂不处理历史消息，简化初版逻辑
            history = "N/A"
            prompt = self.decision_prompt_template.format(
                user_message=message_text,
                is_at=is_at,
                history=history
            )
            
            decision_response = await self.context.get_using_provider().text_chat(prompt=prompt)
            
            if not decision_response or not decision_response.completion_text:
                logger.error(f"[{PLUGIN_METADATA['name']}] LLM决策调用失败，未返回有效内容。")
                return

            # 2. 解析决策结果
            decision_json_str = decision_response.completion_text
            try:
                # 尝试从Markdown代码块中提取JSON
                if "```json" in decision_json_str:
                    decision_json_str = decision_json_str.split("```json")[1].split("```")[0].strip()
                elif "```" in decision_json_str:
                    decision_json_str = decision_json_str.split("```")[1].strip()
                
                decision = json.loads(decision_json_str)
                should_reply = decision.get("should_reply", False)
                reasoning = decision.get("reasoning", "无思考过程。")
            except (json.JSONDecodeError, IndexError) as e:
                logger.error(f"[{PLUGIN_METADATA['name']}] 解析LLM决策JSON失败: {e}. 原始返回: {decision_json_str}")
                return

            # 3. 输出思考过程和意向到控制台
            logger.info(f"[{PLUGIN_METADATA['name']}] --- LLM 思考过程 ---")
            logger.info(f"[{PLUGIN_METADATA['name']}] 消息分析: {reasoning}")
            logger.info(f"[{PLUGIN_METADATA['name']}] 回复意向: {'是' if should_reply else '否'}")

            # 4. 如果决定回复，则请求LLM生成回复
            if should_reply:
                logger.info(f"[{PLUGIN_METADATA['name']}] LLM 决定回复，正在生成内容...")
                # 这里直接使用 event.request_llm，让 AstrBot 核心处理后续流程，包括对话记录
                yield event.request_llm(prompt=message_text)
            else:
                logger.info(f"[{PLUGIN_METADATA['name']}] LLM 决定不回复。")

        except Exception as e:
            logger.error(f"[{PLUGIN_METADATA['name']}] 处理消息时发生未知错误: {e}")

    async def terminate(self):
        """插件卸载/停用时调用"""
        logger.info(f"[{PLUGIN_METADATA['name']}] 插件已卸载。")
