import discord
from discord.ext import tasks, commands
import datetime
import asyncio

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- テスト用投票関数 ----------
async def run_test_vote():
    channel_id = 123456789012345678  # テスト用チャンネルID
    channel = bot.get_channel(channel_id)
    if channel:
        await channel.send("💡 テスト投票開始！")
        # ここに本来の投票処理を呼ぶ
        # 例: await create_vote(channel, "テストイベント", ["✅", "❌"])
    else:
        print("チャンネルが見つかりません")

# ---------- 13時に実行するタスク ----------
@tasks.loop(minutes=1)
async def check_time_and_run():
    now = datetime.datetime.now()
    # 13時ちょうどに実行
    if now.hour == 13 and now.minute == 0:
        print("13時になったのでテスト投票を実行")
        await run_test_vote()
        # 重複実行防止のため1分待つ
        await asyncio.sleep(60)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    check_time_and_run.start()

bot.run("YOUR_BOT_TOKEN")
