import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import pytz
import json
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# ====== 基本設定 ======
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ====== 永続保存 ======
PERSISTENT_DIR = "./data"
os.makedirs(PERSISTENT_DIR, exist_ok=True)
VOTE_FILE = os.path.join(PERSISTENT_DIR, "votes.json")
CONFIRM_FILE = os.path.join(PERSISTENT_DIR, "confirmed.json")

vote_data = {}
confirmed_data = {}

def load_votes():
    global vote_data
    if os.path.exists(VOTE_FILE):
        with open(VOTE_FILE, "r", encoding="utf-8") as f:
            vote_data = json.load(f)
    else:
        vote_data = {}

def save_votes():
    with open(VOTE_FILE, "w", encoding="utf-8") as f:
        json.dump(vote_data, f, ensure_ascii=False, indent=2)

def load_confirmed():
    global confirmed_data
    if os.path.exists(CONFIRM_FILE):
        with open(CONFIRM_FILE, "r", encoding="utf-8") as f:
            confirmed_data = json.load(f)
    else:
        confirmed_data = {}

def save_confirmed():
    with open(CONFIRM_FILE, "w", encoding="utf-8") as f:
        json.dump(confirmed_data, f, ensure_ascii=False, indent=2)

# ====== タイムゾーン ======
JST = pytz.timezone("Asia/Tokyo")

# ====== スケジュール生成 ======
def get_schedule_start():
    today = datetime.datetime.now(JST)
    days_since_sunday = (today.weekday() + 1) % 7
    this_sunday = today - datetime.timedelta(days=days_since_sunday)
    target = this_sunday + datetime.timedelta(weeks=3)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)

def generate_week_schedule():
    start = get_schedule_start()
    weekday_jp = ["月","火","水","木","金","土","日"]
    return [
        f"{(start + datetime.timedelta(days=i)).strftime('%Y-%m-%d')} ({weekday_jp[(start + datetime.timedelta(days=i)).weekday()]})"
        for i in range(7)
    ]

def get_week_name(date):
    month = date.month
    first_day = date.replace(day=1)
    first_sunday = first_day + datetime.timedelta(days=(6 - first_day.weekday()) % 7)
    week_number = ((date - first_sunday).days // 7) + 1
    return f"{month}月第{week_number}週"

# ====== VoteView ======
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str

    async def handle_vote(self, interaction: discord.Interaction, status: str):
        message_id = str(interaction.message.id)
        user_id = str(interaction.user.id)
        user_name = interaction.user.display_name

        if message_id not in vote_data:
            vote_data[message_id] = {}
        if self.date_str not in vote_data[message_id]:
            vote_data[message_id][self.date_str] = {"参加(🟢)": {}, "オンライン可(🟡)": {}, "不可(🔴)": {}}

        current_status = None
        for k, v in vote_data[message_id][self.date_str].items():
            if user_id in v:
                current_status = k
                break

        if current_status == status:
            del vote_data[message_id][self.date_str][status][user_id]
        else:
            for v_dict in vote_data[message_id][self.date_str].values():
                if user_id in v_dict:
                    del v_dict[user_id]
            vote_data[message_id][self.date_str][status][user_id] = user_name

        save_votes()

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="オンライン可(🟡)", style=discord.ButtonStyle.primary)
    async def maybe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "オンライン可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "不可(🔴)")

# ====== Step1～3 関数 ======
async def send_step1_schedule():
    await bot.wait_until_ready()
    guild = bot.guilds[0]
    category_beginner = discord.utils.get(guild.categories, name="初級")
    category_intermediate = discord.utils.get(guild.categories, name="中級")
    if not category_beginner or not category_intermediate:
        return

    start = get_schedule_start()
    week_name = get_week_name(start)
    ch_names = {"初級": f"{week_name}-初級", "中級": f"{week_name}-中級"}
    channels = {}
    for level, ch_name in ch_names.items():
        existing = discord.utils.get(guild.text_channels, name=ch_name)
        if existing:
            channels[level] = existing
        else:
            category = category_beginner if level == "初級" else category_intermediate
            new_ch = await guild.create_text_channel(ch_name, category=category)
            channels[level] = new_ch

    week = generate_week_schedule()
    for level, ch in channels.items():
        for date in week:
            embed = discord.Embed(title=f"📅 {level} - 三週間後の予定 {date}")
            embed.add_field(name="参加(🟢)", value="0人", inline=False)
            embed.add_field(name="オンライン可(🟡)", value="0人", inline=False)
            embed.add_field(name="不可(🔴)", value="0人", inline=False)
            view = VoteView(date)
            msg = await ch.send(embed=embed, view=view)
            vote_data[str(msg.id)] = {"channel": ch.id, date: {"参加(🟢)": {}, "オンライン可(🟡)": {}, "不可(🔴)": {}}}
            save_votes()

