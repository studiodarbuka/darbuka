import discord
from discord import app_commands
import datetime
import os

# IntentsとBotの初期化
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# 投票データ
vote_data = {}

# 投票用View
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="調整可(🟡)", style=discord.ButtonStyle.blurple)
    async def maybe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "調整可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.red)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "不可(🔴)")

    async def register_vote(self, interaction: discord.Interaction, status: str):
        user = interaction.user.name
        message_id = interaction.message.id

        if message_id not in vote_data:
            vote_data[message_id] = {}

        if self.date_str not in vote_data[message_id]:
            vote_data[message_id][self.date_str] = {
                "参加(🟢)": [], "調整可(🟡)": [], "不可(🔴)": []
            }

        # 他の選択肢から削除
        for k in vote_data[message_id][self.date_str]:
            if user in vote_data[message_id][self.date_str][k]:
                vote_data[message_id][self.date_str][k].remove(user)

        # 新しい選択肢に追加
        vote_data[message_id][self.date_str][status].append(user)

        # Embed更新
        embed = interaction.message.embeds[0]
        for k in ["参加(🟢)", "調整可(🟡)", "不可(🔴)"]:
            users = vote_data[message_id][self.date_str][k]
            embed.set_field_at(
                ["参加(🟢)", "調整可(🟡)", "不可(🔴)"].index(k),
                name=k,
                value="\n".join(users) if users else "なし",
                inline=False
            )

        await interaction.response.edit_message(embed=embed, view=self)

# ✅ 修正版 /schedule コマンド（3週間後の日曜から7日間）
@tree.command(name="schedule", description="日程調整を開始します")
async def schedule(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    today = datetime.date.today()

    # 今日から3週間後
    target = today + datetime.timedelta(weeks=3)

    # その週の日曜日を取得（weekday()で0=月曜,6=日曜）
    days_to_sunday = (6 - target.weekday()) % 7
    start_date = target + datetime.timedelta(days=days_to_sunday)

    # 日曜から7日分を生成
    dates = [(start_date + datetime.timedelta(days=i)).strftime("%m/%d(%a)") for i in range(7)]

    for d in dates:
        embed = discord.Embed(title=f"【日程候補】{d}", description="以下のボタンで投票してください")
        embed.add_field(name="参加(🟢)", value="なし", inline=False)
        embed.add_field(name="調整可(🟡)", value="なし", inline=False)
        embed.add_field(name="不可(🔴)", value="なし", inline=False)
        await interaction.channel.send(embed=embed, view=VoteView(d))

    await interaction.followup.send(
        f"📅 {start_date.strftime('%m/%d(%a)')} からの1週間の日程候補を作成しました！",
        ephemeral=True
    )

# /event_now コマンド（突発イベント）
@tree.command(name="event_now", description="突発イベントを作成")
@app_commands.describe(
    title="イベント名",
    description="詳細（任意）",
    date="投票日程（複数可、カンマ区切り、形式: YYYY-MM-DD、例: 2025-10-06）"
)
async def event_now(
    interaction: discord.Interaction,
    title: str,
    date: str,
    description: str = ""
):
    await interaction.response.defer(ephemeral=True)

    dates = []
    for d in date.split(","):
        d_clean = d.strip()
        parsed = None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                parsed = datetime.datetime.strptime(d_clean, fmt).strftime("%m/%d(%a)")
                break
            except ValueError:
                continue
        if not parsed:
            await interaction.followup.send(
                f"⚠️ 日付フォーマットが不正です: {d_clean}（正しい形式: YYYY-MM-DD または YYYY/MM/DD）",
                ephemeral=True
            )
            return
        dates.append(parsed)

    for d in dates:
        embed = discord.Embed(title=f"【突発イベント】{title} - {d}", description=description or "詳細なし")
        embed.add_field(name="参加(🟢)", value="なし", inline=False)
        embed.add_field(name="調整可(🟡)", value="なし", inline=False)
        embed.add_field(name="不可(🔴)", value="なし", inline=False)
        await interaction.channel.send(embed=embed, view=VoteView(d))

    await interaction.followup.send(f"🚨 イベント「{title}」を作成しました！", ephemeral=True)

# Bot起動時にコマンド同期
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        await tree.sync()
        print("✅ Slash commands synced!")
    except Exception as e:
        print(f"❌ Sync error: {e}")

# トークンで起動
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise ValueError("⚠️ DISCORD_BOT_TOKEN が設定されていません。Renderの環境変数を確認してください。")

bot.run(TOKEN)
