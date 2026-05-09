"""
全局配置 - 感知引擎 (Perception Engine)
"""
import os
from pathlib import Path

# === 项目根目录 ===
BASE_DIR = Path(__file__).parent

# === 加载 .env（密钥、连接信息等敏感配置）===
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    with open(_env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if key and key not in os.environ:  # 环境变量优先
                    os.environ[key] = value

# === 资源目录 ===
ASSETS_DIR = BASE_DIR / "assets"
SCREENSHOTS_DIR = ASSETS_DIR / "screenshots"
RECORDINGS_DIR = ASSETS_DIR / "recordings"
TRANSCRIPTS_DIR = ASSETS_DIR / "transcripts"
SUMMARIES_DIR = ASSETS_DIR / "summaries"

# === Obsidian输出 ===
OB_DIR = BASE_DIR / "Obsidian"
OB_LOG_DIR = OB_DIR / "日志"

# === 记忆目录（旧路径，保留兼容）===
MEMORY_DIR = BASE_DIR / "memory"
DAILY_DIR = MEMORY_DIR / "daily"
KNOWLEDGE_DIR = MEMORY_DIR / "knowledge"

# === 数据库 ===
DB_PATH = BASE_DIR / "storage" / "engine.db"

# === 后端配置 ===
BACKEND = "gateway"

# llama-swap 统一本地推理入口（热切换，矩阵并发）
LLAMASWAP_URL = os.getenv("LLAMASWAP_URL", "http://127.0.0.1:9999")
LLAMASWAP_MODELS = {
    "strong_text": "qwen3-6-35b-a3b-apex-i-compact",  # Qwen3.6-35B-A3B-APEX-I 17.3G
    "vision": "qwen3-6-35b-a3b-apex-i-compact",       # 同上（+vision）
    "narrative": "qwen3-6-35b-a3b-apex-i-compact",    # 叙事管线
    "timeline": "martha-0-8b-qwen3-5-omni-q6-k",      # MARTHA 0.8B 屏幕采集 +vision
    "batch_index": "martha-0-8b-nothink",              # Martha 0.8B 批量索引（nothink 64K）
    "fast_text": "qwen3-5-9b-glm5-1-distill-v1-q8-0", # Qwen3.5-9B GLM5.1 Distill 9.5G +vision
}

# Gateway 中转站（云端模型）
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:23333")
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "")

# DeepSeek 官方（余额查询等）
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
GATEWAY_PROVIDERS = {
    "zhipu": os.getenv("GATEWAY_PROVIDER_ZHIPU", "zhipu"),
    "newapi": os.getenv("GATEWAY_PROVIDER_NEWAPI", ""),
    "openrouter": os.getenv("GATEWAY_PROVIDER_OPENROUTER", "openrouter"),
    "deepseek": os.getenv("GATEWAY_PROVIDER_DEEPSEEK", "deepseek"),
}

# Gateway模型路由表（仅云端模型）
GATEWAY_MODELS = {
    "embedding": "ollama:qwen3-embedding:4b",
    "ocr": "ollama:qwen3.5:4b",
}

# 搜索混合权重（dense=语义向量，sparse=词频权重，和=1.0）
SEARCH_WEIGHTS = {
    "dense": 0.7,
    "sparse": 0.3,
}

# Ollama（仅 embedding/OCR 直连）
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# === 提示词目录 ===
PROMPTS_DIR = BASE_DIR / "prompts"