async def send_step2_remind():
    await bot.wait_until_ready()
    guild = bot.guilds[0]
    start = get_schedule_start()
    week_name = get_week_name(start)
    for level in ["初級", "中級"]:
        ch_name = f"{week_name}-{level}"
        target_channel = discord.utils.get(guild.text_channels, name=ch_name)
        if not target_channel: continue
        week = generate_week_schedule()
        message = f"📢【{week_name} {level}リマインド】\n\n"
        for date in week:
            for msg_id, data in vote_data.items():
                if data.get("channel") != target_channel.id: continue
                if date not in data: continue
                date_votes = data[date]
                message += f"{date}\n参加(🟢): " + (", ".join(date_votes["参加(🟢)"].values()) or "なし") + \
                           "\nオンライン可(🟡): " + (", ".join(date_votes["オンライン可(🟡)"].values()) or "なし") + \
                           "\n不可(🔴): " + (", ".join(date_votes["不可(🔴)"].values()) or "なし") + "\n\n"
        await target_channel.send(message)

async def send_step3_confirm():
    await bot.wait_until_ready()
    guild = bot.guilds[0]
    start = get_schedule_start()
    week_name = get_week_name(start)
    for level in ["初級", "中級"]:
        ch_name = f"{week_name}-{level}"
        target_channel = discord.utils.get(guild.text_channels, name=ch_name)
        if not target_channel: continue
        role = discord.utils.get(guild.roles, name=level)
        if not role: continue
        week = generate_week_schedule()
        message = f"📢【{week_name} {level} 1週間前催促】\n\n"
        all_voted = True
        for date in week:
            for msg_id, data in vote_data.items():
                if data.get("channel") != target_channel.id: continue
                if date not in data: continue
                date_votes = data[date]
                unvoted_members = []
                for member in role.members:
                    voted_ids = set()
                    for v_dict in date_votes.values():
                        voted_ids.update(v_dict.keys())
                    if str(member.id) not in voted_ids:
                        unvoted_members.append(member.mention)
                if unvoted_members:
                    all_voted = False
                    message += f"{date}\n" + ", ".join(unvoted_members) + "\n\n"
        if all_voted:
            message = f"📢【{week_name} {level}】全員投票済みです。ありがとうございます！🎉"
        await target_channel.send(message)

# ====== Step4 Cog ======
class Confirm(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @tasks.loop(minutes=1)
    async def check_step4(self):
        await self.bot.wait_until_ready()
        guild = self.bot.guilds[0]
        for level in ["初級", "中級"]:
            role = discord.utils.get(guild.roles, name=level)
            notify_channel = discord.utils.get(guild.text_channels, name="人数確定通知所")
            if not role or not notify_channel: continue
            week = generate_week_schedule()
            for date in week:
                for msg_id, data in vote_data.items():
                    if date not in data: continue
                    date_votes = data[date]
                    if len(date_votes["参加(🟢)"]) >= 1:  # テスト用1人以上
                        participants = ", ".join(date_votes["参加(🟢)"].values())
                        content = f"📢【{level} {date}】参加者: {participants}\nスタジオを抑えてください。"
                        await notify_channel.send(content)

    @check_step4.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

# ====== Scheduler ======
scheduler = AsyncIOScheduler(timezone=JST)

@bot.event
async def on_ready():
    load_votes()
    load_confirmed()
    try:
        await tree.sync()
    except Exception as e:
        print(f"⚠ コマンド同期エラー: {e}")

    # Cog追加（非同期）
    await bot.add_cog(Confirm(bot))

    now = datetime.datetime.now(JST)
    # ===== 固定時刻スケジュール =====
    three_week_test = now.replace(hour=1, minute=00, second=0, microsecond=0)
    two_week_test   = now.replace(hour=1, minute=1, second=0, microsecond=0)
    one_week_test   = now.replace(hour=1, minute=2, second=0, microsecond=0)

    scheduler.add_job(send_step1_schedule, DateTrigger(run_date=three_week_test))
    scheduler.add_job(send_step2_remind,   DateTrigger(run_date=two_week_test))
    scheduler.add_job(send_step3_confirm,  DateTrigger(run_date=one_week_test))

    scheduler.start()

# ====== Bot起動 ======
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
