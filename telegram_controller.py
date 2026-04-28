import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- CONFIGURATION ---
# Your unique bot token from BotFather
TELEGRAM_TOKEN = "8586430735:AAFR16Gw8QZ-JqCIMRMBiM-_VonyevW4f-k"

# Your GitHub credentials for alirezas7/global-arbitrage
GITHUB_TOKEN = "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"
GITHUB_OWNER = "alirezas7"
GITHUB_REPO = "global-arbitrage"

# These must match your .yml filenames in .github/workflows
WORKFLOWS = {
    "nba": "nba.yml",
    "soccer": "soccer.yml",
    "ufc": "ufc.yml"
}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramController:
    def __init__(self):
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {GITHUB_TOKEN}"
        }

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 Arbitrage Controller Active.\n\n"
            "Use these commands to trigger scans:\n"
            "/run_nba - Start NBA Sniper\n"
            "/run_soccer - Start Soccer Sniper\n"
            "/run_ufc - Start UFC Sniper"
        )

    async def trigger_workflow(self, update: Update, sport: str):
        workflow_file = WORKFLOWS.get(sport)
        url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{workflow_file}/dispatches"
        data = {"ref": "main"}

        try:
            response = requests.post(url, headers=self.headers, json=data)
            response.raise_for_status()
            await update.message.reply_text(f"🚀 Success! GitHub is now starting the {sport.upper()} scanner.")
        except Exception as e:
            await update.message.reply_text(f"❌ Failed to trigger GitHub: {str(e)}")

    async def run_nba(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.trigger_workflow(update, "nba")

    async def run_soccer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.trigger_workflow(update, "soccer")

    async def run_ufc(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.trigger_workflow(update, "ufc")

if __name__ == "__main__":
    controller = TelegramController()
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", controller.start))
    application.add_handler(CommandHandler("run_nba", controller.run_nba))
    application.add_handler(CommandHandler("run_soccer", controller.run_soccer))
    application.add_handler(CommandHandler("run_ufc", controller.run_ufc))

    print("✅ Telegram Controller is listening for commands...")
    application.run_polling()
