## origin规则（来源标注）

每条L2必须标注两个来源字段：

### origin（直接来源，自由文本但必须标准化）
这条信息是谁提供的/谁说的。
- 对话中用户说的 → origin: "用户"
- 对话中AI说的 → origin: "AI"
- 用户转述第三方 → origin: "用户"（content中标注转述）
- 视频UP主说的 → origin: "UP主名字"（用实际名字）
- 书籍内容 → origin: "《书名》"
- 用户和AI共同推导 → origin: "用户+AI"

**严格规范：**
- "AI"就是"AI"，不要写"AI分析"、"AI建议"、"AI介绍"、"AI (转述用户理论)"
- "用户"就是"用户"，不要写"用户/AI"、"用户/AI分析"
- 具体的分析/建议/介绍等信息在content里体现，不要塞进origin

### origin_generator（标准化分类，四选一）
- human = 用户/人类说的
- system = AI产出的
- mixed = 人机共同得出
- institution = 机构/组织发布的
