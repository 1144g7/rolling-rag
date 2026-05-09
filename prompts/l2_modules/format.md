## 输出格式

输出一个JSON对象，包含两个字段：records（L2记录数组）和 feedback（执行反馈）。

```json
{
  "records": [
    {
      "subject": "语义主体（人名/AI/公司名/方法论名）",
      "predicate": "动词短语",
      "object": "对象（可null）",
      "type": "从预设列表选择",
      "content": "完整描述，含来源前缀（用户表示.../AI分析...）",
      "time_event": "事件时间或null",
      "location": "信息产生的场景或null",
      "time_sensitivity_days": null,
      "origin": "用户/AI/具体人名",
      "origin_generator": "human/system/mixed/institution",
      "source_l1_indices": [0, 3, 7],
      "verifiability": 0.8,
      "logic_strength": 0.7,
      "source_credibility": 0.9
    }
  ],
  "feedback": [
    "你在执行过程中的任何反馈、建议、疑问，每条一个字符串。",
    "例如：'建议增加type「问题」，L1中高频出现用户遇到的具体问题，现有type难以归类'",
    "例如：'location字段在纯文字对话中始终为空，是否有必要保留？'",
    "例如：'L1-3和L1-7关于收入的描述矛盾，无法判断哪个正确，已取较新的版本'",
    "没有反馈时输出空数组 []"
  ]
}
```

### feedback说明
这是你向系统反馈的意见箱。在提取记录之前，先做一轮预判反思，提取完之后再补充实际遇到的问题。

**提取前反思（先写进feedback）：**
- 这批L1文本和本系统提示词的匹配度如何？有没有大量无法归类的信息？
- 哪些约束（字段、type列表、红线规则）在这批文本上会造成困难？
- 预判一下可能出错的点（比如：大量对话型内容没有明确主体、时间信息模糊等）

**提取后反馈（追加到feedback）：**
- 哪个字段定义不合理、始终用不上？
- 哪种信息频繁出现但现有type覆盖不了？
- 合并L1时遇到什么困难（矛盾、无法判断对错）？
- 你觉得这套系统哪里可以改进？

任何想法都写在feedback里，我们会参考你的建议迭代系统。
