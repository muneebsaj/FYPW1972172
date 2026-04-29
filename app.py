import sqlite3
import os
import re
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'fixmate_secret_2025')

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixmate.db')

# Constants

SUPPORTED_BRANDS = ['windows', 'hp', 'lenovo', 'asus', 'dell']

OFF_TOPIC_KEYWORDS = [
    'weather', 'football', 'soccer', 'basketball', 'cricket', 'sport', 'sports',
    'recipe', 'cook', 'cooking', 'food', 'restaurant', 'eat',
    'movie', 'film', 'music', 'song', 'artist', 'netflix',
    'love', 'relationship', 'dating',
    'news', 'politics', 'government',
    'joke', 'funny', 'meme',
    'homework', 'essay', 'math', 'history'
]

VAGUE_WORDS = ['help', 'broken', 'problem', 'issue', 'fix', 'error', 'bad', 'wrong', 'weird', 'strange']

BRAND_SUPPORT_LINKS = {
    'hp': 'https://support.hp.com',
    'dell': 'https://www.dell.com/support/home',
    'lenovo': 'https://support.lenovo.com',
    'asus': 'https://www.asus.com/support',
    'windows': 'https://support.microsoft.com'
}

# Database setup

# Create the logs table if it doesn't already exist
def init_logs_table():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS unresolved_logs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            code_attempted TEXT NOT NULL,
            brand          TEXT,
            timestamp      TEXT NOT NULL
        )
    ''')
    # Add brand column if upgrading from an older database that doesn't have it
    try:
        cursor.execute('ALTER TABLE unresolved_logs ADD COLUMN brand TEXT')
    except:
        pass
    conn.commit()
    conn.close()

init_logs_table()

# Database helpers

def query_db(code):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM error_codes WHERE code = ?', (code,))
    row = cursor.fetchone()
    conn.close()
    return row

def query_db_by_brand(code, brand):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT * FROM error_codes WHERE code = ? AND LOWER(brand) = LOWER(?)',
        (code, brand)
    )
    row = cursor.fetchone()
    conn.close()
    return row

def log_unresolved(code, brand):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Only log if this code hasn't been logged before
    cursor.execute('SELECT id FROM unresolved_logs WHERE code_attempted = ?', (code,))
    if cursor.fetchone() is None:
        cursor.execute(
            "INSERT INTO unresolved_logs (code_attempted, brand, timestamp) VALUES (?, ?, datetime('now', 'localtime'))",
            (code, brand)
        )
        conn.commit()
    conn.close()

# Detection helpers

def is_off_topic(msg):
    return any(re.search(r'\b' + word + r'\b', msg) for word in OFF_TOPIC_KEYWORDS)

def is_vague(msg):
    return len(msg) < 4 or msg in VAGUE_WORDS

# Routes

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    message = data.get('message', '')
    response = get_response(message)
    return jsonify({'response': response})

@app.route('/reset', methods=['POST'])
def reset():
    session.clear()
    return jsonify({'status': 'ok'})


# Chatbot logic

def get_response(message):
    msg = message.lower().strip()

    # Check for reset command
    if 'start over' in msg or 'restart' in msg or 'reset' in msg:
        session.clear()
        return ("Conversation reset. Let's start again!\n\n"
                "What brand is your laptop?\n\nWindows, HP, Lenovo, ASUS or Dell")

    # If waiting for brand
    if session.get('step') == 'awaiting_brand':
        for brand in SUPPORTED_BRANDS:
            if brand in msg:
                session['brand'] = brand
                session['step'] = 'awaiting_code'
                return ("Got it - " + brand.upper() + " laptop.\n\n"
                        "Now please enter the error code shown on your screen.\n\n"
                        "Tip: error codes usually appear on a blue/black screen during startup, "
                        "or in an error pop-up. Write down the code exactly as it appears.")
        return ("I didn't recognise that brand. Please type one of:\n\n"
                "Windows, HP, Lenovo, ASUS or Dell")

    # If waiting for error code
    if session.get('step') == 'awaiting_code':
        brand = session.get('brand')

        row = query_db_by_brand(msg, brand)
        if not row:
            row = query_db(msg)

        if row:
            session.clear()
            return (row[3] + " Error - " + row[2]
                    + "\n\nStep-by-step fix:\n" + row[4])

        log_unresolved(msg, brand)
        link = BRAND_SUPPORT_LINKS.get(brand, '')
        external = ('\n\nYou can also search directly on the manufacturer\'s support site:\n'
                    + brand.upper() + ' Support: ' + link) if link else ''
        return ("I couldn't find error code '" + msg + "' in my database.\n\n"
                "This has been logged so the admin can review and add it.\n\n"
                "Please check the code and try again, or type 'start over' to begin again.\n\n"
                "Tip: make sure you copy the code exactly as it appears on screen."
                + external)

    # Off-topic check
    if is_off_topic(msg):
        return ("I'm only able to help with laptop problems!\n\n"
                "Try asking about:\n"
                "- An error code on your screen\n"
                "- A laptop issue like slow performance or WiFi problems\n"
                "- Your laptop brand (HP, Dell, Lenovo, ASUS or Windows)")

    # Brand mentioned - checked before vague check since brand names can be short (e.g. HP)
    for brand in SUPPORTED_BRANDS:
        if brand in msg:
            session['brand'] = brand
            session['step'] = 'awaiting_code'
            return ("Got it - " + brand.upper() + " laptop.\n\n"
                    "What error code are you seeing on your screen?\n\n"
                    "Tip: error codes appear on a blue/black screen during startup or in an error pop-up.")

    # Vague input check
    if is_vague(msg):
        return ("I need a bit more detail to help you.\n\n"
                "Could you tell me:\n"
                "- Your laptop brand (HP, Dell, Lenovo, ASUS or Windows)\n"
                "- Any error code shown on your screen\n"
                "- Or describe the issue e.g. 'my laptop is slow' or 'no WiFi'\n\n"
                "Tip: your laptop brand and model number are on the sticker on the bottom of your laptop.")

    # Try direct code lookup
    row = query_db(msg)
    if row:
        return (row[3] + " Error - " + row[2]
                + "\n\nStep-by-step fix:\n" + row[4])

    # Keyword responses

    if 'slow' in msg:
        return ("Slow laptop - here is what to do:\n\n"
                "1. Restart your laptop fully (not sleep) to clear temporary files\n"
                "2. Press Ctrl+Shift+Esc to open Task Manager. Click the CPU or Memory column to sort by usage and identify what is using the most resources\n"
                "3. Disable startup programs: in Task Manager, click the Startup tab, right-click any program you don't need on boot, and select Disable\n"
                "4. Run Disk Cleanup: press Windows key, type 'Disk Cleanup', select your C: drive, and delete temporary files")

    if 'wifi' in msg or 'internet' in msg:
        return ("WiFi issues - here is what to try:\n\n"
                "1. Restart your router: unplug the power cable, wait 30 seconds, then plug it back in and wait 60 seconds for it to reconnect\n"
                "2. Forget and reconnect: go to Settings > Network & Internet > WiFi > Manage known networks, click your network, select Forget, then reconnect and re-enter your password\n"
                "3. Update network drivers: go to Device Manager (right-click Start > Device Manager), expand Network Adapters, right-click your WiFi adapter, and select Update driver")

    if 'battery' in msg:
        return ("Battery draining fast - here is what to do:\n\n"
                "1. Lower screen brightness: press Windows key, go to Settings > System > Display and drag the brightness slider down\n"
                "2. Close background apps: press Ctrl+Shift+Esc, click the Processes tab, and End Task on anything you are not using\n"
                "3. Enable Battery Saver: go to Settings > System > Battery and turn on Battery saver")

    if 'display' in msg or 'screen' in msg:
        return ("Display problems - here is what to try:\n\n"
                "1. Update graphics drivers: right-click the Start button > Device Manager > Display adapters > right-click your GPU > Update driver\n"
                "2. Check display settings: right-click the desktop > Display settings and make sure the resolution is set to Recommended\n"
                "3. Test with an external monitor: plug an HDMI cable into your laptop and a TV or monitor. If the external display works, the issue is with your laptop screen, not the GPU")

    if 'keyboard' in msg:
        return ("Keyboard issues - here is what to try:\n\n"
                "1. Restart your laptop - this clears temporary driver faults\n"
                "2. Update keyboard drivers: open Device Manager (right-click Start), expand Keyboards, right-click your keyboard, and select Update driver\n"
                "3. Test with an external USB keyboard - if that works, the built-in keyboard hardware may be faulty")

    if 'sound' in msg or 'audio' in msg:
        return ("No sound - here is what to check:\n\n"
                "1. Check the volume: click the speaker icon in the bottom-right taskbar and make sure it is not muted and the volume is up\n"
                "2. Check the output device: right-click the speaker icon > Open Sound settings > Output, and make sure the correct device is selected\n"
                "3. Update audio drivers: open Device Manager > Sound, video and game controllers > right-click your audio device > Update driver")

    if 'overheat' in msg or 'hot' in msg:
        return ("Laptop overheating - here is what to do:\n\n"
                "1. Clean the vents: use a can of compressed air and blow short bursts into the vents on the bottom and sides of your laptop\n"
                "2. Always use your laptop on a hard, flat surface - using it on a bed or pillow blocks the vents underneath\n"
                "3. Listen for the fan: if you cannot hear the fan spinning when the laptop is hot, the fan may have failed and needs replacing by a technician")

    if 'touchpad' in msg or 'trackpad' in msg or 'mouse pad' in msg:
        return ("Touchpad not working - here is what to try:\n\n"
                "1. Check if it is disabled: press Fn + F7 (or the key with a touchpad icon) to toggle it on - the key varies by laptop brand\n"
                "2. Update touchpad drivers: open Device Manager (right-click Start), expand Mice and other pointing devices, right-click your touchpad, and select Update driver\n"
                "3. Restart your laptop - a temporary driver fault may be causing the issue\n"
                "4. If using a USB mouse, unplug it and test the touchpad alone - some laptops disable the touchpad when a mouse is connected")

    if 'charg' in msg or 'won\'t charge' in msg or 'not charging' in msg or 'plugged in' in msg:
        return ("Charging problems - here is what to check:\n\n"
                "1. Try a different wall socket - the socket itself may be faulty\n"
                "2. Check the charging cable and adapter for any visible damage, bends, or fraying\n"
                "3. Check the charging port on your laptop for dust or bent pins - use a torch to look inside and a toothpick to gently remove any debris\n"
                "4. Check the battery icon in the taskbar - if it shows 'Plugged in, not charging', go to Device Manager > Batteries, right-click Microsoft ACPI-Compliant Control Method Battery and select Uninstall device, then restart")

    if 'usb' in msg or 'port' in msg or 'not recognised' in msg or 'not recognized' in msg:
        return ("USB / port not working - here is what to try:\n\n"
                "1. Try a different USB port on your laptop - one port may have failed while others still work\n"
                "2. Try the device on another laptop to confirm whether the issue is with the USB device or the laptop port\n"
                "3. Update USB drivers: open Device Manager > Universal Serial Bus controllers, right-click each USB entry and select Update driver\n"
                "4. Restart your laptop - Windows sometimes loses track of USB devices after sleep")

    if 'freez' in msg or 'frozen' in msg or 'crash' in msg or 'not responding' in msg or 'hang' in msg:
        return ("Laptop freezing or crashing - here is what to do:\n\n"
                "1. If completely frozen, hold the power button for 10 seconds to force a shutdown, then restart\n"
                "2. Check for overheating: if the laptop is very hot when it freezes, clean the vents with compressed air\n"
                "3. Run Windows Memory Diagnostic: press Windows key, type 'Memory Diagnostic', open it and click 'Restart now and check for problems' - this tests your RAM\n"
                "4. Check for corrupted system files: open Command Prompt as Administrator and type 'sfc /scannow' then press Enter - this scans and repairs Windows files")

    if 'bluetooth' in msg:
        return ("Bluetooth not working - here is what to try:\n\n"
                "1. Make sure Bluetooth is turned on: go to Settings > Devices > Bluetooth & other devices and toggle it on\n"
                "2. Remove and re-pair the device: click the device in Settings > Bluetooth, select Remove device, then pair it again from scratch\n"
                "3. Update Bluetooth drivers: open Device Manager > Bluetooth, right-click your Bluetooth adapter and select Update driver\n"
                "4. Run the Bluetooth troubleshooter: go to Settings > Update & Security > Troubleshoot > Additional troubleshooters > Bluetooth")

    if 'storage' in msg or 'disk' in msg or 'disk full' in msg or 'no space' in msg or 'out of space' in msg:
        return ("Storage / disk space issues - here is what to do:\n\n"
                "1. Run Disk Cleanup: press Windows key, type 'Disk Cleanup', select your C: drive, tick all boxes and click OK to delete temporary files\n"
                "2. Check what is taking up space: go to Settings > System > Storage to see a breakdown by category\n"
                "3. Uninstall unused programs: go to Settings > Apps > Apps & features, sort by size, and uninstall anything you no longer use\n"
                "4. Move files to an external hard drive or USB to free up space on your main drive")

    # Error mentioned
    if 'error' in msg or 'code' in msg or 'not working' in msg or 'wont' in msg or "won't" in msg:
        session['step'] = 'awaiting_brand'
        return ("I can help with that!\n\n"
                "First, what brand is your laptop?\n\n"
                "Windows, HP, Lenovo, ASUS or Dell\n\n"
                "Tip: your laptop brand is on the sticker on the bottom of your laptop.")

    # Default
    session['step'] = 'awaiting_brand'
    return ("I'd like to help! To give you the most accurate solution, "
            "I need a couple of details.\n\n"
            "First, what brand is your laptop?\n\n"
            "Windows, HP, Lenovo, ASUS or Dell\n\n"
            "Tip: your laptop brand is on the sticker on the bottom of your laptop.\n\n"
            "Or visit your manufacturer's support site directly:\n"
            "- HP: https://support.hp.com\n"
            "- Dell: https://www.dell.com/support/home\n"
            "- Lenovo: https://support.lenovo.com\n"
            "- ASUS: https://www.asus.com/support\n"
            "- Windows: https://support.microsoft.com")

# Admin panel

ADMIN_PASSWORD = 'admin123'

@app.route('/admin')
def admin():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM error_codes')
    rows = cursor.fetchall()

    cursor.execute('SELECT id, code_attempted, brand, timestamp FROM unresolved_logs ORDER BY id DESC')
    logs = cursor.fetchall()

    conn.close()
    return render_template('admin.html', rows=rows, logs=logs, logged_in=True)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'GET':
        return render_template('admin.html', logged_in=False, error=None)

    password = request.form.get('password', '')
    if password == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        return redirect(url_for('admin'))
    else:
        return render_template('admin.html', logged_in=False, error='Incorrect password. Please try again.')

@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin/add', methods=['POST'])
def admin_add():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    code = request.form.get('code', '').strip()
    name = request.form.get('name', '').strip()
    brand = request.form.get('brand', '').strip()
    solution = request.form.get('solution', '').strip()

    if code and name and brand and solution:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO error_codes (code, name, brand, solution) VALUES (?, ?, ?, ?)',
            (code, name, brand, solution)
        )
        conn.commit()
        conn.close()

    return redirect(url_for('admin'))

@app.route('/admin/edit/<int:id>', methods=['GET', 'POST'])
def admin_edit(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if request.method == 'POST':
        code     = request.form.get('code', '').strip()
        name     = request.form.get('name', '').strip()
        brand    = request.form.get('brand', '').strip()
        solution = request.form.get('solution', '').strip()

        cursor.execute(
            'UPDATE error_codes SET code=?, name=?, brand=?, solution=? WHERE id=?',
            (code, name, brand, solution, id)
        )
        conn.commit()
        conn.close()
        return redirect(url_for('admin'))

    cursor.execute('SELECT * FROM error_codes WHERE id=?', (id,))
    row = cursor.fetchone()
    conn.close()
    return render_template('admin.html', logged_in=True, edit_row=row)

@app.route('/admin/delete/<int:id>', methods=['POST'])
def admin_delete(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM error_codes WHERE id=?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

@app.route('/admin/clear_log', methods=['POST'])
def admin_clear_log():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM unresolved_logs')
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

@app.route('/admin/delete_log/<int:id>', methods=['POST'])
def admin_delete_log(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM unresolved_logs WHERE id=?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

# Run app

if __name__ == '__main__':
    app.run(debug=True)
