from flask import Flask, render_template, request, redirect, url_for, flash, session
import mysql.connector
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from functools import wraps
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Flask app setup - MUST BE FIRST
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key')

# Initialize Flask extensions
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# Mail configuration - NOW app is defined
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.environ.get('MAIL_USERNAME', 'uwfsaepurchasing@gmail.com')
app.config["MAIL_PASSWORD"] = os.environ.get('MAIL_PASSWORD', 'your-app-password-here')
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get('MAIL_USERNAME', 'uwfsaepurchasing@gmail.com')
mail = Mail(app)

# Database connection function
def get_db_connection():
    return mysql.connector.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASSWORD', ''),
        database=os.environ.get('DB_NAME', 'ClubPurchasesDB')
    )

# Email helper function with timeout handling
def send_email_safely(to_email, subject, body, sender_name="Club Purchases"):
    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = f"{sender_name} <{app.config['MAIL_USERNAME']}>"
        msg['To'] = to_email
        msg['Subject'] = subject
        
        # Add body
        msg.attach(MIMEText(body, 'plain'))
        
        # Setup server with timeout
        server = smtplib.SMTP(app.config["MAIL_SERVER"], app.config["MAIL_PORT"], timeout=10)
        server.starttls()
        server.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
        
        # Send email
        text = msg.as_string()
        server.sendmail(app.config["MAIL_USERNAME"], to_email, text)
        server.quit()
        
        return True, "Email sent successfully"
        
    except smtplib.SMTPAuthenticationError:
        return False, "Gmail authentication failed - check app password"
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {str(e)}"
    except Exception as e:
        return False, f"Email error: {str(e)}"

# User model for Flask-Login
class User(UserMixin):
    def __init__(self, id, username, email, name, is_admin):
        self.id = id
        self.username = username
        self.email = email
        self.name = name
        self.is_admin = is_admin

# Flask-Login user loader
@login_manager.user_loader
def load_user(user_id):
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM Users WHERE UserID = %s", (user_id,))
        user_data = cursor.fetchone()
        if user_data:
            return User(
                user_data["UserID"], 
                user_data["Username"], 
                user_data["Email"], 
                user_data["Name"], 
                user_data["IsAdmin"]
            )
        return None
    finally:
        cursor.close()
        db.close()

# Home route to display all purchases
@app.route("/")
@login_required
def index():
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM ClubPurchases WHERE UserID = %s ORDER BY NeededBy;", (current_user.id,))
        purchases = cursor.fetchall()
        return render_template("index.html", purchases=purchases)
    finally:
        cursor.close()
        db.close()

# Admin-only decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash("Admin access required!", "danger")
            return redirect("/")
        return f(*args, **kwargs)
    return decorated_function

@app.route("/admin")
@admin_required
def admin_dashboard():
    purchase_filter = request.args.get("purchase_filter", "Submitted")
    reimbursement_filter = request.args.get("reimbursement_filter", "Submitted")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:
        # Filtered purchases with User Full Name
        cursor.execute("""
            SELECT ClubPurchases.*, Users.Name AS UserName 
            FROM ClubPurchases 
            LEFT JOIN Users ON ClubPurchases.UserID = Users.UserID 
            WHERE ClubPurchases.Status = %s 
            ORDER BY ClubPurchases.NeededBy;
        """, (purchase_filter,))
        purchases = cursor.fetchall()

        # Filtered reimbursements with User Full Name
        cursor.execute("""
            SELECT Reimbursements.*, Users.Name AS UserName 
            FROM Reimbursements 
            LEFT JOIN Users ON Reimbursements.UserID = Users.UserID 
            WHERE Reimbursements.Status = %s 
            ORDER BY Reimbursements.RequestDate DESC;
        """, (reimbursement_filter,))
        reimbursements = cursor.fetchall()

        return render_template(
            "admin_dashboard.html",
            purchases=purchases,
            reimbursements=reimbursements,
            purchase_filter=purchase_filter,
            reimbursement_filter=reimbursement_filter
        )
    finally:
        cursor.close()
        db.close()

