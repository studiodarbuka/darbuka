import os
import discord
from discord.ext import commands
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

# ====== 永続保存 ======
PERSISTENT_DIR = "./data"
os.makedirs(PERSISTENT_DIR, exist_ok=True)
VOTE_FILE = os.path.join(PERSISTENT_DIR, "votes.json")

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

# ====== 三週間後・日曜始まり週を算出 ======
def get_schedule_start():
    today = datetime.datetime.now(JST)
    days_since_sunday = (today.weekday() + 1) % 7
    this_sunday = today - datetime.timedelta(days=days_since_sunday)
    target = this_sunday + datetime.timedelta(weeks=3)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)

# ====== 日本語曜日で一週間生成 ======
def generate_week_schedule():
    start = get_schedule_start()
    weekday_jp = ["月","火","水","木","金","土","日"]
    return [
        f"{(start + datetime.timedelta(days=i)).strftime('%Y-%m-%d')} ({weekday_jp[(start + datetime.timedelta(days=i)).weekday()]})"
        for i in range(7)
    ]

# ====== 月第N週の文字列を返す ======
def get_week_name(date):
    month = date.month
    first_day = date.replace(day=1)
    first_sunday = first_day + datetime.timedelta(days=(6 - first_day.weekday()) % 7)
    week_number = ((date - first_sunday).days // 7) + 1
    return f"{month}月第{week_number}週"

# ====== Step4用: 確定/不確定ボタン付きビュー ======
class ConfirmView(discord.ui.View):
    def __init__(self, level: str, date_str: str, participants: list, target_channel_id: int):
        super().__init__(timeout=None)
        self.level = level
        self.date_str = date_str
        self.participants = participants
        self.target_channel_id = target_channel_id

    async def send_confirm_message(self, interaction: discord.Interaction, confirmed: bool):
        guild = interaction.guild
        target_channel = guild.get_channel(self.target_channel_id)
        mentions = ", ".join([f"<@{p_id}>" for p_id in self.participants])
        msg_text = f"{self.date_str} の {self.level}クラスは参加者 {len(self.participants)}人 ({mentions}) です。\n"
        if confirmed:
            msg_text += "✅ スタジオ確定通知です！"
        else:
            msg_text += "❌ 残念ながら確定できませんでした。すみません。"

        await target_channel.send(msg_text)
        await interaction.response.edit_message(content=f"✅ 確定通知を送信しました。", view=None)

    @discord.ui.button(label="確定", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_confirm_message(interaction, confirmed=True)

    @discord.ui.button(label="不確定", style=discord.ButtonStyle.danger)
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.send_confirm_message(interaction, confirmed=False)

# ====== 投票ボタン付きビュー（トグル式、user_id管理、Step4自動通知） ======
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

        # Step4チェック（3人以上で通知）
        await self.check_step4(interaction, message_id)

    async def check_step4(self, interaction: discord.Interaction, message_id: str):
        data = vote_data[message_id]
        participants = list(data[self.date_str]["参加(🟢)"].keys())
        if len(participants) < 3:
            return

        guild = interaction.guild
        teacher_role = discord.utils.get(guild.roles, name="講師")
        notify_channel = discord.utils.get(guild.text_channels, name="人数確定通知所")
        if not teacher_role or not notify_channel:
            return

        if data.get(f"{self.date_str}_step4_sent"):
            return
        data[f"{self.date_str}_step4_sent"] = True
        save_votes()

        embed_text = f"{self.date_str} の {interaction.channel.name} クラス\n参加者 {len(participants)}人: " + \
                     ", ".join(data[self.date_str]["参加(🟢)"].values()) + "\nスタジオを抑えてください。"
        view = ConfirmView(level=interaction.channel.name, date_str=self.date_str,
                           participants=participants, target_channel_id=interaction.channel.id)
        await notify_channel.send(content=teacher_role.mention,
                                  embed=discord.Embed(description=embed_text),
                                  view=view)

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="オンライン可(🟡)", style=discord.ButtonStyle.primary)
    async def maybe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "オンライン可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "不可(🔴)")

# ====== Step1: チャンネル作成 + 投票送信 ======
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

    print("✅ Step1: 初級・中級チャンネルへ三週間後スケジュール投稿完了。")

# ====== Step2: 二週間前リマインド ======
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
                if data.get("channel") != target_channel.id:
                    continue
                if date not in data:
                    continue
                date_votes = data[date]
                message += f"{date}\n"
                message += f"参加(🟢) " + (", ".join(date_votes["参加(🟢)"].values()) if date_votes["参加(🟢)"] else "なし") + "\n"
                message += f"オンライン可(🟡) " + (", ".join(date_votes["オンライン可(🟡)"].values()) if date_votes["オンライン可(🟡)"] else "なし") + "\n"
                message += f"不可(🔴) " + (", ".join(date_votes["不可(🔴)"].values()) if date_votes["不可(🔴)"] else "なし") + "\n\n"
        await target_channel.send(message)

    print("✅ Step2: 二週間前リマインド送信完了。")

# ====== Step3: 一週間前催促 ======
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
                if data.get("channel") != target_channel.id:
                    continue
                if date not in data:
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

    print("✅ Step3: 1週間前催促送信完了。")

# ====== Scheduler ======
scheduler = AsyncIOScheduler(timezone=JST)

@bot.event
async def on_ready():
    load_votes()
    print(f"✅ ログイン完了: {bot.user}")

    now = datetime.datetime.now(JST)

    # 実行時刻（Render用に起動直後にStep1〜3も動かせるように）
    step1_time = now + datetime.timedelta(seconds=20)
    step2_time = now + datetime.timedelta(seconds=60)
    step3_time = now + datetime.timedelta(seconds=60)

    scheduler.add_job(send_step1_schedule, DateTrigger(run_date=step1_time))
    scheduler.add_job(send_step2_remind, DateTrigger(run_date=step2_time))
    scheduler.add_job(send_step3_remind, DateTrigger(run_date=step3_time))

    scheduler.start()

# ====== Bot起動 ======
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
