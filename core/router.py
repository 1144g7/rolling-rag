"""
模型路由器 - 统一入口
本地模型走 llama-swap (统一端口热切换), 云端模型走 Gateway, embedding 走 Ollama
"""
import urllib.request
import json
import asyncio
import time
from typing import Optional, Callable

import config
from core._backend_llamaswap import LlamaswapBackend
from core._backend_gateway import GatewayBackend
from core._embed_ocr import EmbedOCR

# 全局 opener：显式无代理，所有请求直连 localhost
_proxy_handler = urllib.request.ProxyHandler({})
_opener = urllib.request.build_opener(_proxy_handler)


class ModelRouter:
    def __init__(self):
        self.backend = getattr(config, "BACKEND", "gateway")
        # llama-swap 统一本地推理入口
        self.llamaswap_url = getattr(config, "LLAMASWAP_URL", "http://127.0.0.1:9999")
        self.llamaswap_models = getattr(config, "LLAMASWAP_MODELS", {})
        # Ollama（仅 embedding 用）
        self.ollama_url = getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434")
        # Gateway（云端模型）
        self.gateway_url = getattr(config, "GATEWAY_URL", "")
        self.gateway_api_key = getattr(config, "GATEWAY_API_KEY", "")
        self.gateway_providers = getattr(config, "GATEWAY_PROVIDERS", {})
        self.gateway_models = getattr(config, "GATEWAY_MODELS", {})
        self._last_model = None

        # 缓存命中统计
        self._cache_stats = {"total_prompt_tokens": 0, "total_cached_tokens": 0, "requests": 0}

        # 请求追踪：支持按 ID 取消正在进行的推理请求
        self._active_requests: dict[str, "http.client.HTTPConnection"] = {}
        self._request_counter = 0

        # 后端实例
        self.llamaswap = LlamaswapBackend(self.llamaswap_url, self._active_requests)
        self.gateway = GatewayBackend(
            self.gateway_url, self.gateway_api_key,
            self.gateway_providers, self.gateway_models,
        )
        self._embed_ocr = EmbedOCR(self.ollama_url, self.gateway_models)

        # claims 引用（engine 初始化后注入）
        self._claims = None

    # ===== 请求取消 =====

    def alloc_request_id(self) -> str:
        self._request_counter += 1
        return f"req_{self._request_counter}"

    def cancel_request(self, request_id: str):
        conn = self._active_requests.pop(request_id, None)
        if conn:
            try:
                conn.close()
                print(f"[Router/Cancel] 已取消请求 {request_id}")
            except Exception:
                pass

    def cancel_all_requests(self):
        ids = list(self._active_requests.keys())
        for rid in ids:
            self.cancel_request(rid)
        if ids:
            print(f"[Router/Cancel] 已取消全部 {len(ids)} 个请求")

    # ===== 路由入口 =====

    async def chat(self, prompt: str, model_type: str = "fast_text",
                   images: list[str] = None, system: str = None,
                   stream: bool = False, think: bool = False,
                   num_ctx: int = None, num_predict: int = None,
                   format: dict = None, tools: list = None,
                   tool_choice: str = "auto",
                   timeout: int = 300, model_override: str = None,
                   sampling_preset: str = None,
                   sampling_override: dict = None,
                   think_budget: int = None,
                   source_tag: str = "unknown",
                   request_id: str = None) -> str:
        """统一聊天接口"""

        prompt_snapshot = json.dumps({
            "prompt": prompt[:2000], "system": (system or "")[:1000],
            "model_type": model_type, "images": len(images) if images else 0,
            "think": think, "format": bool(format), "tools": bool(tools),
        }, ensure_ascii=False)
        t0 = time.time()

        try:
            use_llamaswap, resolved_model = self._resolve_route(model_type, model_override)

            if use_llamaswap:
                result = await self.llamaswap.chat(
                    prompt, resolved_model, images, system, think,
                    num_ctx, num_predict, format, tools, tool_choice,
                    timeout, sampling_preset, sampling_override,
                    model_type, think_budget, request_id,
                )
                self._update_cache_stats(result if isinstance(result, dict) else {})
                self._log_call(t0, resolved_model, "llamaswap",
                               "vision" if images else "chat", source_tag,
                               prompt_snapshot, result)
                return result

            if self.gateway_url:
                result = await self.gateway.chat(
                    prompt, model_type, images, system, think,
                    num_ctx, num_predict, format, tools, tool_choice,
                    timeout, model_override, sampling_preset, sampling_override,
                )
                self._update_cache_stats(result if isinstance(result, dict) else {})
                self._log_call(t0, model_type, "gateway",
                               "vision" if images else "chat", source_tag,
                               prompt_snapshot, result)
                return result

            raise RuntimeError(f"No route for model_type={model_type}")

        except Exception as e:
            self._log_call(t0, model_type or "", "?", "chat", source_tag,
                           prompt_snapshot, None, error=str(e))
            raise

    async def chat_messages(self, messages: list[dict], model_type: str = "fast_text",
                            tools: list = None, tool_choice: str = "auto",
                            format: dict = None, think: bool = False,
                            num_ctx: int = None, num_predict: int = None,
                            timeout: int = 300, model_override: str = None,
                            sampling_preset: str = None, sampling_override: dict = None,
                            think_budget: int = None,
                            source_tag: str = "agent",
                            request_id: str = None,
                            stream: bool = False,
                            on_thinking: Callable = None,
                            on_text: Callable = None) -> dict:
        """多轮对话接口。接受完整 messages 数组，返回结构化结果。"""

        prompt_snapshot = json.dumps({
            "messages_count": len(messages),
            "model_type": model_type, "think": think,
            "format": bool(format), "tools": bool(tools),
        }, ensure_ascii=False)
        t0 = time.time()

        try:
            use_llamaswap, resolved_model = self._resolve_route(model_type, model_override)

            if use_llamaswap:
                result = await self.llamaswap.chat_messages(
                    messages, resolved_model, think,
                    num_ctx, num_predict, format, tools, tool_choice,
                    timeout, sampling_preset, sampling_override,
                    model_type, think_budget, request_id,
                    stream, on_thinking, on_text,
                )
                self._update_cache_stats(result)
                self._log_call(t0, resolved_model, "llamaswap",
                               "agent_stream" if stream else "agent", source_tag,
                               prompt_snapshot, result)
                return result

            if self.gateway_url:
                result = await self.gateway.chat_messages(
                    messages, model_type, think,
                    num_ctx, num_predict, format, tools, tool_choice,
                    timeout, model_override, sampling_preset, sampling_override,
                    stream, on_thinking, on_text,
                )
                self._update_cache_stats(result)
                self._log_call(t0, model_type, "gateway",
                               "agent_stream" if stream else "agent", source_tag,
                               prompt_snapshot, result)
                return result

            raise RuntimeError(f"No route for model_type={model_type}")

        except Exception as e:
            self._log_call(t0, model_type or "", "?", "agent", source_tag,
                           prompt_snapshot, None, error=str(e))
            raise

    def _resolve_route(self, model_type: str, model_override: str = None) -> tuple[bool, str]:
        """决定走 llama-swap 还是 Gateway，返回 (use_llamaswap, model_id)"""
        target_model = model_override or self.llamaswap_models.get(model_type) or self.gateway_models.get(model_type, model_type)
        self._last_model = target_model

        if model_override:
            if model_override.startswith("llamaswap:"):
                return True, model_override.split(":", 1)[1]
            elif model_override.startswith("gateway:"):
                return False, model_override
            else:
                return True, model_override
        elif model_type in self.llamaswap_models:
            return True, self.llamaswap_models[model_type]
        else:
            return False, model_type

    # ===== 缓存统计 =====

    def _update_cache_stats(self, result: dict):
        """从后端返回的 _usage 中提取缓存命中统计"""
        usage = result.get("_usage", {})
        if not usage:
            return
        prompt_tokens = usage.get("prompt_tokens", 0)

        # DeepSeek 格式: prompt_cache_hit_tokens (顶层)
        # OpenAI 格式: prompt_tokens_details.cached_tokens (嵌套)
        cached = usage.get("prompt_cache_hit_tokens", 0)
        if not cached:
            prompt_details = usage.get("prompt_tokens_details", {})
            cached = prompt_details.get("cached_tokens", 0) if isinstance(prompt_details, dict) else 0

        self._cache_stats["total_prompt_tokens"] += prompt_tokens
        self._cache_stats["total_cached_tokens"] += cached
        self._cache_stats["requests"] += 1
        if cached > 0:
            pct = cached / max(prompt_tokens, 1) * 100
            print(f"[Router] cache hit: {cached}/{prompt_tokens} tokens ({pct:.0f}%)")
            self._last_cache_hit = f"{cached}/{prompt_tokens} ({pct:.0f}%)"
        else:
            self._last_cache_hit = None

    def get_cache_stats(self) -> dict:
        s = self._cache_stats
        total = s["total_prompt_tokens"]
        cached = s["total_cached_tokens"]
        return {
            "requests": s["requests"],
            "total_prompt_tokens": total,
            "total_cached_tokens": cached,
            "hit_rate": round(cached / total * 100, 1) if total > 0 else 0,
        }

    # ===== Embedding / OCR =====

    async def embed(self, text: str, source_tag: str = "embedding") -> list[float]:
        t0 = time.time()
        try:
            result = await self._embed_ocr.embed(text, source_tag)
            self._log_call(t0, "qwen3-embedding", "ollama", "embed", source_tag,
                           text[:2000], json.dumps(result[:5]))
            return result
        except Exception as e:
            self._log_call(t0, "qwen3-embedding", "ollama", "embed", source_tag,
                           text[:2000], None, error=str(e))
            raise

    async def ocr(self, image_path: str) -> str:
        return await self._embed_ocr.ocr(image_path)

    # ===== 工具方法 =====

    def select_model(self, task_hint: str) -> tuple[str, bool]:
        hint = task_hint.lower()
        if any(w in hint for w in ["看", "图", "截图", "画面", "识别", "谁", "screenshot"]):
            return "vision", False
        if any(w in hint for w in ["总结", "分析", "深度", "调研", "规划"]):
            return "strong_text", True
        if any(w in hint for w in ["ocr", "文字", "提取"]):
            return "ocr", False
        return "fast_text", False

    async def get_llamaswap_loaded(self) -> list[str]:
        def _call():
            try:
                req = urllib.request.Request(
                    f"{self.llamaswap_url}/running",
                    headers={"Content-Type": "application/json"},
                )
                resp = _opener.open(req, timeout=5)
                data = json.loads(resp.read())
                return [m.get("model", "") for m in data.get("running", [])]
            except Exception:
                return []
        return await asyncio.to_thread(_call)

    # 兼容旧接口
    async def get_ollama_loaded(self) -> list[str]:
        return await self.get_llamaswap_loaded()

    async def get_lmstudio_loaded(self) -> list[str]:
        return await self.get_llamaswap_loaded()

    async def unload_lmstudio_model(self, model_id: str = "") -> bool:
        def _call():
            try:
                data = json.dumps({}).encode()
                req = urllib.request.Request(
                    f"{self.llamaswap_url}/unload",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                _opener.open(req, timeout=5)
                return True
            except Exception:
                return False
        return await asyncio.to_thread(_call)

    async def close(self):
        pass

    # ===== 调用日志 =====

    def _log_call(self, t0: float, model: str, backend: str, kind: str,
                   source_tag: str, prompt_full: str, response_full: str = None,
                   error: str = None):
        try:
            if hasattr(self, '_claims') and self._claims:
                self._claims.log_model_call(
                    ts=t0, model=model, backend=backend, kind=kind,
                    source_tag=source_tag, prompt_full=prompt_full,
                    response_full=(response_full or "")[:50000],
                    duration_ms=int((time.time() - t0) * 1000),
                    error=error,
                )
        except Exception as e:
            print(f"[Router] log_model_call 失败: {e}")

    def set_claims(self, claims):
        self._claims = claims
