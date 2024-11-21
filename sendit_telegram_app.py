from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
import telebot
import os
import sqlite3
import logging
import random
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Telegram Bot Token and Flask App Configuration
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SENDIT_BOT = telebot.TeleBot(BOT_TOKEN)
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")

FLASK_PORT = 5001  # Using port 5001 for Flask Application

# Flask Application Setup
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Database setup
DATABASE = 'sendit.db'

def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_balances (
            username TEXT PRIMARY KEY,
            balance REAL NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_otps (
            username TEXT PRIMARY KEY,
            otp INTEGER NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

# Initialize the database
init_db()

# Functions to interact with database
def get_balance(username):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM user_balances WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    else:
        return None

def update_balance(username, amount):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    if get_balance(username) is None:
        cursor.execute("INSERT INTO user_balances (username, balance) VALUES (?, ?)", (username, amount))
    else:
        cursor.execute("UPDATE user_balances SET balance = ? WHERE username = ?", (amount, username))
    conn.commit()
    conn.close()

### Step 4.2: Set Up Telegram Bot Commands

@SENDIT_BOT.message_handler(commands=["start"])
def send_welcome(message):
    SENDIT_BOT.reply_to(
        message,
        "Welcome to SendIt! You can send money to other Telegram users using their username! Please verify your identity by using the /verify command."
    )

@SENDIT_BOT.message_handler(commands=["verify"])
def send_verification(message):
    user = message.from_user.username
    if user is None:
        SENDIT_BOT.reply_to(message, "You must have a Telegram username to use this service.")
        return
    otp = random.randint(100000, 999999)
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("REPLACE INTO user_otps (username, otp) VALUES (?, ?)", (user, otp))
    conn.commit()
    conn.close()
    SENDIT_BOT.reply_to(message, f"Your verification OTP is: {otp}. Please use /confirm <OTP> to verify.")

@SENDIT_BOT.message_handler(commands=["confirm"])
def confirm_verification(message):
    try:
        params = message.text.split()
        if len(params) != 2:
            SENDIT_BOT.reply_to(message, "Invalid format. Please use: /confirm <OTP>")
            return
        user = message.from_user.username
        otp = int(params[1])
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("SELECT otp FROM user_otps WHERE username = ?", (user,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0] == otp:
            SENDIT_BOT.reply_to(message, "Verification successful! You can now use SendIt services.")
        else:
            SENDIT_BOT.reply_to(message, "Invalid OTP. Please try again.")
    except ValueError:
        SENDIT_BOT.reply_to(message, "Invalid OTP format. Please enter a numeric OTP.")

### Step 4.3: Set Up Flask Routes for the Web Interface

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/balance", methods=["POST"])
def check_balance_web():
    username = request.form.get("username")
    if username:
        balance = get_balance(username)
        if balance is None:
            balance = 1000.0
            update_balance(username, balance)  # Initialize user balance
        flash(f"User @{username}'s current balance is {balance:.2f}", "info")
    else:
        flash("Username is required to check balance.", "error")
    return redirect(url_for("index"))

@app.route("/send_money", methods=["POST"])
def send_money_web():
    sender = request.form.get("sender")
    receiver = request.form.get("receiver")
    amount = request.form.get("amount")
    try:
        if not sender or not receiver or not amount:
            flash("All fields are required.", "error")
            return redirect(url_for("index"))
        amount = float(amount)
        sender_balance = get_balance(sender)
        if sender_balance is None:
            sender_balance = 1000.0
            update_balance(sender, sender_balance)  # Initialize sender balance

        if sender == receiver:
            flash("You cannot send money to yourself.", "error")
            return redirect(url_for("index"))

        if sender_balance < amount:
            flash("Insufficient funds to complete this transaction.", "error")
            return redirect(url_for("index"))

        receiver_balance = get_balance(receiver)
        if receiver_balance is None:
            receiver_balance = 0.0
            update_balance(receiver, receiver_balance)

        update_balance(sender, sender_balance - amount)
        update_balance(receiver, receiver_balance + amount)

        flash(f"Success! You sent {amount:.2f} to @{receiver}.", "success")
    except ValueError:
        flash("Invalid amount format.", "error")
    except Exception as e:
        logging.error(f"Error processing transaction: {str(e)}")
        flash(f"An error occurred: {str(e)}", "error")
    return redirect(url_for("index"))

# Define the /webhook route
@app.route('/webhook', methods=['POST'])
def webhook():
    json_string = request.get_data().decode('UTF-8')
    logging.info(f"Received webhook update: {json_string}")
    try:
        update = telebot.types.Update.de_json(json_string)
        logging.info("Processing update with telebot.")
        SENDIT_BOT.process_new_updates([update])
    except Exception as e:
        logging.error(f"Error processing update: {e}")
    return '!', 200
    
### Step 4.4: Main Application Entry Point

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=FLASK_PORT)
