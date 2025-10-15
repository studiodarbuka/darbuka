import os
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import datetime
import pytz
import json
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# ====== 基本設定 ======
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ====== 永続化ディレクトリ ======
PERSISTENT_DIR = "/opt/render/project/src/data"
os.makedirs(PERSISTENT_DIR, exist_ok=True)
VOTE_FILE = os.path.join(PERSISTENT_DIR, "votes.json")

# ====== タイムゾーン ======
JST = pytz.timezone("Asia/Tokyo")

# ====== 投票データ ======
vote_data = {}

# ====== データ保存 ======
def save_votes():
    with open(VOTE_FILE, "w", encoding="utf-8") as f:
        json.dump(vote_data, f, ensure_ascii=False, indent=2)

def load_votes():
    global vote_data
    if os.path.exists(VOTE_FILE):
        with open(VOTE_FILE, "r", encoding="utf-8") as f:
            vote_data = json.load(f)
    else:
        vote_data = {}

# ====== ユーティリティ ======
def get_schedule_start():
    """3週間後の日曜を取得"""
    today = datetime.datetime.now(JST)
    days_until_sunday = (6 - today.weekday()) % 7
    target = today + datetime.timedelta(days=days_until_sunday + 14)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)

def generate_week_schedule():
    start = get_schedule_start()
    return [(start + datetime.timedelta(days=i)).strftime("%Y-%m-%d (%a)") for i in range(7)]

# ====== 投票ビュー ======
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str

    @discord.ui.button(label="参加(✅)", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "参加")

    @discord.ui.button(label="調整(🤔)", style=discord.ButtonStyle.blurple)
    async def maybe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "調整")

    @discord.ui.button(label="不可(❌)", style=discord.ButtonStyle.red)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "不可")

    async def register_vote(self, interaction: discord.Interaction, status: str):
        user = interaction.user.name
        if self.date_str not in vote_data:
            vote_data[self.date_str] = {"参加": [], "調整": [], "不可": []}

        # 他のステータスから削除
        for k in vote_data[self.date_str]:
            if user in vote_data[self.date_str][k]:
                vote_data[self.date_str][k].remove(user)

        vote_data[self.date_str][status].append(user)
        save_votes()

        # Embed更新
        embed = interaction.message.embeds[0]
        for idx, k in enumerate(["参加", "調整", "不可"]):
            users = vote_data[self.date_str][k]
            embed.set_field_at(idx, name=k, value="\n".join(users) if users else "なし", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

# ====== スケジュール投稿 ======
async def send_schedule():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="wqwq")
    if not channel:
        print("⚠️ チャンネル #wqwq が見つかりません。")
        return

    week = generate_week_schedule()
    global vote_data
    vote_data = {date: {"参加": [], "調整": [], "不可": []} for date in week}
    save_votes()

    for date in week:
        embed = discord.Embed(title=f"【日程候補】{date}", description="ボタンで投票してください")
        embed.add_field(name="参加", value="なし", inline=False)
        embed.add_field(name="調整", value="なし", inline=False)
        embed.add_field(name="不可", value="なし", inline=False)
        await channel.send(embed=embed, view=VoteView(date))

    print("✅ 投票投稿完了")

# ====== /schedule コマンド ======
@bot.tree.command(name="schedule", description="手動で日程投票を開始")
async def schedule_command(interaction: discord.Interaction):
    await interaction.response.send_message("📅 手動で日程投票を開始します", ephemeral=True)
    await send_schedule()

# ====== /event_now コマンド ======
@bot.tree.command(name="event_now", description="突発イベントを通知")
@app_commands.describe(内容="イベント内容")
async def event_now(interaction: discord.Interaction, 内容: str):
    channel = discord.utils.get(interaction.guild.channels, name="wqwq")
    if not channel:
        await interaction.response.send_message("⚠️ チャンネル #wqwq が見つかりません", ephemeral=True)
        return
    await channel.send(f"🚨 **突発イベント**\n{内容}")
    await interaction.response.send_message("✅ 突発イベントを送信しました", ephemeral=True)

# ====== 起動時 ======
@bot.event
async def on_ready():
    load_votes()
    try:
        await bot.tree.sync()
        print("✅ Slash Commands synced!")
    except Exception as e:
        print(f"⚠️ コマンド同期エラー: {e}")

    # 今日14:00の投稿テスト
    now = datetime.datetime.now(JST)
    post_time = now.replace(hour=14, minute=0, second=0, microsecond=0)
    if post_time < now:
        post_time += datetime.timedelta(days=0)  # 今日の14:00を過ぎていたら次回
    scheduler = AsyncIOScheduler(timezone=JST)
    scheduler.add_job(send_schedule, DateTrigger(run_date=post_time))
    scheduler.start()
    print(f"✅ Logged in as {bot.user} / Scheduler set for {post_time.strftime('%Y-%m-%d %H:%M')} JST")

# ====== 実行 ======
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("❌ DISCORD_BOT_TOKEN が設定されていません。")
    bot.run(token)
