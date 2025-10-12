import discord
from discord.ext import tasks
import asyncio
import datetime
import os

# ===== 設定 =====
TOKEN = os.getenv("DISCORD_BOT_TOKEN")  # 環境変数からトークンを取得
TARGET_CHANNEL_NAME = "wqwq"             # 送信先チャンネル名
TARGET_HOUR = 18                         # 実行時刻（時）
TARGET_MINUTE = 40                       # 実行時刻（分）

# ===== Discord Bot初期化 =====
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

target_channel = None  # 送信先チャンネルの参照を保持


@client.event
async def on_ready():
    global target_channel
    print(f"✅ ログイン成功: {client.user}")

    # チャンネル自動検出
    for guild in client.guilds:
        for channel in guild.text_channels:
            if channel.name == TARGET_CHANNEL_NAME:
                target_channel = channel
                print(f"🎯 送信チャンネル検出: {channel.name} ({channel.id})")
                break

    if not target_channel:
        print("⚠️ チャンネル 'wqwq' が見つかりません。")

    # 自動実行ループ開始
    if not auto_task.is_running():
        auto_task.start()


@tasks.loop(minutes=1)
async def auto_task():
    """毎分チェックして18:40に自動実行"""
    now = datetime.datetime.now()
    if now.hour == TARGET_HOUR and now.minute == TARGET_MINUTE:
        await run_task()


async def run_task():
    """ここに実行したい処理を書く"""
    if target_channel:
        await target_channel.send("⏰ 自動実行テストです！（18:40）")
        print("✅ メッセージを送信しました。")
    else:
        print("⚠️ 送信チャンネルが見つかりません。")


# ===== 実行 =====
client.run(TOKEN)