# === 模型推理参数 ===
# 采样参数预设（基于 Qwen3.5 官方推荐 + 实测调优）
# 使用方式: Router.chat(..., sampling_preset="structured")
SAMPLING = {
    "think": {"temperature": 1.0, "top_p": 0.95, "top_k": 20,
              "presence_penalty": 1.5, "repeat_penalty": 1.0},
    "default": {"temperature": 0.7, "top_p": 0.8, "top_k": 20,
                "presence_penalty": 1.5, "repeat_penalty": 1.0},
    "structured": {"temperature": 0.3, "top_p": 0.8, "top_k": 20,
                   "presence_penalty": 1.5, "repeat_penalty": 1.0},
    "hightemp": {"temperature": 0.6, "top_p": 0.85, "top_k": 40,
                 "presence_penalty": 1.5, "repeat_penalty": 1.0},
    "l2_t01": {"temperature": 0.1, "top_p": 0.9, "top_k": 20,
               "presence_penalty": 1.5, "repeat_penalty": 1.0},
    "l2_t02": {"temperature": 0.2, "top_p": 0.9, "top_k": 20,
               "presence_penalty": 1.5, "repeat_penalty": 1.0},
    "l2_t03": {"temperature": 0.3, "top_p": 0.9, "top_k": 20,
               "presence_penalty": 1.5, "repeat_penalty": 1.0},
    "l2_probe_hot": {"temperature": 2.5, "top_p": 1.0, "top_k": 100,
                     "presence_penalty": 1.5, "repeat_penalty": 1.0},
    "l2_probe_cold": {"temperature": 0.0, "top_p": 1.0, "top_k": 1,
                      "presence_penalty": 1.5, "repeat_penalty": 1.0},
}

# 上下文窗口 (num_ctx) 默认值
NUM_CTX = {
    "default": 65536,
    "think": 65536,
    "images_4": 32768,     # >3张图
    "images_9": 65536,     # >8张图
    "images_31": 131072,   # >30张图
    "extraction": 131072,  # L1/L2提取
    "analysis": 32768,     # 日志分析/档案填充
}

# Agent 参数
AGENT = {
    "max_steps": 30,
    "default_num_ctx": 32768,
}

# 思考 token 预算（per-request，llama-server 原生支持）
# N>0 = 最多 N token 思考，超出后优雅引导模型结束思考并输出正式回答
# -1 = 不限（深度任务）
THINK_BUDGET = {
    "fast_text": 512,          # 快速聊天，限制思考
    "strong_text": -1,         # 深度任务，不限
    "vision": 1024,            # 视觉描述，适度思考
    "timeline": 256,           # 时间线采集，简短思考
    "narrative": -1,           # 叙事，不限
}

# === 屏幕录制配置（ffmpeg持续存档） ===
SCREEN_RECORDING = {
    "output_dir": str(RECORDINGS_DIR / "archive"),
    "framerate": 2,            # 录制帧率（2fps，流畅回看但文件小）
    "resolution": "2560x1440", # 原始2K分辨率
    "encoder": "av1_nvenc",    # AV1 NVENC硬件编码（RTX 4090 D专用芯片）
    "preset": "p4",            # 编码速度/质量平衡
    "crf": 30,                 # 质量参数（越低越好，30为合理压缩）
    "segment_hours": 1,        # 每小时切一个文件
}

# === AI屏幕分析配置 ===
SCREEN_ANALYSIS = {
    "interval_seconds": 120,        # 每2分钟分析一次
    "buffer_window_seconds": 120,   # 取完整2分钟的帧（与分析间隔对齐）
    "max_keyframes": 20,            # 最多20帧（变化检测后的有效帧，通常远少于原始帧数）
    "min_change_ratio": 0.03,       # 至少3%变化才触发分析（跳过静止屏幕）
    "keyframe_size": (480, 270),    # 关键帧尺寸（~256 token/张，20张≈5120 token）
}

# === 屏幕采集管线配置 ===
# 单帧落盘 + 区域变化检测 + 冷却矩阵 + 异步叙事填充
TIMELINE = {
    "jpeg_quality": 80,                  # JPEG压缩质量
    "idle_threshold_seconds": 3 * 60,    # 3分钟无 keyframe 视为用户离开，暂停采集（与narrative_worker对齐）
    "check_interval_seconds": 0.1,       # 检测tick间隔（0.1秒/10fps，高帧率更好区分视频晃动和切镜）
    "embedding_schedule_hours": [3, 15], # （已弃用，保留兼容）改为积压触发
}

