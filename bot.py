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
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ====== 永続保存 ======
PERSISTENT_DIR = "/opt/render/project/src/data"
os.makedirs(PERSISTENT_DIR, exist_ok=True)
VOTE_FILE = os.path.join(PERSISTENT_DIR, "votes.json")
CONFIRM_FILE = os.path.join(PERSISTENT_DIR, "confirmed.json")

# ====== タイムゾーン ======
JST = pytz.timezone("Asia/Tokyo")

# ====== データ ======
vote_data = {}
confirmed_dates = {}

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
    global confirmed_dates
    if os.path.exists(CONFIRM_FILE):
        with open(CONFIRM_FILE, "r", encoding="utf-8") as f:
            confirmed_dates = json.load(f)
    else:
        confirmed_dates = {}

def save_confirmed():
    with open(CONFIRM_FILE, "w", encoding="utf-8") as f:
        json.dump(confirmed_dates, f, ensure_ascii=False, indent=2)

# ====== スケジュール生成 ======
def get_schedule_start():
    today = datetime.datetime.now(JST)
    days_until_sunday = (6 - today.weekday()) % 7
    target = today + datetime.timedelta(days=days_until_sunday + 14)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)

def generate_week_schedule():
    start = get_schedule_start()
    return [(start + datetime.timedelta(days=i)).strftime("%Y-%m-%d (%a)") for i in range(7)]

# ====== ボタン形式投票 ======
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

        user_current_status = None
        for k, v in vote_data[message_id][self.date_str].items():
            if user_name in v:
                user_current_status = k
                break

        if user_current_status == status:
            vote_data[message_id][self.date_str][status].remove(user_name)
        else:
            for k in vote_data[message_id][self.date_str]:
                if user_name in vote_data[message_id][self.date_str][k]:
                    vote_data[message_id][self.date_str][k].remove(user_name)
            vote_data[message_id][self.date_str][status].append(user_name)

        save_votes()
        await self.update_embed(interaction)
        await check_dynamic_confirm(interaction.channel, self.date_str)

    async def update_embed(self, interaction):
        message_id = str(interaction.message.id)
        embed = discord.Embed(title=f"【予定候補】{self.date_str}")
        for k, v in vote_data[message_id][self.date_str].items():
            if isinstance(v, list):
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

# ====== Step1: 三週間前スケジュール ======
async def send_step1_schedule():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="wqwq")
    if not channel:
        print("⚠️ チャンネル「wqwq」が見つかりません。")
        return

    week = generate_week_schedule()
    for date in week:
        placeholder_id = f"tmp-{date}"
        vote_data[placeholder_id] = {date: {"参加(🟢)": [], "オンライン可(🟡)": [], "不可(🔴)": []}}
        save_votes()

        embed = discord.Embed(title=f"📅 三週間後の予定（投票開始） {date}")
        for k, v in vote_data[placeholder_id][date].items():
            embed.add_field(name=f"{k} ({len(v)}人)", value="\n".join(v) if v else "0人", inline=False)

        view = VoteView(date)
        msg = await channel.send(embed=embed, view=view)
        vote_data[str(msg.id)] = vote_data.pop(placeholder_id)
        save_votes()

    print("✅ Step1: 三週間前スケジュール投稿完了")

# ====== Step2: 二週間前リマインド ======
async def send_step2_remind():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="日程")
    if not channel:
        print("⚠️ チャンネル「日程」が見つかりません。")
        return

    header = "⏰ **2週間前になりました！投票をお願いします！**\n現状の投票状況：\n"
    for message_id, dates in vote_data.items():
        for date_str, votes in dates.items():
            lines = [header, f"📅 {date_str}"]
            for status, users in votes.items():
                if isinstance(users, list):
                    lines.append(f"- {status} ({len(users)}人): " + (", ".join(users) if users else "なし"))
            await channel.send("```\n" + "\n".join(lines) + "\n```")

    print("✅ Step2: 2週間前リマインド送信完了")

# ====== Step3: 未投票者催促 + 確定通知 + 前日・当日通知 ======
async def send_step3_confirm():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="日程")
    if not channel:
        print("⚠️ チャンネル「日程」が見つかりません。")
        return

    load_votes()
    load_confirmed()
    exclude_users = [bot.user.display_name]

    for message_id, dates in vote_data.items():
        for date_str, votes in dates.items():
            voted_users = set(u for v in votes.values() if isinstance(v, list) for u in v)
            guild = channel.guild
            unvoted_mentions = [
                m.mention for m in guild.members
                if m.display_name not in voted_users and
                   m.display_name not in exclude_users and
                   channel.permissions_for(m).send_messages
            ]
            if unvoted_mentions:
                await channel.send(f"📅 {date_str}\n未投票者: {', '.join(unvoted_mentions)}")

            await check_dynamic_confirm(channel, date_str)

