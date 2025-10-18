import os
import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import datetime
import pytz
import json

# ====== 基本設定 ======
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
JST = pytz.timezone("Asia/Tokyo")
scheduler = AsyncIOScheduler(timezone=JST)

# ====== 永続データ ======
VOTE_FILE = "votes.json"

vote_data = {
    "初級": {},
    "中級": {}
}

# ====== データロード/セーブ ======
def load_votes():
    global vote_data
    if os.path.exists(VOTE_FILE):
        with open(VOTE_FILE, "r", encoding="utf-8") as f:
            vote_data = json.load(f)
        print("✅ 投票データ読み込み完了")
    else:
        print("⚠ 投票データなし、新規作成")


def save_votes():
    with open(VOTE_FILE, "w", encoding="utf-8") as f:
        json.dump(vote_data, f, ensure_ascii=False, indent=2)
    print("💾 投票データ保存")


# ====== Step1: 三週間後の予定送信 ======
async def send_step1_schedule():
    await bot.wait_until_ready()
    guild = bot.guilds[0]
    print("🟢 Step1 実行開始")

    today = datetime.datetime.now(JST).date()
    target_start = today + datetime.timedelta(weeks=3)
    week_dates = [target_start + datetime.timedelta(days=i) for i in range(7)]

    for level in ["初級", "中級"]:
        text = f"📅【{level}クラス】三週間後の予定（{week_dates[0]}〜{week_dates[-1]}）\n\n"
        for d in week_dates:
            date_str = d.strftime("%Y-%m-%d")
            weekday_jp = ["月", "火", "水", "木", "金", "土", "日"][d.weekday()]
            text += f"{date_str}（{weekday_jp}）\n"
            text += "🟢 参加\n🟡 オンライン可\n🔴 不可\n\n"
            if date_str not in vote_data[level]:
                vote_data[level][date_str] = {"🟢": [], "🟡": [], "🔴": []}

        # ✅ 部分一致でチャンネル取得
        target_channel = next((ch for ch in guild.text_channels if level in ch.name), None)
        if target_channel:
            msg = await target_channel.send(text)
            for emoji in ["🟢", "🟡", "🔴"]:
                await msg.add_reaction(emoji)
            print(f"✅ {level} にStep1送信完了")
        else:
            print(f"⚠ {level}チャンネルが見つかりません")

    save_votes()


# ====== Step2: 二週間前リマインド ======
async def send_step2_reminder():
    await bot.wait_until_ready()
    guild = bot.guilds[0]
    print("🟡 Step2 実行開始")

    for level, dates in vote_data.items():
        text = f"📢【{level}リマインド】\n\n📅 参加状況まとめ：\n\n"

        for date_str, reactions in dates.items():
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            weekday_jp = ["月", "火", "水", "木", "金", "土", "日"][dt.weekday()]
            text += f"{date_str}（{weekday_jp}）\n"
            text += f"🟢 参加：{', '.join(reactions['🟢']) if reactions['🟢'] else 'なし'}\n"
            text += f"🟡 オンライン可：{', '.join(reactions['🟡']) if reactions['🟡'] else 'なし'}\n"
            text += f"🔴 不可：{', '.join(reactions['🔴']) if reactions['🔴'] else 'なし'}\n\n"

        # ✅ 修正版：部分一致検索
        target_channel = next((ch for ch in guild.text_channels if level in ch.name), None)
        if target_channel:
            await target_channel.send(text)
            print(f"✅ {level} にリマインド送信完了")
        else:
            print(f"⚠ {level} のチャンネルが見つかりません")


# ====== Bot起動時処理 ======
@bot.event
async def on_ready():
    print(f"✅ ログイン完了：{bot.user}")
    load_votes()

    now = datetime.datetime.now(JST)
    # テスト動作用スケジュール
    scheduler.add_job(send_step1_schedule, "date", run_date=now + datetime.timedelta(seconds=10))
    scheduler.add_job(send_step2_reminder, "date", run_date=now + datetime.timedelta(seconds=30))

    scheduler.start()
    print("🕒 スケジューラ開始")


# ====== 投票リアクション監視 ======
@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return

    msg = reaction.message
    level = "初級" if "初級" in msg.channel.name else "中級" if "中級" in msg.channel.name else None
    if not level:
        return

    # メッセージ本文から日付抽出
    lines = msg.content.split("\n")
    for line in lines:
        if line.startswith("20"):  # 日付行
            date_str = line.split("（")[0]
            if date_str in vote_data[level]:
                for emoji in ["🟢", "🟡", "🔴"]:
                    if user.name in vote_data[level][emoji]:
                        vote_data[level][emoji].remove(user.name)
                vote_data[level][reaction.emoji].append(user.name)

    save_votes()


# ====== 起動 ======
TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)