EMBEDDING_BATCH_THRESHOLD = 30  # 积压多少条才触发embedding

# === 滚动压缩配置 ===
COMPRESSION = {
    "mode": "compact",             # "compact"(一次性拼摘要) 或 "progressive"(渐进层叠)
    "token_threshold": 12000,      # 超过此 token 数触发删除原文
    "keep_recent_messages": 6,     # 保留最近 N 条消息（约3轮对话）
    # 预设: "economy"(keep=4,省token) / "balanced"(keep=6,1:1) / "quality"(keep=10,上下文多)
}
DISABLE_EMBEDDING = True  # GPU被占时禁用embedding，search_knowledge降级为文本搜索

# === 屏幕变化检测参数（纯事件驱动） ===
# 5 触发源：按键(Enter/Ctrl+S) / 滚轮停 / SSIM突变 / active→passive 边沿 / 30s兜底
# 1 静态过滤：SSIM > ssim_static 跳过
SCREEN_DETECT = {
    "ssim_static": 0.99,          # SSIM > 此值 → 完全没动，跳过
    "ssim_scene_cut": 0.60,       # SSIM < 此值 → 场景突变（标签切换、应用内切换）
    "scene_cut_cooldown": 3.0,    # scene_cut 最小间隔（防视频连续触发）
    "scroll_end_idle_sec": 0.8,   # 滚轮停止多久算"滚停"事件
    "scroll_end_cooldown": 5.0,   # scroll_end 最小间隔（秒）
    "edge_debounce_sec": 5.0,     # active→passive 边沿截图防抖
    "fallback_interval": 30.0,    # 兜底强制截间隔（秒）
    "detect_width": 640,
    "detect_height": 360,
}

# === 屏幕采集配置 ===
SCREEN_CAPTURE = {
    "interval_seconds": 3,          # 定时截图间隔
    "change_threshold": 0.05,       # 画面变化阈值 (5%像素变化才存储)
    "jpeg_quality": 60,             # JPEG 压缩质量
    "buffer_seconds": 3,            # 环形缓冲保留时长（3秒，仅供 capture_tick 取帧）
    "buffer_fps": 2,                # 缓冲帧率 (2fps, 3s = 6帧 ≈ 16MB)
    "max_storage_mb": 2048,         # 截图最大存储空间 (MB)
}

# === 叙事 worker 配置 ===
NARRATIVE_WORKER = {
    "idle_threshold_sec": 180,      # 用户idle超过此秒数→全速处理积压（默认3分钟）
    "idle_batch_size": 20,          # idle时每次tick处理的最大条数
    "active_batch_size": 3,         # 活跃时每次tick串行处理条数（比1更快消化积压）
    "active_interval_sec": 10,      # 活跃时tick间隔（秒）
    "context_window": 131072,       # 叙事模型的上下文窗口大小 (128K)
}

# === 索引配置（0.8B 屏幕帧索引） ===
BATCH_INDEX = {
    "model": "martha-0-8b-nothink",       # llama-swap 模型ID（nothink变体）
    "batch_size": 8,                      # 每批处理帧数（8帧一组送模型）
    "max_per_tick": 50,                   # 每次tick最多处理帧数
    "idle_threshold_sec": 60,             # 用户idle超过60s才跑
    "resolution": (1280, 720),            # 图片分辨率（720p，能看清文字）
    "jpeg_quality": 85,                   # JPEG压缩质量
    "num_ctx": 65536,                     # 上下文窗口
    "max_tokens": 1024,                   # 最大输出token
    "temperature": 0.1,                   # 低温度，输出稳定
}

# === 键盘感知配置 ===
KEYBOARD_PERCEPTION = {
    "enabled": True,                # 是否启用键盘感知
    "burst_gap_sec": 1.5,           # 超过此秒数没敲键，算一段 burst 结束
    "burst_min_chars": 3,           # burst 最少字符数（少于此数不算 burst）
}

