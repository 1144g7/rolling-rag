"""
BGEEmbedding — 统一嵌入 + 重排模块（BGE-M3 + BGE-Reranker-v2-m3，懒加载单例）

所有 embedding / rerank 调用的统一入口：
- conv_segments 段摘要
- conv_index 全局摘要
- conversation_embeddings 对话 chunk
- 搜索查询向量 + 重排序
"""
import threading
import numpy as np


class BGEEmbedding:
    """BGE-M3 + Reranker 懒加载单例，线程安全"""

    _instance = None
    _lock = threading.Lock()
    _model = None
    _reranker_tokenizer = None
    _reranker_model = None

    # BGE-M3 dense 输出维度
    DIM = 1024

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def model(self):
        """懒加载 BGE-M3 模型"""
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel
            print("[BGEEmbedding] 加载 BAAI/bge-m3 ...")
            self._model = BGEM3FlagModel(
                "BAAI/bge-m3",
                use_fp16=True,
                device="cuda",
                use_safetensors=True,
            )
            print("[BGEEmbedding] 加载完成")
        return self._model

    def _ensure_reranker(self):
        """懒加载 BGE-Reranker-v2-m3"""
        if self._reranker_model is None:
            import torch
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            print("[BGEEmbedding] 加载 BAAI/bge-reranker-v2-m3 ...")
            self._reranker_tokenizer = AutoTokenizer.from_pretrained(
                "BAAI/bge-reranker-v2-m3")
            self._reranker_model = AutoModelForSequenceClassification.from_pretrained(
                "BAAI/bge-reranker-v2-m3",
                dtype=torch.float16,
            ).cuda()
            print("[BGEEmbedding] Reranker 加载完成")

    def embed(self, text: str, max_length: int = 512) -> np.ndarray:
        """嵌入单条文本，返回 1024-dim 向量（L2 归一化）"""
        out = self.model.encode(
            [text], batch_size=1, max_length=max_length,
            return_dense=True, return_sparse=False,
        )
        vec = np.array(out["dense_vecs"][0], dtype=np.float32)
        vec = vec / (np.linalg.norm(vec) + 1e-9)
        return vec

    def embed_batch(self, texts: list[str], batch_size: int = 24,
                    max_length: int = 512) -> np.ndarray:
        """批量嵌入，返回 (N, 1024) 矩阵（L2 归一化）"""
        if not texts:
            return np.zeros((0, self.DIM), dtype=np.float32)
        out = self.model.encode(
            texts, batch_size=batch_size, max_length=max_length,
            return_dense=True, return_sparse=False,
        )
        mat = np.array(out["dense_vecs"], dtype=np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
        mat = mat / norms
        return mat

    def embed_dense_sparse(self, texts: list[str], batch_size: int = 24,
                           max_length: int = 512) -> tuple[np.ndarray, list[dict]]:
        """批量嵌入，返回 (dense_matrix, sparse_weights_list)
        dense: (N, 1024) float32 L2归一化
        sparse: list[dict] — 每个 dict 是 token_id → weight
        """
        if not texts:
            return np.zeros((0, self.DIM), dtype=np.float32), []
        out = self.model.encode(
            texts, batch_size=batch_size, max_length=max_length,
            return_dense=True, return_sparse=True,
            return_colbert_vecs=False,
        )
        mat = np.array(out["dense_vecs"], dtype=np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
        mat = mat / norms
        return mat, out["lexical_weights"]

    def rerank(self, query: str, documents: list[str],
               max_length: int = 512) -> list[float]:
        """重排序：query 与每个 document 的相关性分数
        返回与 documents 等长的 float 列表，越高越相关。
        查询时实时调用，不需要预跑。
        """
        import torch
        self._ensure_reranker()
        pairs = [[query, doc] for doc in documents]
        with torch.no_grad():
            inputs = self._reranker_tokenizer(
                pairs, padding=True, truncation=True,
                max_length=max_length, return_tensors="pt",
            ).to(self._reranker_model.device)
            scores = self._reranker_model(**inputs).logits.squeeze(-1)
        return scores.float().cpu().tolist()

    @staticmethod
    def vec_to_blob(vec: np.ndarray) -> bytes:
        """float32 向量 → BLOB"""
        return vec.astype(np.float32).tobytes()

    @staticmethod
    def blob_to_vec(blob: bytes) -> np.ndarray:
        """BLOB → float32 向量"""
        return np.frombuffer(blob, dtype=np.float32)

    def unload(self):
        """卸载所有模型释放 GPU 显存"""
        import gc, torch
        for attr in ("_model", "_reranker_model", "_reranker_tokenizer"):
            obj = getattr(self, attr, None)
            if obj is not None:
                del obj
                setattr(self, attr, None)
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print("[BGEEmbedding] 模型已卸载")

    def unload_reranker(self):
        """只卸载 reranker（M3 保留）"""
        import gc, torch
        for attr in ("_reranker_model", "_reranker_tokenizer"):
            obj = getattr(self, attr, None)
            if obj is not None:
                del obj
                setattr(self, attr, None)
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print("[BGEEmbedding] Reranker 已卸载")


# 模块级便捷函数
_default = None


def get_embedding() -> BGEEmbedding:
    """获取全局 BGEEmbedding 单例"""
    global _default
    if _default is None:
        _default = BGEEmbedding()
    return _default