# Update purchase status (Admin Only) with working email
@app.route("/update_status/<int:purchase_id>", methods=["POST"])
@admin_required
def update_status(purchase_id):
    new_status = request.form["status"]
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:
        # Fetch purchase details
        cursor.execute("""
            SELECT ClubPurchases.*, Users.Name AS UserName, Users.Email AS UserEmail
            FROM ClubPurchases
            LEFT JOIN Users ON ClubPurchases.UserID = Users.UserID
            WHERE ClubPurchases.PurchaseID = %s
        """, (purchase_id,))
        purchase = cursor.fetchone()

        if not purchase:
            flash("Purchase not found.", "danger")
            return redirect("/admin")

        # Update the status in the database
        cursor.execute("""
            UPDATE ClubPurchases SET Status = %s WHERE PurchaseID = %s
        """, (new_status, purchase_id))
        db.commit()

        # Send email if status is "Received"
        if new_status == "Received" and purchase["UserEmail"]:
            subject = "Your Package Has Been Received!"
            body = f"""Hi {purchase['UserName']},

Your package for '{purchase['Description']}' has been received and is ready for pickup.

Purchase Details:
- Item: {purchase['Description']}
- Vendor: {purchase['Vendor']}
- Quantity: {purchase['Quantity']}

Please collect your item at your earliest convenience.

Best regards,
Club Purchases Team"""

            success, message = send_email_safely(purchase["UserEmail"], subject, body)
            if success:
                flash(f"Status updated and notification sent to {purchase['UserEmail']}!", "success")
            else:
                flash(f"Status updated, but email failed: {message}", "warning")
        else:
            flash("Purchase status updated!", "success")

    except Exception as e:
        db.rollback()
        flash(f"Failed to update status: {str(e)}", "danger")
    finally:
        cursor.close()
        db.close()

    return redirect("/admin")

# Update reimbursement status (Admin Only)
@app.route("/update_reimbursement_status/<int:reimbursement_id>", methods=["POST"])
@admin_required
def update_reimbursement_status(reimbursement_id):
    new_status = request.form["status"]
    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            "UPDATE Reimbursements SET Status = %s WHERE ReimbursementID = %s",
            (new_status, reimbursement_id)
        )
        db.commit()
        flash("Reimbursement status updated!", "success")
    except Exception as e:
        db.rollback()
        flash(f"Failed to update reimbursement status: {str(e)}", "danger")
    finally:
        cursor.close()
        db.close()
    return redirect("/admin")

@app.route("/update_account/<int:purchase_id>", methods=["POST"])
@admin_required
def update_account(purchase_id):
    account_used = request.form["account_used"]
    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            "UPDATE ClubPurchases SET TeamAccount = %s WHERE PurchaseID = %s",
            (account_used, purchase_id)
        )
        db.commit()
        flash("Account used updated for the purchase!", "success")
    except Exception as e:
        db.rollback()
        flash(f"Failed to update account: {str(e)}", "danger")
    finally:
        cursor.close()
        db.close()
    return redirect("/admin")

# Route to add a new purchase
@app.route("/add", methods=["GET", "POST"])
@login_required
def add_purchase():
    if request.method == "POST":
        description = request.form["description"]
        quantity = request.form["quantity"]
        unit_price = request.form["unit_price"]
        subtotal = float(quantity) * float(unit_price)
        vendor = request.form["vendor"]
        link = request.form["link"]
        part_number = request.form.get("part_number")
        request_date = request.form["request_date"]
        needed_by = request.form["needed_by"]
        subteam = request.form["subteam"]
        notes = request.form.get("notes")
        team_account = None

        db = get_db_connection()
        cursor = db.cursor()
        try:
            cursor.execute(
                """INSERT INTO ClubPurchases 
                (UserID, Description, Quantity, UnitPrice, Subtotal, Vendor, Link, PartNumber, RequestDate, NeededBy, Subteam, Notes, TeamAccount, Status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Submitted')""",
                (
                    current_user.id, description, quantity, unit_price, subtotal, vendor,
                    link, part_number, request_date, needed_by, subteam, notes, team_account
                )
            )
            db.commit()
            flash("Purchase request submitted!", "success")
            return redirect("/")
        except Exception as e:
            db.rollback()
            flash(f"Failed to submit purchase request: {str(e)}", "danger")
        finally:
            cursor.close()
            db.close()
    return render_template("add.html")