# === 语音感知配置 ===
VOICE_HARVESTER = {
    "disable_model": True,     # 启动时不加载Whisper模型，从GUI手动加载
    "hotkey_mod": None,         # None = 单键触发模式
    "hotkey_trigger": "right alt",  # 按一下开始录音，再按一下停止
    "whisper_model": "deepdml/faster-whisper-large-v3-turbo-ct2",
    "whisper_device": "cuda",
    "whisper_compute": "float16",
    "unload_idle_sec": 180,     # 超过3分钟无操作，卸载whisper释放显存（_idle_monitor 触发）
    "worker_idle_timeout_sec": 120,  # 子进程内部超时：超过2分钟未收到音频任务，子进程自动退出释放显存
                                     # 设为 0 = 禁用子进程超时（永久驻留）
}

# === 上下文配置 ===
CONTEXT = {
    "max_recent_screenshots": 5,    # 上下文中最多带几张最近截图
    "max_memory_results": 10,       # 记忆搜索最多返回几条
}

# === 用户 Profile ===
# 个人档案已迁移到 storage/profile.yaml（分层结构，支持按场景注入）
# 通过 engine.profile 访问，不再使用这里的 dict
PROFILE_PATH = BASE_DIR / "storage" / "profile.yaml"

# === Claim提取配置 ===
CLAIM_EXTRACTION = {
    "chunk_target_chars": 20000,    # 大chunk：35b-a3b 128K上下文，减少切割次数和边界问题
    "l1_model": "fast_text",        # L1用35b MoE，质量远好于4b（幻觉少、SPO完整）
    "l2_model": "strong_text",      # L2用35b MoE，深度分析
    "think": False,                 # 关闭思考，快速输出
    "l2_use_tools": True,           # L2用tool calling模式（思考更短，质量更高）
}

# === 数据导入路径（环境变量可覆盖）===
CLAUDE_EXPORT_PATH = os.getenv("CLAUDE_EXPORT_PATH", str(BASE_DIR / "assets/AIChatData/Claude/extracted_temp/conversations.json"))
GPT_EXPORT_PATH = os.getenv("GPT_EXPORT_PATH", str(BASE_DIR / "assets/AIChatData/GPT/ChatGPT/ChatGPT_ip/20251123/conversations.json"))
GEMINI_TAKEOUT_PATH = os.getenv("GEMINI_TAKEOUT_PATH", str(BASE_DIR / "assets/AIChatData/Gemini/Takeout/我的活动/Gemini Apps/我的活动记录.html"))
WORKBUDDY_HISTORY_PATH = os.getenv("WORKBUDDY_HISTORY_PATH", "")
CLAUDE_CODE_PROJECTS_PATH = os.getenv("CLAUDE_CODE_PROJECTS_PATH", str(Path.home() / ".claude" / "projects"))

# === API 配置（环境变量可覆盖）===
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8900"))

# === Skill 配置（每个AI调用任务一份）===
# 统一管理：输出schema + 采样预设 + 模型类型 + 参数
# 新增skill只需在这里加一条，engine和test共享
SKILL_CONFIGS = {
    "narrative": {
        "model_type": "narrative",        # 对应 GATEWAY_MODELS 里的 key
        "sampling": "structured",          # 对应 SAMPLING 里的 key
        "num_predict": 8192,
        "schema": {
            "type": "object",
            "properties": {
                "narrative_part": {"type": "string"},
                "summary": {"type": "string", "maxLength": 100},
                "flag": {"type": "string", "enum": ["[起始]", "[续写]", "[切换]", "[中断]", "[疑似漏截]", "[疑似重复]", "[看不清]"]},
                "keep_summary_count": {"type": "integer"},
                "keep_keyboard_count": {"type": "integer"},
            },
            "required": ["narrative_part", "summary", "flag"]
        },
    },
}
