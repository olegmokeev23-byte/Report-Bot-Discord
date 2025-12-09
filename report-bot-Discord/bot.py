import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
import asyncio
from datetime import datetime
import os
from dotenv import load_dotenv
from config import REPORT_CHANNEL_ID, MOD_CHANNEL_ID, COLORS

load_dotenv()

# Настройка бота
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Хранилище репортов (в продакшене лучше использовать БД)
reports = {}


# ═══════════════════════════════════════════════════════
# МОДАЛЬНОЕ ОКНО ДЛЯ ОТВЕТА МОДЕРАТОРА
# ═══════════════════════════════════════════════════════
class ResponseModal(Modal, title="Ответ на репорт"):
    response = TextInput(
        label="Ваш ответ пользователю",
        style=discord.TextStyle.paragraph,
        placeholder="Введите ответ на репорт...",
        required=True,
        max_length=1000
    )
    
    def __init__(self, report_id: str, user_id: int):
        super().__init__()
        self.report_id = report_id
        self.user_id = user_id
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            user = await bot.fetch_user(self.user_id)
            
            # Создаём embed для пользователя
            embed = discord.Embed(
                title="📬 Ответ на ваш репорт",
                description=self.response.value,
                color=COLORS["accepted"],
                timestamp=datetime.now()
            )
            embed.add_field(name="ID репорта", value=f"`{self.report_id}`", inline=True)
            embed.add_field(name="Модератор", value=interaction.user.mention, inline=True)
            embed.set_footer(text="Спасибо за обращение!")
            
            await user.send(embed=embed)
            await interaction.response.send_message(
                f"✅ Ответ отправлен пользователю {user.mention}!", 
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Не удалось отправить сообщение пользователю (ЛС закрыты)", 
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Ошибка: {e}", 
                ephemeral=True
            )


# ═══════════════════════════════════════════════════════
# КНОПКИ ДЛЯ МОДЕРАТОРОВ
# ═══════════════════════════════════════════════════════
class ReportButtons(View):
    def __init__(self, report_id: str, user_id: int):
        super().__init__(timeout=None)
        self.report_id = report_id
        self.user_id = user_id
    
    @discord.ui.button(label="✅ Принять", style=discord.ButtonStyle.success, custom_id="accept")
    async def accept_button(self, interaction: discord.Interaction, button: Button):
        await self.update_status(interaction, "accepted", "✅ Принят")
    
    @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.danger, custom_id="reject")
    async def reject_button(self, interaction: discord.Interaction, button: Button):
        await self.update_status(interaction, "rejected", "❌ Отклонён")
    
    @discord.ui.button(label="🔄 В процессе", style=discord.ButtonStyle.primary, custom_id="progress")
    async def progress_button(self, interaction: discord.Interaction, button: Button):
        await self.update_status(interaction, "in_progress", "🔄 В процессе")
    
    @discord.ui.button(label="💬 Ответить", style=discord.ButtonStyle.secondary, custom_id="respond")
    async def respond_button(self, interaction: discord.Interaction, button: Button):
        modal = ResponseModal(self.report_id, self.user_id)
        await interaction.response.send_modal(modal)
    
    async def update_status(self, interaction: discord.Interaction, status: str, status_text: str):
        embed = interaction.message.embeds[0]
        embed.color = COLORS[status]
        
        # Обновляем или добавляем поле статуса
        for i, field in enumerate(embed.fields):
            if field.name == "Статус":
                embed.set_field_at(i, name="Статус", value=status_text, inline=True)
                break
        else:
            embed.add_field(name="Статус", value=status_text, inline=True)
        
        # Добавляем информацию о модераторе
        embed.add_field(
            name="Обработал", 
            value=f"{interaction.user.mention}", 
            inline=True
        )
        embed.timestamp = datetime.now()
        
        await interaction.response.edit_message(embed=embed, view=self)
        
        # Уведомляем пользователя
        try:
            user = await bot.fetch_user(self.user_id)
            notify_embed = discord.Embed(
                title="📋 Статус вашего репорта обновлён",
                description=f"Репорт `{self.report_id}` изменил статус на: **{status_text}**",
                color=COLORS[status],
                timestamp=datetime.now()
            )
            await user.send(embed=notify_embed)
        except:
            pass


