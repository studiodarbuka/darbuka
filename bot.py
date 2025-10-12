import discord
from discord import app_commands
from discord.ext import tasks
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
import datetime
import os

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)
scheduler = AsyncIOScheduler()

# 投稿したいチャンネルIDを設定（実際の値に変更して！）
CHANNEL_ID = 123456789012345678  # ← あなたのDiscordチャンネルIDに書き換え

# ========================
# 予定表を送る関数
# ========================
async def send_schedule_message():
    """予定表を自動投稿する"""
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if not channel:
            print("⚠️ チャンネルが見つかりません。CHANNEL_IDを確認してください。")
            return

        today = datetime.date.today()
        target_date = today + datetime.timedelta(weeks=3)
        embed = discord.Embed(
            title=f"📅 {target_date.strftime('%m/%d')}週の予定調整",
            description="以下の候補日から投票してください！",
            color=discord.Color.blue(),
        )

        # 例：3日分の候補を出す
        for i in range(3):
            date = target_date + datetime.timedelta(days=i)
            embed.add_field(
                name=date.strftime("%m/%d (%a)"),
                value="✅ 参加\n❌ 不可",
                inline=False
            )

        await channel.send(embed=embed)
        print(f"✅ {target_date.strftime('%m/%d')} の予定表を投稿しました！")

    except Exception as e:
        print(f"❌ エラー: {e}")


# ========================
# コマンド登録 (/schedule)
# ========================
@tree.command(name="schedule", description="3週間後の予定調整を投稿します。")
async def schedule_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await send_schedule_message()
    await interaction.followup.send("✅ 予定表を投稿しました！", ephemeral=True)


# ========================
# Bot起動時
# ========================
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ ログイン完了: {bot.user}")

    # テスト：日本時間 2025/10/12 12:20 に一度だけ投稿
    target_time_jst = datetime.datetime(2025, 10, 12, 12, 20)
    # RenderはUTCなので、JST→UTC変換（-9時間）
    target_time_utc = target_time_jst - datetime.timedelta(hours=9)

    now = datetime.datetime.utcnow()
    if now < target_time_utc:
        scheduler.add_job(
            send_schedule_message,
            "date",
            run_date=target_time_utc,
            id="test_schedule"
        )
        scheduler.start()
        print(f"⏰ テストジョブを登録しました（JST {target_time_jst} に実行予定）")
    else:
        print("⚠️ すでに過ぎた時刻です。target_timeを更新してください。")


# ========================
# 起動
# ========================
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
bot.run(TOKEN)
