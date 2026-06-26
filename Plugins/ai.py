"""
AI Plugin - Test feature for sendMessageDraft
Command: /ai <prompt>
"""
import asyncio
import random
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from util.logging import log
from config import OWNER_IDS

async def handle_ai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ai command and simulate streaming."""
    user_id = update.effective_user.id
    if user_id not in OWNER_IDS:
        return

    if not context.args:
        await update.message.reply_text("Please provide a prompt. Example: /ai hello")
        return

    prompt = " ".join(context.args)
    chat_id = update.effective_chat.id
    
    # Generate a random non-zero draft_id
    draft_id = random.randint(1000, 999999)
    
    # Dummy response to stream (~3000 characters)
    base_text = f"You said: '{prompt}'.\n\nThis is a simulated AI response streaming token by token using the new sendMessageDraft feature! "
    filler = "Here is some more generated text to simulate a very long AI response. It just keeps generating and generating to show how the stream looks over a longer period of time. "
    
    # Repeat the filler to make it around 3000 characters
    dummy_text = base_text + (filler * 2)
    
    words = dummy_text.split(" ")
    current_text = ""
    
    # Start streaming
    for i, word in enumerate(words):
        current_text += word + " "
        
        # Stream the update every few words
        if i % 3 == 0 or i == len(words) - 1:
            try:
                # Use the new draft feature
                await context.bot.send_message_draft(
                    chat_id=chat_id,
                    draft_id=draft_id,
                    text=current_text.strip()
                )
            except Exception as e:
                log.warning(f"Failed to send draft: {e}")
            
            # Simulate a slower processing delay
            await asyncio.sleep(0.3)
            
    # Finally, send the real message which replaces the draft in the UI
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = [[InlineKeyboardButton("TEST BUTTON", callback_data="test_ai_button")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=current_text.strip(),
            reply_markup=reply_markup
        )
    except Exception as e:
        log.error(f"Failed to send final AI message: {e}")

def register(app: Application) -> None:
    """Register the plugin handlers."""
    # Pass block=False so this long-running streaming handler doesn't block the bot
    # from processing updates for other users simultaneously.
    app.add_handler(CommandHandler("ai", handle_ai, block=False))