# ═══════════════════════════════════════════════════════
# КОМАНДА /REPORT
# ═══════════════════════════════════════════════════════
@bot.tree.command(name="report", description="Отправить репорт модераторам")
@app_commands.describe(
    тип="Тип репорта",
    нарушитель="Пользователь, на которого жалоба (опционально)",
    описание="Подробное описание проблемы",
    доказательства="Ссылка на скриншот/видео (опционально)"
)
@app_commands.choices(тип=[
    app_commands.Choice(name="🚫 Нарушение правил", value="rules"),
    app_commands.Choice(name="👤 Жалоба на игрока", value="player"),
    app_commands.Choice(name="🐛 Баг/Ошибка", value="bug"),
    app_commands.Choice(name="💬 Оскорбление", value="insult"),
    app_commands.Choice(name="🎭 Мошенничество", value="scam"),
    app_commands.Choice(name="❓ Другое", value="other"),
])
async def report(
    interaction: discord.Interaction,
    тип: app_commands.Choice[str],
    описание: str,
    нарушитель: discord.Member = None,
    доказательства: str = None
):
    # Проверяем, что команда используется в правильном канале
    if interaction.channel_id != REPORT_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ Эту команду можно использовать только в канале <#{REPORT_CHANNEL_ID}>!",
            ephemeral=True
        )
        return
    
    # Генерируем ID репорта
    report_id = f"RPT-{interaction.user.id}-{int(datetime.now().timestamp())}"
    
    # Создаём embed для модераторов
    embed = discord.Embed(
        title="📩 Новый репорт",
        description=f"```{описание}```",
        color=COLORS["pending"],
        timestamp=datetime.now()
    )
    
    embed.add_field(name="🆔 ID репорта", value=f"`{report_id}`", inline=True)
    embed.add_field(name="📁 Тип", value=тип.name, inline=True)
    embed.add_field(name="Статус", value="⏳ Ожидает", inline=True)
    
    embed.add_field(
        name="👤 Отправитель", 
        value=f"{interaction.user.mention}\n`{interaction.user.id}`", 
        inline=True
    )
    
    if нарушитель:
        embed.add_field(
            name="🎯 Нарушитель", 
            value=f"{нарушитель.mention}\n`{нарушитель.id}`", 
            inline=True
        )
    
    if доказательства:
        embed.add_field(name="🔗 Доказательства", value=доказательства, inline=False)
    
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.set_footer(text=f"Сервер: {interaction.guild.name}")
    
    # Отправляем в канал модераторов
    mod_channel = bot.get_channel(MOD_CHANNEL_ID)
    
    if mod_channel:
        view = ReportButtons(report_id, interaction.user.id)
        await mod_channel.send(embed=embed, view=view)
        
        # Сохраняем репорт
        reports[report_id] = {
            "user_id": interaction.user.id,
            "type": тип.value,
            "description": описание,
            "status": "pending"
        }
        
        # Подтверждение пользователю
        confirm_embed = discord.Embed(
            title="✅ Репорт отправлен!",
            description="Ваш репорт был успешно отправлен модераторам.",
            color=COLORS["accepted"]
        )
        confirm_embed.add_field(name="ID репорта", value=f"`{report_id}`", inline=False)
        confirm_embed.add_field(name="Тип", value=тип.name, inline=True)
        confirm_embed.set_footer(text="Ожидайте ответа в личных сообщениях")
        
        await interaction.response.send_message(embed=confirm_embed, ephemeral=True)
    else:
        await interaction.response.send_message(
            "❌ Ошибка: канал модераторов не найден!", 
            ephemeral=True
        )


# ═══════════════════════════════════════════════════════
# СОБЫТИЯ БОТА
# ═══════════════════════════════════════════════════════
@bot.event
async def on_ready():
    print(f"{'═' * 50}")
    print(f"🤖 Бот {bot.user.name} запущен!")
    print(f"📊 Серверов: {len(bot.guilds)}")
    print(f"{'═' * 50}")
    
    # Синхронизация команд
    try:
        synced = await bot.tree.sync()
        print(f"✅ Синхронизировано {len(synced)} команд")
    except Exception as e:
        print(f"❌ Ошибка синхронизации: {e}")
    
    # Устанавливаем статус
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching, 
            name="за репортами | /report"
        )
    )


@bot.event
async def on_command_error(ctx, error):
    print(f"Ошибка: {error}")


# ═══════════════════════════════════════════════════════
# ЗАПУСК БОТА
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))