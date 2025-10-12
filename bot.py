import discord
from discord import app_commands
import datetime
import os
import asyncio
import json

# -----------------------------
# 初期設定
# -----------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# -----------------------------
# データ保持（永続化なし簡易版）
# -----------------------------
vote_data = {}

# -----------------------------
# VoteView
# -----------------------------
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str

    async def register_vote(self, interaction: discord.Interaction, status: str):
        # 簡易版なので保存はなし
        await interaction.response.send_message(f"✅ {status} に投票しました（テスト用）", ephemeral=True)

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="調整可(🟡)", style=discord.ButtonStyle.blurple)
    async def maybe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "調整可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.red)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "不可(🔴)")

# -----------------------------
# 日程送信関数
# -----------------------------
async def send_week_schedule(channel):
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date()
    target = today + datetime.timedelta(weeks=3)
    days_to_sunday = (6 - target.weekday()) % 7
    start_date = target + datetime.timedelta(days=days_to_sunday)

    dates = [(start_date + datetime.timedelta(days=i)).strftime("%m/%d(%a)") for i in range(7)]
    for d in dates:
        embed = discord.Embed(title=f"【日程候補】{d}", description="以下のボタンで投票してください")
        embed.add_field(name="参加(🟢)", value="なし", inline=False)
        embed.add_field(name="調整可(🟡)", value="なし", inline=False)
        embed.add_field(name="不可(🔴)", value="なし", inline=False)
        await channel.send(embed=embed, view=VoteView(d))

    await channel.send("✅ 自動送信テスト完了！")

# -----------------------------
# Bot起動時処理
# -----------------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    await tree.sync()
    print("✅ Slash commands synced!")

    # チャンネル名で取得
    channel_name = "wqwq"
    channel = None
    for guild in bot.guilds:
        channel = discord.utils.get(guild.text_channels, name=channel_name)
        if channel:
            break
    if not channel:
        print(f"❌ チャンネル {channel_name} が見つかりません")
        return

    # 今日の19:55 JST に送信
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    send_time = now.replace(hour=19, minute=55, second=0, microsecond=0)
    if send_time < now:
        send_time += datetime.timedelta(days=1)

    async def schedule_task():
        await asyncio.sleep((send_time - datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))).total_seconds())
        await send_week_schedule(channel)

    bot.loop.create_task(schedule_task())
    print(f"⏰ 今日の19:55 JST に自動送信予定です")

# -----------------------------
# 実行
# -----------------------------
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise ValueError("⚠️ DISCORD_BOT_TOKEN が設定されていません。")

bot.run(TOKEN)

