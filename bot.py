import discord
from discord.ext import tasks, commands
import datetime
import asyncio
import os

# ==== 環境設定 ====
TOKEN = os.getenv("DISCORD_BOT_TOKEN")  # Render環境変数に設定してあるBotトークンを利用
TARGET_CHANNEL_NAME = "wqwq"  # 投稿先チャンネル名

# ==== Bot初期化 ====
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

target_channel = None  # 検出結果を保持

# ==== 起動時処理 ====
@bot.event
async def on_ready():
    global target_channel
    print(f"✅ ログイン完了: {bot.user}")

    # チャンネル検出
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.name == TARGET_CHANNEL_NAME:
                target_channel = channel
                print(f"🎯 送信チャンネル検出: {channel.name} ({channel.id})")
                break

    if target_channel is None:
        print(f"⚠️ チャンネル '{TARGET_CHANNEL_NAME}' が見つかりませんでした。")
    else:
        print("🕒 スケジュールタスクを開始します...")
        auto_task.start()  # 自動タスク起動

# ==== 自動実行タスク ====
@tasks.loop(minutes=1)
async def auto_task():
    """毎分チェックして18:50になったら送信"""
    now = datetime.datetime.now().strftime("%H:%M")
    if now == "18:50":
        await target_channel.send("⏰ 自動実行テストです！（18:50）")
        print("✅ 自動実行完了")

# ==== 手動テストコマンド ====
@bot.command()
async def test_now(ctx):
    """手動で送信テスト"""
    await ctx.send("✅ 手動送信テストです！")

# ==== 実行 ====
bot.run(TOKEN)
