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

def generate_week_schedule():
    start = get_schedule_start()
    return [(start + datetime.timedelta(days=i)).strftime("%Y-%m-%d (%a)") for i in range(7)]

# ====== 月第N週の文字列を返す ======
def get_week_name(date):
    month = date.month
    first_day = date.replace(day=1)
    first_sunday = first_day + datetime.timedelta(days=(6 - first_day.weekday()) % 7)
    week_number = ((date - first_sunday).days // 7) + 1
    return f"{month}月第{week_number}週"

# ====== 投票ボタン付きビュー ======
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str

    async def handle_vote(self, interaction: discord.Interaction, status: str):
        message_id = str(interaction.message.id)
        user_name = interaction.user.display_name

        if message_id not in vote_data:
            vote_data[message_id] = {}
        if self.date_str not in vote_data[message_id]:
            vote_data[message_id][self.date_str] = {"参加(🟢)": [], "オンライン可(🟡)": [], "不可(🔴)": []}

        # 前の投票を削除して新しい選択を追加
        for k, v in vote_data[message_id][self.date_str].items():
            if user_name in v:
                v.remove(user_name)
        vote_data[message_id][self.date_str][status].append(user_name)
        save_votes()

        embed = discord.Embed(title=f"【予定候補】{self.date_str}")
        for k, v in vote_data[message_id][self.date_str].items():
            embed.add_field(name=f"{k} ({len(v)}人)", value="\n".join(v) if v else "0人", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="オンライン可(🟡)", style=discord.ButtonStyle.primary)
    async def maybe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "オンライン可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "不可(🔴)")

# ====== Step1: 三週間後の予定作成 ======
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
            vote_data[str(msg.id)] = {date: {"参加(🟢)": [], "オンライン可(🟡)": [], "不可(🔴)": []}}
            save_votes()

    print("✅ Step1: 三週間後スケジュール投稿完了。")

# ====== Step2: 二週間前リマインド（テキスト形式） ======
async def send_step2_remind():
    await bot.wait_until_ready()
    guild = bot.guilds[0]

    channels = [c for c in guild.text_channels if any(x in c.name for x in ["初級", "中級"])]
    if not channels:
        print("⚠️ リマインド対象チャンネルが見つかりません。")
        return

    for ch in channels:
        msg_list = []
        for message_id, date_data in vote_data.items():
            for date_str, votes in date_data.items():
                # 日付部分をパース
                try:
                    date_obj = datetime.datetime.strptime(date_str.split(" ")[0], "%Y-%m-%d")
                except ValueError:
                    continue
                week_ja = ["月", "火", "水", "木", "金", "土", "日"][date_obj.weekday()]
                date_fmt = f"{date_obj.strftime('%-m/%-d')}（{week_ja}）"

                join = votes.get("参加(🟢)", [])
                online = votes.get("オンライン可(🟡)", [])
                no = votes.get("不可(🔴)", [])

                msg_list.append(
                    f"📅 **{date_fmt}**\n"
                    f"　🟢 参加：{', '.join(join) if join else 'なし'}\n"
                    f"　🟡 オンライン可：{', '.join(online) if online else 'なし'}\n"
                    f"　🔴 不可：{', '.join(no) if no else 'なし'}\n"
                )

        if msg_list:
            remind_text = (
                "📢 **【二週間前リマインド】投票状況まとめ**\n"
                "以下は現時点での参加状況です！\n\n" + "\n".join(msg_list)
            )
            await ch.send(remind_text)
            print(f"✅ Step2: {ch.name} にリマインド送信完了。")
        else:
            await ch.send("📢 現在、この週の投票データはまだありません。")
            print(f"⚠️ Step2: {ch.name} に投票データなし。")

# ====== Bot起動時スケジュール設定 ======
@bot.event
async def on_ready():
    print(f"✅ ログイン完了: {bot.user}")
    scheduler = AsyncIOScheduler(timezone=JST)

    # Step1 → 14:51 に実行
    step1_time = datetime.datetime.now(JST).replace(hour=1, minute=20, second=0, microsecond=0)
    if step1_time < datetime.datetime.now(JST):
        step1_time += datetime.timedelta(days=1)
    scheduler.add_job(send_step1_schedule, DateTrigger(run_date=step1_time))

    # Step2 → 14:55 に実行
    step2_time = datetime.datetime.now(JST).replace(hour=1, minute=22, second=0, microsecond=0)
    if step2_time < datetime.datetime.now(JST):
        step2_time += datetime.timedelta(days=1)
    scheduler.add_job(send_step2_remind, DateTrigger(run_date=step2_time))

    scheduler.start()
    print("⏰ Step1・Step2 スケジュールを設定しました。")

# ====== 起動 ======
load_votes()
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
