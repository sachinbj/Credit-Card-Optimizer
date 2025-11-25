#!/usr/bin/env python3
"""
Telegram Bot for Credit Card Usage Optimization
Suggests best card for expenses and tracks spending history
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Bot token - replace with your actual token from @BotFather
BOT_TOKEN = "8234566254:AAGDB-ynor-r6ppO-ShsYdEA_lUd-umvU-I"

# Conversation states
CATEGORY, AMOUNT, VOUCHER, SAVE_EXPENSE = range(4)

# Data directory
DATA_DIR = "user_data"
os.makedirs(DATA_DIR, exist_ok=True)


class CreditCard:
    def __init__(self, name, card_type, base_rate, vouchers=None, special=None, 
                 exclusions=None, annual_fee=None, fee_waiver_spend=None):
        self.name = name
        self.card_type = card_type
        self.base_rate = base_rate
        self.vouchers = vouchers or []
        self.special = special or []
        self.exclusions = exclusions or []
        self.annual_fee = annual_fee
        self.fee_waiver_spend = fee_waiver_spend
        
    def get_reward_rate(self, category, amount, via_voucher=None):
        if any(excl.lower() in category.lower() for excl in self.exclusions):
            return 0, "Excluded category"
        
        if via_voucher:
            for voucher in self.vouchers:
                if voucher['name'].lower() in via_voucher.lower():
                    return voucher['rate'], f"Via {voucher['name']} voucher"
            return 0, "Voucher not available"
        
        for special in self.special:
            if special['category'].lower() in category.lower() or category.lower() in special['category'].lower():
                limit = special.get('limit')
                if limit:
                    return special['rate'], f"Special rate (₹{limit:,} monthly cap)"
                return special['rate'], "Special rate"
        
        return self.base_rate, "Base rate"
    
    def calculate_rewards(self, amount, rate):
        if self.card_type == "points":
            return amount * rate / 100, "points"
        else:
            return amount * rate / 100, "cashback"


# Define all cards
CARDS = [
    CreditCard(
        name="HDFC Infinia (Primary)",
        card_type="points",
        base_rate=5/150 * 100,
        vouchers=[
            {'name': 'Amazon Pay', 'rate': 25/150 * 100, 'limit': 10000},
            {'name': 'Amazon Shopping', 'rate': 25/150 * 100, 'limit': 10000},
            {'name': 'Flipkart', 'rate': 25/150 * 100, 'limit': 10000},
            {'name': 'Myntra', 'rate': 25/150 * 100, 'limit': 25000}
        ],
        exclusions=['Tax', 'Fuel', 'Rent', 'Government', 'E-wallet']
    ),
    CreditCard(
        name="HDFC Infinia (Add-on)",
        card_type="points",
        base_rate=5/150 * 100,
        vouchers=[
            {'name': 'Amazon Pay', 'rate': 25/150 * 100, 'limit': 10000},
            {'name': 'Amazon Shopping', 'rate': 25/150 * 100, 'limit': 10000},
            {'name': 'Flipkart', 'rate': 25/150 * 100, 'limit': 10000},
            {'name': 'Myntra', 'rate': 25/150 * 100, 'limit': 25000}
        ],
        exclusions=['Tax', 'Fuel', 'Rent', 'Government', 'E-wallet']
    ),
    CreditCard(
        name="ICICI Emerald Private Metal",
        card_type="points",
        base_rate=6/200 * 100,
        vouchers=[
            {'name': 'Amazon Pay', 'rate': 36/200 * 100, 'limit': 12000},
            {'name': 'Amazon Shopping', 'rate': 36/200 * 100, 'limit': 10000},
            {'name': 'Flipkart', 'rate': 36/200 * 100, 'limit': 10000},
            {'name': 'Myntra', 'rate': 36/200 * 100, 'limit': 10000}
        ],
        exclusions=['Jewellery', 'Tax', 'Fuel', 'Rent', 'Government', 'E-wallet'],
        annual_fee=12499 * 1.18,
        fee_waiver_spend=1000000
    ),
    CreditCard(
        name="ICICI Amazon Pay",
        card_type="cashback",
        base_rate=1,
        special=[
            {'category': 'Amazon Shopping', 'rate': 5},
            {'category': 'Amazon Pay Voucher', 'rate': 4, 'limit': 20000},
            {'category': 'Myntra Voucher', 'rate': 4, 'limit': 10000}
        ]
    ),
    CreditCard(
        name="HSBC Live+",
        card_type="cashback",
        base_rate=1.5,
        special=[
            {'category': 'Grocery', 'rate': 10},
            {'category': 'Dining', 'rate': 10},
            {'category': 'Food Delivery', 'rate': 10}
        ],
        exclusions=['Fuel', 'E-wallet', 'Rent', 'EMI', 'Insurance', 'Utilities']
    ),
    CreditCard(
        name="HDFC Swiggy",
        card_type="cashback",
        base_rate=1,
        special=[
            {'category': 'Swiggy', 'rate': 10, 'limit': 1500},
            {'category': 'Instamart', 'rate': 10, 'limit': 1500},
            {'category': 'Dineout', 'rate': 10, 'limit': 1500},
            {'category': 'Amazon', 'rate': 5, 'limit': 1500},
            {'category': 'Flipkart', 'rate': 5, 'limit': 1500},
            {'category': 'Uber', 'rate': 5, 'limit': 1500}
        ],
        exclusions=['Tax', 'Fuel', 'Rent', 'Government', 'E-wallet']
    ),
    CreditCard(
        name="HDFC Tata Neu Infinity",
        card_type="cashback",
        base_rate=0,
        special=[
            {'category': 'Tata Neu', 'rate': 5},
            {'category': 'Amazon Pay Voucher', 'rate': 5},
            {'category': 'Flipkart Voucher', 'rate': 5},
            {'category': 'Myntra Voucher', 'rate': 5}
        ]
    )
]


class ExpenseTracker:
    def __init__(self, user_id):
        self.user_id = user_id
        self.file_path = os.path.join(DATA_DIR, f"user_{user_id}.json")
        self.expenses = self.load_expenses()
    
    def load_expenses(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r') as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def save_expenses(self):
        with open(self.file_path, 'w') as f:
            json.dump(self.expenses, f, indent=2)
    
    def add_expense(self, category, amount, card_name, via_voucher=None):
        expense = {
            'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'category': category,
            'amount': amount,
            'card': card_name,
            'via_voucher': via_voucher
        }
        self.expenses.append(expense)
        self.save_expenses()
    
    def get_current_month_expenses(self):
        current_month = datetime.now().strftime('%Y-%m')
        return [e for e in self.expenses if e['date'].startswith(current_month)]
    
    def get_voucher_usage(self, card_name, voucher_name):
        month_expenses = self.get_current_month_expenses()
        total = 0
        for exp in month_expenses:
            if exp['card'] == card_name and exp.get('via_voucher') == voucher_name:
                total += exp['amount']
        return total
    
    def get_card_spend(self, card_name):
        month_expenses = self.get_current_month_expenses()
        return sum(e['amount'] for e in month_expenses if e['card'] == card_name)
    
    def get_annual_card_spend(self, card_name):
        current_year = datetime.now().year
        year_expenses = [e for e in self.expenses if e['date'].startswith(str(current_year))]
        return sum(e['amount'] for e in year_expenses if e['card'] == card_name)


def find_best_card_with_limits(category, amount, via_voucher, tracker, prefer_emerald=False):
    best_card = None
    best_rate = 0
    best_reason = ""
    
    for card in CARDS:
        rate, reason = card.get_reward_rate(category, amount, via_voucher)
        
        if via_voucher and rate > 0:
            for voucher in card.vouchers:
                if voucher['name'].lower() in via_voucher.lower():
                    used = tracker.get_voucher_usage(card.name, voucher['name'])
                    remaining = voucher['limit'] - used
                    if amount > remaining:
                        rate = 0
                        reason = f"Limit exceeded (₹{used:,}/₹{voucher['limit']:,} used)"
                    else:
                        reason += f" [₹{remaining:,} left]"
                    break
        
        if prefer_emerald and card.name == "ICICI Emerald Private Metal" and rate >= best_rate * 0.9:
            best_card = card
            best_rate = rate
            best_reason = reason + " [Fee waiver]"
        elif rate > best_rate:
            best_card = card
            best_rate = rate
            best_reason = reason
    
    return best_card, best_rate, best_reason


# Bot command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    keyboard = [
        [InlineKeyboardButton("💳 Get Card Suggestion", callback_data='suggest')],
        [InlineKeyboardButton("📊 Monthly Summary", callback_data='summary')],
        [InlineKeyboardButton("📝 View Expenses", callback_data='expenses')],
        [InlineKeyboardButton("🎫 Voucher Limits", callback_data='limits')],
        [InlineKeyboardButton("❓ Help", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "👋 *Welcome to Credit Card Optimizer Bot!*\n\n"
        "I'll help you choose the best credit card for each expense "
        "and track your spending to maximize rewards.\n\n"
        "What would you like to do?"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'suggest':
        await start_suggestion(update, context)
    elif query.data == 'summary':
        await show_summary(update, context)
    elif query.data == 'expenses':
        await show_expenses(update, context)
    elif query.data == 'limits':
        await show_limits(update, context)
    elif query.data == 'help':
        await show_help(update, context)
    elif query.data.startswith('cat_'):
        await handle_category_selection(update, context)
    elif query.data in ['voucher_yes', 'voucher_no', 'emerald_yes', 'emerald_no']:
        await handle_option_selection(update, context)
    elif query.data in ['save_yes', 'save_no']:
        await handle_save_decision(update, context)


async def start_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the card suggestion flow"""
    keyboard = [
        [InlineKeyboardButton("🍽️ Dining", callback_data='cat_Dining')],
        [InlineKeyboardButton("🛵 Food Delivery", callback_data='cat_Food Delivery')],
        [InlineKeyboardButton("🛒 Grocery", callback_data='cat_Grocery')],
        [InlineKeyboardButton("⛽ Fuel", callback_data='cat_Fuel')],
        [InlineKeyboardButton("🛍️ Online Shopping", callback_data='cat_Online Shopping')],
        [InlineKeyboardButton("💡 Utilities", callback_data='cat_Utilities')],
        [InlineKeyboardButton("✈️ Travel", callback_data='cat_Travel')],
        [InlineKeyboardButton("🎫 Amazon Pay Voucher", callback_data='cat_Amazon Pay Voucher')],
        [InlineKeyboardButton("🎫 Flipkart Voucher", callback_data='cat_Flipkart Voucher')],
        [InlineKeyboardButton("📱 Other", callback_data='cat_Other')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "Select expense category:"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)
    
    return CATEGORY


async def handle_category_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle category selection"""
    query = update.callback_query
    category = query.data.replace('cat_', '')
    context.user_data['category'] = category
    
    await query.edit_message_text(
        f"Category: *{category}*\n\nEnter the amount in ₹:",
        parse_mode='Markdown'
    )
    
    return AMOUNT


async def handle_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle amount input"""
    try:
        amount = float(update.message.text.strip())
        context.user_data['amount'] = amount
        
        category = context.user_data['category']
        
        # Check if voucher question is needed
        if any(keyword in category.lower() for keyword in ['voucher', 'utilities']):
            keyboard = [
                [InlineKeyboardButton("Yes", callback_data='voucher_yes')],
                [InlineKeyboardButton("No", callback_data='voucher_no')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "Will you buy this via voucher purchase?",
                reply_markup=reply_markup
            )
            return VOUCHER
        else:
            # Skip to emerald preference
            context.user_data['via_voucher'] = None
            return await ask_emerald_preference(update, context)
    
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please enter a number:")
        return AMOUNT


async def handle_option_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voucher/emerald option selection"""
    query = update.callback_query
    
    if query.data == 'voucher_yes':
        await query.edit_message_text("Which voucher? (e.g., Amazon Pay, Flipkart):")
        return VOUCHER
    elif query.data == 'voucher_no':
        context.user_data['via_voucher'] = None
        return await ask_emerald_preference(update, context)
    elif query.data in ['emerald_yes', 'emerald_no']:
        prefer_emerald = query.data == 'emerald_yes'
        return await show_recommendation(update, context, prefer_emerald)


async def handle_voucher_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voucher name input"""
    context.user_data['via_voucher'] = update.message.text.strip()
    return await ask_emerald_preference(update, context)


async def ask_emerald_preference(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask about ICICI Emerald preference"""
    keyboard = [
        [InlineKeyboardButton("Yes (for fee waiver)", callback_data='emerald_yes')],
        [InlineKeyboardButton("No", callback_data='emerald_no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "Prefer ICICI Emerald to help reach annual fee waiver?"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)
    
    return SAVE_EXPENSE


async def show_recommendation(update: Update, context: ContextTypes.DEFAULT_TYPE, prefer_emerald: bool):
    """Show card recommendation"""
    query = update.callback_query
    user_id = query.from_user.id
    
    tracker = ExpenseTracker(user_id)
    category = context.user_data['category']
    amount = context.user_data['amount']
    via_voucher = context.user_data.get('via_voucher')
    
    card, rate, reason = find_best_card_with_limits(category, amount, via_voucher, tracker, prefer_emerald)
    
    if not card or rate == 0:
        await query.edit_message_text("❌ No suitable card found or limits exceeded!")
        return ConversationHandler.END
    
    reward_value, reward_type = card.calculate_rewards(amount, rate)
    
    # Store recommendation for saving
    context.user_data['recommended_card'] = card.name
    
    text = (
        f"💳 *RECOMMENDED CARD*\n\n"
        f"Card: *{card.name}*\n"
        f"Reward Rate: *{rate:.2f}%*\n"
        f"Reason: {reason}\n\n"
        f"You'll earn: *{reward_value:.0f} {reward_type}*\n"
        f"On spend: ₹{amount:,}\n\n"
        f"Current month spend on this card: ₹{tracker.get_card_spend(card.name):,}"
    )
    
    if card.name == "ICICI Emerald Private Metal":
        annual_spend = tracker.get_annual_card_spend(card.name)
        progress = (annual_spend / card.fee_waiver_spend) * 100
        text += f"\n\n🎯 Annual spend: ₹{annual_spend:,} ({progress:.1f}% toward fee waiver)"
    
    keyboard = [
        [InlineKeyboardButton("✅ Save Expense", callback_data='save_yes')],
        [InlineKeyboardButton("❌ Don't Save", callback_data='save_no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    return SAVE_EXPENSE


async def handle_save_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle save/don't save decision"""
    query = update.callback_query
    
    if query.data == 'save_yes':
        user_id = query.from_user.id
        tracker = ExpenseTracker(user_id)
        
        tracker.add_expense(
            context.user_data['category'],
            context.user_data['amount'],
            context.user_data['recommended_card'],
            context.user_data.get('via_voucher')
        )
        
        await query.edit_message_text("✅ Expense saved successfully!")
    else:
        await query.edit_message_text("Expense not saved.")
    
    # Clear user data
    context.user_data.clear()
    
    return ConversationHandler.END


async def show_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show monthly summary"""
    query = update.callback_query
    user_id = query.from_user.id
    
    tracker = ExpenseTracker(user_id)
    month_expenses = tracker.get_current_month_expenses()
    
    if not month_expenses:
        await query.edit_message_text("📭 No expenses recorded this month.")
        return
    
    total_spend = sum(e['amount'] for e in month_expenses)
    
    cards_summary = {}
    for card in CARDS:
        card_spend = tracker.get_card_spend(card.name)
        if card_spend > 0:
            cards_summary[card.name] = card_spend
    
    text = (
        f"📊 *MONTHLY SUMMARY*\n"
        f"_{datetime.now().strftime('%B %Y')}_\n\n"
        f"Total Expenses: {len(month_expenses)}\n"
        f"Total Spend: ₹{total_spend:,.0f}\n\n"
        f"*Card-wise Breakdown:*\n"
    )
    
    for card_name, spend in cards_summary.items():
        text += f"• {card_name}: ₹{spend:,.0f}\n"
    
    # ICICI Emerald tracking
    emerald_annual = tracker.get_annual_card_spend("ICICI Emerald Private Metal")
    if emerald_annual > 0:
        progress = (emerald_annual / 1000000) * 100
        text += f"\n🎯 *ICICI Emerald Fee Waiver:*\n"
        text += f"Annual: ₹{emerald_annual:,} ({progress:.1f}%)\n"
        if progress >= 100:
            text += "✓ Target achieved!"
        else:
            remaining = 1000000 - emerald_annual
            text += f"₹{remaining:,} more needed"
    
    await query.edit_message_text(text, parse_mode='Markdown')


async def show_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all expenses"""
    query = update.callback_query
    user_id = query.from_user.id
    
    tracker = ExpenseTracker(user_id)
    month_expenses = tracker.get_current_month_expenses()
    
    if not month_expenses:
        await query.edit_message_text("📭 No expenses recorded this month.")
        return
    
    text = f"📝 *ALL EXPENSES*\n_{datetime.now().strftime('%B %Y')}_\n\n"
    
    for i, exp in enumerate(month_expenses[-10:], 1):  # Show last 10
        voucher_info = f" (via {exp['via_voucher']})" if exp.get('via_voucher') else ""
        text += f"{i}. {exp['category']}{voucher_info}\n"
        text += f"   ₹{exp['amount']:,} • {exp['card']}\n"
        text += f"   _{exp['date']}_\n\n"
    
    if len(month_expenses) > 10:
        text += f"_(Showing last 10 of {len(month_expenses)} expenses)_"
    
    await query.edit_message_text(text, parse_mode='Markdown')


async def show_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show voucher limits"""
    query = update.callback_query
    user_id = query.from_user.id
    
    tracker = ExpenseTracker(user_id)
    
    text = f"🎫 *VOUCHER LIMITS*\n_{datetime.now().strftime('%B %Y')}_\n\n"
    
    for card in CARDS:
        if card.vouchers:
            text += f"*{card.name}:*\n"
            for voucher in card.vouchers:
                used = tracker.get_voucher_usage(card.name, voucher['name'])
                remaining = voucher['limit'] - used
                percentage = (used / voucher['limit']) * 100 if voucher['limit'] > 0 else 0
                text += f"• {voucher['name']}: ₹{used:,}/₹{voucher['limit']:,} ({percentage:.0f}%)\n"
            text += "\n"
    
    await query.edit_message_text(text, parse_mode='Markdown')


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message"""
    query = update.callback_query
    
    text = (
        "❓ *HOW TO USE*\n\n"
        "*💳 Get Card Suggestion:*\n"
        "Tell me your expense category and amount, "
        "and I'll recommend the best card.\n\n"
        "*📊 Monthly Summary:*\n"
        "View your total spending and card-wise breakdown.\n\n"
        "*📝 View Expenses:*\n"
        "See all your recorded expenses for the month.\n\n"
        "*🎫 Voucher Limits:*\n"
        "Check remaining voucher purchase limits.\n\n"
        "Use /start anytime to see the main menu."
    )
    
    await query.edit_message_text(text, parse_mode='Markdown')


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel conversation"""
    await update.message.reply_text("Operation cancelled. Use /start to begin again.")
    return ConversationHandler.END


def main():
    """Start the bot"""
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation handler for card suggestions
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern='^suggest$')],
        states={
            CATEGORY: [CallbackQueryHandler(handle_category_selection, pattern='^cat_')],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount)],
            VOUCHER: [
                CallbackQueryHandler(handle_option_selection, pattern='^voucher_'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_voucher_input)
            ],
            SAVE_EXPENSE: [CallbackQueryHandler(handle_option_selection)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Start bot
    print("🤖 Bot started! Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