# Route to request reimbursement
@app.route("/request_reimbursement", methods=["GET", "POST"])
@login_required
def request_reimbursement():
    if request.method == "POST":
        amount = request.form["amount"]
        reason = request.form["reason"]
        paypal = request.form["paypal"]

        db = get_db_connection()
        cursor = db.cursor()
        try:
            cursor.execute(
                "INSERT INTO Reimbursements (UserID, Amount, Reason, PayPal, Status) VALUES (%s, %s, %s, %s, 'Submitted')",
                (current_user.id, amount, reason, paypal)
            )
            db.commit()
            flash("Reimbursement request submitted!", "success")
            return redirect("/")
        except Exception as e:
            db.rollback()
            flash(f"Failed to submit reimbursement request: {str(e)}", "danger")
        finally:
            cursor.close()
            db.close()
    return render_template("request_reimbursement.html")

# Registration route
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = bcrypt.generate_password_hash(request.form["password"]).decode("utf-8")
        email = request.form["email"]
        name = request.form["name"]

        db = get_db_connection()
        cursor = db.cursor()
        try:
            cursor.execute(
                "INSERT INTO Users (Username, PasswordHash, Email, Name, IsAdmin) VALUES (%s, %s, %s, %s, FALSE)",
                (username, password, email, name)
            )
            db.commit()
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))
        except mysql.connector.IntegrityError:
            flash("Username or email already exists.", "danger")
        except Exception as e:
            db.rollback()
            flash(f"Registration failed: {str(e)}", "danger")
        finally:
            cursor.close()
            db.close()
    return render_template("register.html")

# Login route
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM Users WHERE Username = %s", (username,))
            user_data = cursor.fetchone()

            if user_data and bcrypt.check_password_hash(user_data["PasswordHash"], password):
                user = User(user_data["UserID"], user_data["Username"], user_data["Email"], user_data["Name"], user_data["IsAdmin"])
                login_user(user)
                flash("Login successful!", "success")
                return redirect("/")
            flash("Invalid username or password.", "danger")
        finally:
            cursor.close()
            db.close()
    return render_template("login.html")

# Logout route
@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))

@app.route("/setup_database")
def setup_database():
    db = get_db_connection()
    cursor = db.cursor()
    
    try:
        # Create Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Users (
                UserID INT AUTO_INCREMENT PRIMARY KEY,
                Username VARCHAR(50) UNIQUE NOT NULL,
                PasswordHash VARCHAR(255) NOT NULL,
                Email VARCHAR(100) UNIQUE NOT NULL,
                Name VARCHAR(100) NOT NULL,
                IsAdmin BOOLEAN DEFAULT FALSE,
                CreatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create ClubPurchases table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ClubPurchases (
                PurchaseID INT AUTO_INCREMENT PRIMARY KEY,
                UserID INT NOT NULL,
                Description TEXT NOT NULL,
                Quantity INT NOT NULL,
                UnitPrice DECIMAL(10, 2) NOT NULL,
                Subtotal DECIMAL(10, 2) NOT NULL,
                Vendor VARCHAR(255) NOT NULL,
                Link TEXT,
                PartNumber VARCHAR(100),
                RequestDate DATE NOT NULL,
                NeededBy DATE NOT NULL,
                Subteam VARCHAR(100) NOT NULL,
                Notes TEXT,
                TeamAccount VARCHAR(100),
                Status ENUM('Submitted', 'Purchased', 'Hold', 'Denied', 'Received') DEFAULT 'Submitted',
                PurchaseDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (UserID) REFERENCES Users(UserID) ON DELETE CASCADE
            )
        """)
        
        # Create Reimbursements table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Reimbursements (
                ReimbursementID INT AUTO_INCREMENT PRIMARY KEY,
                UserID INT NOT NULL,
                Amount DECIMAL(10, 2) NOT NULL,
                Reason TEXT NOT NULL,
                PayPal VARCHAR(100) NOT NULL,
                Status ENUM('Submitted', 'Approved', 'Denied') DEFAULT 'Submitted',
                RequestDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (UserID) REFERENCES Users(UserID) ON DELETE CASCADE
            )
        """)
        
        db.commit()
        return "Database tables created successfully!"
    finally:
        cursor.close()
        db.close()
        
@app.route("/test_email")
def test_email():
    success, message = send_email_safely("your-email@example.com", "Test Subject", "Test body")
    return f"Email test result: {success}, Message: {message}"
    
# Run the Flask app
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
