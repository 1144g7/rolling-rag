## 字段定义

### 必填字段
- subject: 语义主体（见subject规则）
- predicate: 动词/动词短语
- content: 完整自然语言描述，独立可理解
- type: 信息类型（见type分类规则）
- origin: 直接来源（见origin规则）
- origin_generator: human/system/mixed/institution
- verifiability: 0.0-1.0
- logic_strength: 0.0-1.0
- source_credibility: 0.0-1.0
- source_l1_indices: 来源L1序号列表

### 选填字段
- object: 动作对象（可null）
- time_event: 事件时间（无则null）
- location: 信息产生的场景或环境（"与Claude对话"、"公司会议"、"看B站视频"等，无明确场景则null）
- time_sensitivity_days: 时效性
  - 用户当前收入/职业/住址 → 90
  - 性格分析/心理模式 → 180
  - 历史事实/定义/方法论 → null（永久有效）

### 三个子分数
verifiability（可验证性）
  0.9+ = 可查证的客观数据（日期、数字、公开信息）
  0.6 = 可间接验证
  0.3 = 纯主观判断

logic_strength（论证强度）
  0.9+ = 有明确证据链或一手经历
  0.6 = 有道理但论证不充分
  0.3 = 空口断言或纯猜测

source_credibility（来源可信度）
  0.9+ = 一手经验/权威机构
  0.6 = AI分析/有专业性的博主
  0.3 = 匿名/未经验证

### 不需要输出的字段（系统自动处理）
- tags: 系统从源L1自动继承
- time_observed: 系统自动填充对话时间
- confidence: 系统从三个子分数自动计算
