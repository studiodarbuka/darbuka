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
tree = bot.tree

# ====== 永続保存設定 ======
PERSISTENT_DIR = "/opt/render/project/src/data"
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

# ====== スケジュール生成 ======
def get_schedule_start():
    """3週間後の日曜を取得"""
    today = datetime.datetime.now(JST)
    days_until_sunday = (6 - today.weekday()) % 7
    target = today + datetime.timedelta(days=days_until_sunday + 14)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)

def generate_week_schedule():
    start = get_schedule_start()
    return [(start + datetime.timedelta(days=i)).strftime("%Y-%m-%d (%a)") for i in range(7)]

# ====== ボタン形式投票（トグル対応版） ======
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
            vote_data[message_id][self.date_str] = {"参加(🟢)": [], "調整可(🟡)": [], "不可(🔴)": []}

        user_current_status = None
        for k, v in vote_data[message_id][self.date_str].items():
            if user_name in v:
                user_current_status = k
                break

        # 同じボタン → 削除（トグルオフ）
        if user_current_status == status:
            vote_data[message_id][self.date_str][status].remove(user_name)
        else:
            # まず全てから削除してから新しい方に追加
            for k in vote_data[message_id][self.date_str]:
                if user_name in vote_data[message_id][self.date_str][k]:
                    vote_data[message_id][self.date_str][k].remove(user_name)
            vote_data[message_id][self.date_str][status].append(user_name)

        save_votes()

        # Embed更新
        embed = discord.Embed(title=f"【予定候補】{self.date_str}")
        for k, v in vote_data[message_id][self.date_str].items():
            embed.add_field(name=f"{k} ({len(v)}人)", value="\n".join(v) if v else "0人", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="調整可(🟡)", style=discord.ButtonStyle.primary)
    async def maybe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "調整可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "不可(🔴)")

# ====== Step1: 三週間前スケジュール通知 ======
async def send_step1_schedule():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="wqwq")
    if not channel:
        print("⚠️ チャンネル「wqwq」が見つかりません。")
        return

    week = generate_week_schedule()
    for date in week:
        embed_title = f"📅 三週間後の予定（投票開始） {date}"
        message_id_placeholder = f"tmp-{date}"
        vote_data[message_id_placeholder] = {
            date: {"参加(🟢)": [], "調整可(🟡)": [], "不可(🔴)": []}
        }
        save_votes()

        embed = discord.Embed(title=embed_title)
        for k, v in vote_data[message_id_placeholder][date].items():
            embed.add_field(name=f"{k} ({len(v)}人)", value="\n".join(v) if v else "0人", inline=False)

        view = VoteView(date)
        msg = await channel.send(embed=embed, view=view)

        vote_data[str(msg.id)] = vote_data.pop(message_id_placeholder)
        save_votes()

    print("✅ Step1: 三週間前スケジュール投稿完了。")

# ====== Step2: 二週間前リマインド ======
async def send_step2_remind():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="日程")
    if not channel:
        print("⚠️ チャンネル「日程」が見つかりません。")
        return

    header = "⏰ **2週間前になりました！投票をお願いします！**\n以下、現状の投票状況です：\n"
    all_lines = [header]

    for message_id, dates in vote_data.items():
        for date_str, votes in dates.items():
            all_lines.append(f"📅 {date_str}")
            for status, users in votes.items():
                all_lines.append(f"- {status} ({len(users)}人): " + (", ".join(users) if users else "なし"))
            all_lines.append("")

    text_msg = "```\n" + "\n".join(all_lines) + "\n```"
    await channel.send(text_msg)
    print("✅ Step2: 2週間前リマインド送信完了。")

# ====== /event_now コマンド ======
@tree.command(name="event_now", description="突発イベントを作成します（手動イベント）")
@app_commands.describe(
    title="イベントのタイトルを入力",
    date="イベントの日付を YYYY-MM-DD 形式で入力（例：2025-10-20）",
    detail="イベントの詳細を入力（任意）"
)
async def event_now(interaction: discord.Interaction, title: str, date: str, detail: str = "詳細なし"):
    try:
        datetime.datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        await interaction.response.send_message("⚠ 日付は YYYY-MM-DD 形式で入力してください。", ephemeral=True)
        return

    embed = discord.Embed(title=f"📢 {title}", color=0x00BFFF)
    embed.add_field(name="📅 日付", value=date, inline=False)
    embed.add_field(name="📝 詳細", value=detail, inline=False)
    embed.set_footer(text="投票してください！ 🟢参加 / 🟡調整可 / 🔴不可")

    view = VoteView(date)
    await interaction.response.defer()
    msg = await interaction.channel.send(embed=embed, view=view)

    vote_data[str(msg.id)] = {
        date: {"参加(🟢)": [], "調整可(🟡)": [], "不可(🔴)": []}
    }
    save_votes()

    await interaction.followup.send(f"✅ イベント『{title}』を作成しました！", ephemeral=True)

# ====== on_ready ======
scheduler = AsyncIOScheduler(timezone=JST)

@bot.event
async def on_ready():
    load_votes()
    try:
        await tree.sync()
        print("✅ Slash Commands synced!")
    except Exception as e:
        print(f"⚠️ コマンド同期エラー: {e}")

    now = datetime.datetime.now(JST)
    three_week_test = now.replace(hour=15, minute=8, second=0, microsecond=0)
    two_week_test = now.replace(hour=15, minute=10, second=0, microsecond=0)

    scheduler.add_job(send_step1_schedule, DateTrigger(run_date=three_week_test))
    scheduler.add_job(send_step2_remind, DateTrigger(run_date=two_week_test))
    scheduler.start()

    print(f"✅ Logged in as {bot.user}")
    print("✅ Scheduler started.")

# ====== メイン ======
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("❌ DISCORD_BOT_TOKEN が設定されていません。")
    bot.run(token)
