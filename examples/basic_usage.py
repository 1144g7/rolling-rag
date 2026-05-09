"""
Rolling RAG 基本用法示例
"""
import asyncio
from core.conv_indexer import ConvIndexer
from core.router import ModelRouter
from core.embedding import BGEEmbedding
import config

async def main():
    # 初始化组件
    router = ModelRouter()
    embedding = BGEEmbedding()
    indexer = ConvIndexer(router, embedding, config)

    # 示例消息
    messages = [
        {"role": "user", "content": "我在考虑用 Rust 还是 Go 做这个项目"},
        {"role": "assistant", "content": "Rust 性能更好，Go 学习曲线更低..."},
        {"role": "user", "content": "我决定用 Rust，因为性能是关键"},
        {"role": "assistant", "content": "好的，Rust 是个好选择..."},
        # ... 更多消息
    ]

    # 执行滚动分段
    result = await indexer.process_conversation(
        conv_id="example_001",
        messages=messages,
    )

    # 查看结果
    print("=== 段落 ===")
    for seg in result["segments"]:
        print(f"  {seg['name']}: {seg['summary']}")

    print("\n=== 关系 ===")
    for rel in result["relations"]:
        print(f"  {rel['from']} --[{rel['type'}]--> {rel['to']}")

    print(f"\n=== 全局摘要 ===")
    print(result["global_summary"])

    print(f"\n=== 结论 ===")
    print(result["conclusion"])

if __name__ == "__main__":
    asyncio.run(main())