async def check_dynamic_confirm(channel, date_str):
    load_confirmed()
    if confirmed_dates.get(date_str, {}).get("確定通知済み"):
        return

    participants = []
    for msg_id, dates in vote_data.items():
        if date_str in dates:
            participants = dates[date_str].get("参加(🟢)", [])
            break
    if len(participants) >= 3:
        guild = channel.guild
        member_mentions = [m.mention for m in guild.members if m.display_name in participants]
        msg = (
            f"こんにちは！今週のレッスン日程が決まったよ！\n\n"
            f"日時：{date_str}\n場所：朝霧台駅前 ABLE I 2st\nメンバー：{' '.join(member_mentions)}\n\n"
            "調整ありがとう、当日は遅れずに来てね！"
        )
        await channel.send(msg)

        if date_str not in confirmed_dates:
            confirmed_dates[date_str] = {}
        confirmed_dates[date_str]["確定通知済み"] = True
        save_confirmed()

        # 前日20時通知
        date_dt = datetime.datetime.strptime(date_str[:10], "%Y-%m-%d")
        pre_day_dt = datetime.datetime.combine(date_dt - datetime.timedelta(days=1),
                                               datetime.time(hour=20, minute=0, tzinfo=JST))
        morning_dt = datetime.datetime.combine(date_dt,
                                              datetime.time(hour=8, minute=0, tzinfo=JST))

        scheduler.add_job(send_pre_day_notify, DateTrigger(run_date=pre_day_dt),
                          args=[channel.id, date_str, "前日20時"])
        scheduler.add_job(send_pre_day_notify, DateTrigger(run_date=morning_dt),
                          args=[channel.id, date_str, "当日朝8時"])

async def send_pre_day_notify(channel_id, date_str, notify_type):
    load_confirmed()
    if confirmed_dates.get(date_str, {}).get(f"{notify_type}_済み"):
        return
    channel = bot.get_channel(channel_id)
    if not channel:
        return

    participants = []
    for msg_id, dates in vote_data.items():
        if date_str in dates:
            participants = dates[date_str].get("参加(🟢)", [])
            break
    if not participants:
        return

    guild = channel.guild
    member_mentions = [m.mention for m in guild.members if m.display_name in participants]
    await channel.send(f"{notify_type}です！レッスン日程のお知らせ\n\n日時：{date_str}\n場所：朝霧台駅前 ABLE I 2st\nメンバー：{' '.join(member_mentions)}")

    confirmed_dates[date_str][f"{notify_type}_済み"] = True
    save_confirmed()

# ====== /event_now 突発イベント ======
@tree.command(name="event_now", description="突発イベントを作成します")
@app_commands.describe(title="イベントのタイトル", date="YYYY-MM-DD形式の日付", detail="詳細（任意）")
async def event_now(interaction: discord.Interaction, title: str, date: str, detail: str = "詳細なし"):
    try:
        datetime.datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        await interaction.response.send_message("⚠ 日付は YYYY-MM-DD 形式で入力してください。", ephemeral=True)
        return

    embed = discord.Embed(title=f"📢 {title}", color=0x00BFFF)
    embed.add_field(name="📅 日付", value=date, inline=False)
    embed.add_field(name="📝 詳細", value=detail, inline=False)
    embed.set_footer(text="投票してください！ 🟢参加 / 🟡オンライン可 / 🔴不可")
    view = VoteView(date)
    await interaction.response.defer()
    msg = await interaction.channel.send(embed=embed, view=view)
    vote_data[str(msg.id)] = {date: {"参加(🟢)": [], "オンライン可(🟡)": [], "不可(🔴)": []}}
    save_votes()
    await interaction.followup.send("✅ 突発イベントを作成しました！", ephemeral=True)

# ====== on_ready + テスト用 Scheduler ======
scheduler = AsyncIOScheduler(timezone=JST)

@bot.event
async def on_ready():
    load_votes()
    load_confirmed()
    try:
        await tree.sync()
        print("✅ Slash Commands synced!")
    except Exception as e:
        print(f"⚠ コマンド同期エラー: {e}")

    now = datetime.datetime.now(JST)
    # ===== テスト用秒単位スケジュール =====
    three_week_test = now.replace(hour=23, minute=10, second=0, microsecond=0)
    two_week_test = now.replace(hour=23, minute=12, second=0, microsecond=0)
    one_week_test = now.replace(hour=23, minute=14, second=0, microsecond=0)

    scheduler.add_job(send_step1_schedule, DateTrigger(run_date=three_week_test))
    scheduler.add_job(send_step2_remind, DateTrigger(run_date=two_week_test))
    scheduler.add_job(send_step3_confirm, DateTrigger(run_date=one_week_test))

    scheduler.start()
    print(f"✅ Logged in as {bot.user}")
    print("✅ Scheduler started (Test mode). Step1～3 will run in 10/20/30 seconds)")

# ====== メイン ======
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("❌ DISCORD_BOT_TOKEN が設定されていません。")
    bot.run(token)
