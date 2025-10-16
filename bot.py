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

# ====== ボタン形式投票 ======
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="調整可(🟡)", style=discord.ButtonStyle.primary)
    async def maybe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "調整可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "不可(🔴)")

    async def register_vote(self, interaction: discord.Interaction, status: str):
        message_id = interaction.message.id
        user_name = interaction.user.display_name

        if message_id not in vote_data:
            vote_data[message_id] = {}
        if self.date_str not in vote_data[message_id]:
            vote_data[message_id][self.date_str] = {"参加(🟢)": [], "調整可(🟡)": [], "不可(🔴)": []}

        user_list = vote_data[message_id][self.date_str][status]

        if user_name in user_list:
            # すでに投票していたら削除（トグルOFF）
            user_list.remove(user_name)
        else:
            # 投票していなければ追加
            user_list.append(user_name)
            # 他の選択肢からは削除（1日1選択のみ）
            for k in vote_data[message_id][self.date_str]:
                if k != status and user_name in vote_data[message_id][self.date_str][k]:
                    vote_data[message_id][self.date_str][k].remove(user_name)

        save_votes()

        # Embed更新（人数をフィールド名に表示）
        embed = discord.Embed(title=f"【予定候補】{self.date_str}")
        for k, v in vote_data[message_id][self.date_str].items():
            embed.add_field(name=f"{k} ({len(v)}人)", value="\n".join(v) if v else "0人", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

# ====== メッセージ送信 ======
async def send_step1_schedule():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="wqwq")
    if not channel:
        print("⚠️ チャンネル「wqwq」が見つかりません。")
        return

    week = generate_week_schedule()
    for date in week:
        # 初期投票データを作成して保存
        embed_title = f"📅 三週間後の予定（投票開始） {date}"
        message_id_placeholder = f"tmp-{date}"  # 仮ID
        vote_data[message_id_placeholder] = {
            date: {"参加(🟢)": [], "調整可(🟡)": [], "不可(🔴)": []}
        }
        save_votes()

        # Embed作成（人数を表示）
        embed = discord.Embed(title=embed_title)
        for k, v in vote_data[message_id_placeholder][date].items():
            embed.add_field(name=f"{k} ({len(v)}人)", value="\n".join(v) if v else "0人", inline=False)

        view = VoteView(date)
        msg = await channel.send(embed=embed, view=view)

        # message.id に合わせて vote_data を更新
        vote_data[msg.id] = vote_data.pop(message_id_placeholder)
        save_votes()

    print("✅ Step1: 三週間前スケジュール投稿完了。")

async def send_step2_remind():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="日程")
    if not channel:
        print("⚠️ チャンネル「日程」が見つかりません。")
        return

    # ヘッダー
    header = "⏰ **2週間前になりました！投票をお願いします！**\n以下、現状の投票状況です：\n"
    all_lines = [header]

    # 投票状況をまとめてテキスト形式で作成
    for message_id, dates in vote_data.items():
        for date_str, votes in dates.items():
            all_lines.append(f"📅 {date_str}")
            for status, users in votes.items():
                all_lines.append(f"- {status} ({len(users)}人): " + (", ".join(users) if users else "なし"))
            all_lines.append("")  # 日付ごとに空行

    text_msg = "```\n" + "\n".join(all_lines) + "\n```"
    await channel.send(text_msg)

    print("✅ Step2: 2週間前リマインド送信完了。")

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
    # 三週間前通知テスト
    three_week_test = now.replace(hour=15, minute=08, second=0, microsecond=0)
    scheduler.add_job(send_step1_schedule, DateTrigger(run_date=three_week_test))

    # 二週間前リマインドテスト
    two_week_test = now.replace(hour=15, minute=10, second=0, microsecond=0)
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
