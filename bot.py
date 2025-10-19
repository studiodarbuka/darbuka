import os
import discord
from discord import app_commands
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import datetime
import pytz
import json

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
LOCATIONS_FILE = os.path.join(PERSISTENT_DIR, "locations.json")

# ====== タイムゾーン ======
JST = pytz.timezone("Asia/Tokyo")

# ====== 投票データ ======
vote_data = {}

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

# ====== 日付計算 ======
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

# ====== 投票ビュー（Step4自動通知対応） ======
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

        # トグル式
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

        # Embed更新
        embed = discord.Embed(title=f"【予定候補】{self.date_str}")
        for k, v in vote_data[message_id][self.date_str].items():
            embed.add_field(name=f"{k} ({len(v)}人)", value="\n".join(v.values()) if v else "0人", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

        # Step4自動通知
        participants = vote_data[message_id][self.date_str]["参加(🟢)"]
        if len(participants) >= 1:
            await self.send_confirm_notice(interaction, participants)

    async def send_confirm_notice(self, interaction: discord.Interaction, participants: dict):
        guild = interaction.guild
        confirm_channel = discord.utils.get(guild.text_channels, name="人数確定通知所")
        if not confirm_channel:
            print("⚠️ 『人数確定通知所』チャンネルが見つかりません。")
            return

        level = "初級" if "初級" in interaction.channel.name else "中級"
        participants_list = ", ".join(participants.values())

        embed = discord.Embed(
            title="📢 人数確定通知",
            description=(
                f"日程: {self.date_str}\n"
                f"級: {level}\n"
                f"参加者 ({len(participants)}人): {participants_list}\n\n"
                f"<@&講師> さん、スタジオを抑えてください。\n"
                f"確定または不確定が決まったら、`/確定` または `/不確定` コマンドで通知してください。"
            ),
            color=0x00BFFF
        )
        await confirm_channel.send(embed=embed)

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="オンライン可(🟡)", style=discord.ButtonStyle.primary)
    async def maybe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "オンライン可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "不可(🔴)")

# ====== Step1～Step3 ======
async def send_step1_schedule():
    await bot.wait_until_ready()
    guild = bot.guilds[0]

    category_beginner = discord.utils.get(guild.categories, name="初級")
    category_intermediate = discord.utils.get(guild.categories, name="中級")
    if not category_beginner or not category_intermediate:
        print("⚠️ カテゴリ「初級」「中級」が見つかりません。")
        return

    start = get_schedule_start()
    week_name = get_week_name(start)

    ch_names = {
        "初級": f"{week_name}-初級",
        "中級": f"{week_name}-中級"
    }

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
    print("✅ Step1: 投稿完了")

async def send_step2_remind():
    await bot.wait_until_ready()
    guild = bot.guilds[0]
    start = get_schedule_start()
    week_name = get_week_name(start)

    for level in ["初級", "中級"]:
        ch_name = f"{week_name}-{level}"
        target_channel = discord.utils.get(guild.text_channels, name=ch_name)
        if not target_channel:
            continue

        week = generate_week_schedule()
        message = f"📢【{week_name} {level}リマインド】\n\n📅 日程ごとの参加状況：\n\n"
        for date in week:
            for msg_id, data in vote_data.items():
                if data.get("channel") != target_channel.id or date not in data:
                    continue
                date_votes = data[date]
                message += f"{date}\n"
                message += f"参加(🟢) " + (", ".join(date_votes["参加(🟢)"].values()) if date_votes["参加(🟢)"] else "なし") + "\n"
                message += f"オンライン可(🟡) " + (", ".join(date_votes["オンライン可(🟡)"].values()) if date_votes["オンライン可(🟡)"] else "なし") + "\n"
                message += f"不可(🔴) " + (", ".join(date_votes["不可(🔴)"].values()) if date_votes["不可(🔴)"] else "なし") + "\n\n"
        await target_channel.send(message)
    print("✅ Step2: テストリマインド送信完了")

async def send_step3_remind():
    await bot.wait_until_ready()
    guild = bot.guilds[0]
    start = get_schedule_start()
    week_name = get_week_name(start)

    for level in ["初級", "中級"]:
        ch_name = f"{week_name}-{level}"
        target_channel = discord.utils.get(guild.text_channels, name=ch_name)
        if not target_channel:
            continue

        role = discord.utils.get(guild.roles, name=level)
        if not role:
            continue

        week = generate_week_schedule()
        message = f"📢【{week_name} {level} 1週間前催促】\n\n"

        all_voted = True
        for date in week:
            for msg_id, data in vote_data.items():
                if data.get("channel") != target_channel.id or date not in data:
                    continue
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

        if message.strip():
            await target_channel.send(message)
    print("✅ Step3: テスト1週間前催促送信完了")

# ====== Step4 確定/不確定コマンド ======
@tree.command(name="確定", description="指定した級の開催を確定として通知")
@app_commands.describe(級="初級 or 中級", 日付="例: 2025-11-09")
async def confirm_event(interaction: discord.Interaction, 級: str, 日付: str):
    guild = interaction.guild
    target_ch = discord.utils.find(lambda c: 級 in c.name, guild.text_channels)
    if target_ch:
        await target_ch.send(f"✅【開催確定】\n{級}の{日付}開催は確定です。参加者の皆さん、よろしくお願いします！")
        await interaction.response.send_message("✅ 確定通知を送信しました。", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ 対象チャンネルが見つかりません。", ephemeral=True)

@tree.command(name="不確定", description="指定した級の開催を不確定として通知")
@app_commands.describe(級="初級 or 中級", 日付="例: 2025-11-09")
async def unconfirm_event(interaction: discord.Interaction, 級: str, 日付: str):
    guild = interaction.guild
    target_ch = discord.utils.find(lambda c: 級 in c.name, guild.text_channels)
    if target_ch:
        await target_ch.send(f"⚠️【開催不確定】\n{級}の{日付}開催は不確定です。ご迷惑をおかけしました。")
        await interaction.response.send_message("✅ 不確定通知を送信しました。", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ 対象チャンネルが見つかりません。", ephemeral=True)

# ====== Scheduler（Step1～3テスト起動） ======
scheduler = AsyncIOScheduler(timezone=JST)

@bot.event
async def on_ready():
    load_votes()
    try:
        await tree.sync()
        print("✅ Slash Commands synced!")
    except Exception as e:
        print(f"⚠ コマンド同期エラー: {e}")

    now = datetime.datetime.now(JST)
    # ===== 固定時刻スケジュール（テスト用） =====
    three_week_test = now.replace(hour=1, minute=50, second=0, microsecond=0)  # Step1
    two_week_test   = now.replace(hour=1, minute=51, second=0, microsecond=0)  # Step2
    one_week_test   = now.replace(hour=1, minute=52, second=0, microsecond=0)  # Step3

    scheduler.add_job(send_step1_schedule, DateTrigger(run_date=three_week_test))
    scheduler.add_job(send_step2_remind,   DateTrigger(run_date=two_week_test))
    scheduler.add_job(send_step3_remind,   DateTrigger(run_date=one_week_test))

    scheduler.start()
    print(f"✅ Logged in as {bot.user}")
    print(f"✅ Scheduler started (Test mode). Step1～3は指定時刻に実行されます。")

# ====== Bot起動 ======
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
