import os
import discord
from discord import app_commands
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import datetime
import pytz
import json

# ===== 基本設定 =====
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", 0))
JST = pytz.timezone("Asia/Tokyo")
VOTE_FILE = "votes.json"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ===== データ保存 =====
def load_votes():
    if os.path.exists(VOTE_FILE):
        with open(VOTE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_votes(data):
    with open(VOTE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ===== 投票UI =====
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str

    async def handle_vote(self, interaction: discord.Interaction, vote_type: str):
        votes = load_votes()
        date = self.date_str
        user = interaction.user.name

        if date not in votes:
            votes[date] = {"参加": [], "オンライン可": [], "不可": []}

        # 二重押しで解除できるように
        if user in votes[date][vote_type]:
            votes[date][vote_type].remove(user)
            msg = f"{date} の「{vote_type}」投票を取り消しました。"
        else:
            for key in votes[date]:
                if user in votes[date][key]:
                    votes[date][key].remove(user)
            votes[date][vote_type].append(user)
            msg = f"{date} に「{vote_type}」として投票しました。"

        save_votes(votes)
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="🟢参加", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "参加")

    @discord.ui.button(label="🟡オンライン可", style=discord.ButtonStyle.primary)
    async def maybe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "オンライン可")

    @discord.ui.button(label="🔴不可", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "不可")

# ===== Step1（投票開始） =====
async def send_step1_schedule():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        print("❌ ギルドが見つかりません。")
        return

    for level_name in ["初級", "中級"]:
        channel = discord.utils.get(guild.text_channels, name=level_name)
        if not channel:
            print(f"⚠ チャンネル「{level_name}」が見つかりません。")
            continue

        now = datetime.datetime.now(JST)
        target_start = now + datetime.timedelta(weeks=3)
        start_of_week = target_start - datetime.timedelta(days=target_start.weekday())

        embed = discord.Embed(
            title=f"📅【{start_of_week.strftime('%m月第%W週')} {level_name} 投票開始】",
            description="以下の日付で参加可否を選んでください！",
            color=0x2ECC71
        )

        for i in range(7):
            day = start_of_week + datetime.timedelta(days=i)
            date_str = (
                day.strftime("%Y-%m-%d (%a)")
                .replace("(Sun)", "(日)").replace("(Mon)", "(月)")
                .replace("(Tue)", "(火)").replace("(Wed)", "(水)")
                .replace("(Thu)", "(木)").replace("(Fri)", "(金)")
                .replace("(Sat)", "(土)")
            )
            view = VoteView(date_str)
            await channel.send(embed=discord.Embed(title=date_str, color=0x95A5A6), view=view)

        await channel.send(f"{level_name} の投票を開始しました！")

# ===== Step2（2週間前リマインド） =====
async def send_step2_remind():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        print("❌ ギルドが見つかりません。")
        return

    votes = load_votes()
    now = datetime.datetime.now(JST)
    target_start = now + datetime.timedelta(weeks=1)
    start_of_week = target_start - datetime.timedelta(days=target_start.weekday())

    for level_name in ["初級", "中級"]:
        channel = discord.utils.get(guild.text_channels, name=level_name)
        if not channel:
            continue

        embed = discord.Embed(
            title=f"📢【{start_of_week.strftime('%m月第%W週')} {level_name}リマインド】",
            color=0x3498DB
        )

        for i in range(7):
            day = start_of_week + datetime.timedelta(days=i)
            date_str = (
                day.strftime("%Y-%m-%d (%a)")
                .replace("(Sun)", "(日)").replace("(Mon)", "(月)")
                .replace("(Tue)", "(火)").replace("(Wed)", "(水)")
                .replace("(Thu)", "(木)").replace("(Fri)", "(金)")
                .replace("(Sat)", "(土)")
            )
            v = votes.get(date_str, {"参加": [], "オンライン可": [], "不可": []})
            embed.add_field(
                name=date_str,
                value=f"🟢参加: {', '.join(v['参加']) or 'なし'}\n🟡オンライン可: {', '.join(v['オンライン可']) or 'なし'}\n🔴不可: {', '.join(v['不可']) or 'なし'}",
                inline=False
            )

        await channel.send(embed=embed)

# ===== Step3（1週間前催促） =====
async def send_step3_remind():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        print("❌ ギルドが見つかりません。")
        return

    votes = load_votes()
    now = datetime.datetime.now(JST)
    target_start = now + datetime.timedelta(days=7)
    start_of_week = target_start - datetime.timedelta(days=target_start.weekday())

    for level_name in ["初級", "中級"]:
        channel = discord.utils.get(guild.text_channels, name=level_name)
        role = discord.utils.get(guild.roles, name=level_name)
        if not channel or not role:
            continue

        not_voted_users = {}
        for member in guild.members:
            if role not in member.roles:
                continue

            not_voted_days = []
            for i in range(7):
                day = start_of_week + datetime.timedelta(days=i)
                date_str = (
                    day.strftime("%Y-%m-%d (%a)")
                    .replace("(Sun)", "(日)").replace("(Mon)", "(月)")
                    .replace("(Tue)", "(火)").replace("(Wed)", "(水)")
                    .replace("(Thu)", "(木)").replace("(Fri)", "(金)")
                    .replace("(Sat)", "(土)")
                )
                v = votes.get(date_str, {"参加": [], "オンライン可": [], "不可": []})
                if (
                    member.name not in v["参加"]
                    and member.name not in v["オンライン可"]
                    and member.name not in v["不可"]
                ):
                    not_voted_days.append(date_str)

            if not_voted_days:
                not_voted_users[member] = not_voted_days

        if not not_voted_users:
            await channel.send(f"✅【{level_name}】全員投票済みです！")
            continue

        msg = f"📢【{start_of_week.strftime('%m月第%W週')} {level_name} 未投票催促】\n以下のメンバーはまだ投票していません：\n\n"
        for member, days in not_voted_users.items():
            msg += f"🔸 {member.mention}\n未投票日：{', '.join(days)}\n"

        await channel.send(msg)

# ===== 起動時（Render対応） =====
@bot.event
async def on_ready():
    load_votes()
    print(f"✅ ログイン完了: {bot.user}")
    scheduler = AsyncIOScheduler(timezone=JST)
    now = datetime.datetime.now(JST)
    step1_time = now.replace(hour=21, minute=30, second=0, microsecond=0)
    step2_time = now.replace(hour=21, minute=31, second=0, microsecond=0)
    step3_time = now.replace(hour=21, minute=32, second=0, microsecond=0)

    scheduler.add_job(send_step1_schedule, DateTrigger(run_date=step1_time))
    scheduler.add_job(send_step2_remind, DateTrigger(run_date=step2_time))
    scheduler.add_job(send_step3_remind, DateTrigger(run_date=step3_time))

    scheduler.start()

bot.run(TOKEN)
