MEMORY_UPDATE_PROMPT = """你负责维护 CoCo Code 的长期记忆。

请根据本轮对话和现有索引，判断是否需要创建、更新或删除笔记。
只输出 JSON 数组，不要输出解释文本。不得调用工具。

分类：
- user_preference：跨项目通用的用户偏好
- correction_feedback：用户纠正过的行为或反馈
- project_knowledge：当前项目事实、规范、架构知识
- reference_material：用户提供的参考资料或链接摘要

输出格式：
[
  {"action":"create","level":"project","type":"project_knowledge","title":"...","slug":"...","content":"..."},
  {"action":"update","level":"user","filename":"user_preference_terse_replies.md","title":"...","content":"..."},
  {"action":"delete","level":"project","filename":"project_knowledge_old_api.md"}
]

如果没有值得更新的内容，输出 []。
"""
