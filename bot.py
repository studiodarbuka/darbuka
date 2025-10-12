import discord
from discord.ext import tasks
import asyncio
import datetime
import os

# ====== Bot設定 ======
TOKEN = os.getenv("DISCORD_BOT_TOKEN")  # Renderの環境変数に設定済みのトークン
CHANNEL_NAME = "wqwq"  # 自動検出するチャンネル名
TARGET_HOUR = 19       # 19時
TARGET_MINUTE = 0      # 00分

# ====== Bot初期化 ======
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

target_channel = None


@bot.event
async def on_ready():
    """Bot起動時に呼ばれる"""
    global target_channel
    print(f"[✅] Logged in as: {bot.user}")

    # チャンネル自動検出
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.name == CHANNEL_NAME:
                target_channel = channel
                print(f"[✅] Target channel found: #{channel.name} in {guild.name}")
                break

    if target_channel is None:
        print(f"[⚠️] チャンネル名 '{CHANNEL_NAME}' が見つかりません。")
        return

    # 自動タスク開始
    check_time.start()
    print("[⏰] スケジュールタスク開始済み。")


@tasks.loop(minutes=1)
async def check_time():
    """毎分時刻をチェックして、指定時刻にメッセージ送信"""
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))  # JST
    if now.hour == TARGET_HOUR and now.minute == TARGET_MINUTE:
        if target_channel:
            await target_channel.send(f"⏰ 自動実行テストです！（{TARGET_HOUR:02}:{TARGET_MINUTE:02}）")
            print(f"[✅] {TARGET_HOUR:02}:{TARGET_MINUTE:02} にメッセージ送信しました。")
        else:
            print("[⚠️] target_channel が未設定です。")


@bot.event
async def on_message(message):
    """手動テスト用コマンド"""
    if message.author == bot.user:
        return
    if message.content == "/test_now":
        await message.channel.send("✅ 手動送信テストです！")


bot.run(TOKEN)
