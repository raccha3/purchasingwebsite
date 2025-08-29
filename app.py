from flask import Flask, render_template, request, redirect, url_for, flash, session
import mysql.connector
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from functools import wraps
import os

# Flask app setup
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your_secret_key')

# Initialize Flask extensions
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# Mail configuration
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.environ.get('MAIL_USERNAME', 'uwfsaepurchasing@gmail.com')
app.config["MAIL_PASSWORD"] = os.environ.get('MAIL_PASSWORD', 'oxqt iiot hnlc olqy')
mail = Mail(app)

# Connect to your MySQL database
db = mysql.connector.connect(
    host=os.environ.get('DB_HOST', 'localhost'),
    user=os.environ.get('DB_USER', 'root'),
    password=os.environ.get('DB_PASSWORD', ''),
    database=os.environ.get('DB_NAME', 'ClubPurchasesDB')
)

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
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM Users WHERE UserID = %s", (user_id,))
    user_data = cursor.fetchone()
    cursor.close()
    if user_data:
        return User(
            user_data["UserID"], 
            user_data["Username"], 
            user_data["Email"], 
            user_data["Name"], 
            user_data["IsAdmin"]
        )
    return None

# Home route to display all purchases
@app.route("/")
@login_required
def index():
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM ClubPurchases WHERE UserID = %s ORDER BY NeededBy;", (current_user.id,))
    purchases = cursor.fetchall()
    cursor.close()
    return render_template("index.html", purchases=purchases)

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

    cursor = db.cursor(dictionary=True)

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

    cursor.close()

    return render_template(
        "admin_dashboard.html",
        purchases=purchases,
        reimbursements=reimbursements,
        purchase_filter=purchase_filter,
        reimbursement_filter=reimbursement_filter
    )

# Update purchase status (Admin Only)
@app.route("/update_status/<int:purchase_id>", methods=["POST"])
@admin_required
def update_status(purchase_id):
    new_status = request.form["status"]
    cursor = db.cursor(dictionary=True)

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
    try:
        cursor.execute("""
            UPDATE ClubPurchases SET Status = %s WHERE PurchaseID = %s
        """, (new_status, purchase_id))
        db.commit()

        # Send email if status is "Received"
        if new_status == "Received" and purchase["UserEmail"]:
            msg = Message(
                "Your Package Has Been Received!",
                sender=app.config["MAIL_USERNAME"],
                recipients=[purchase["UserEmail"]]
            )
            msg.body = f"Hi {purchase['UserName']},\n\nYour package for '{purchase['Description']}' has been received."
            mail.send(msg)
            flash(f"Notification email sent to {purchase['UserEmail']}!", "success")
    except Exception as e:
        db.rollback()
        flash(f"Failed to update status or send email: {str(e)}", "danger")
    finally:
        cursor.close()

    flash("Purchase status updated!", "success")
    return redirect("/admin")

# Update reimbursement status (Admin Only)
@app.route("/update_reimbursement_status/<int:reimbursement_id>", methods=["POST"])
@admin_required
def update_reimbursement_status(reimbursement_id):
    new_status = request.form["status"]
    cursor = db.cursor()
    cursor.execute(
        "UPDATE Reimbursements SET Status = %s WHERE ReimbursementID = %s",
        (new_status, reimbursement_id)
    )
    db.commit()
    flash("Reimbursement status updated!", "success")
    return redirect("/admin")

@app.route("/update_account/<int:purchase_id>", methods=["POST"])
@admin_required
def update_account(purchase_id):
    account_used = request.form["account_used"]
    cursor = db.cursor()
    try:
        cursor.execute(
            "UPDATE ClubPurchases SET TeamAccount = %s WHERE PurchaseID = %s",
            (account_used, purchase_id)
        )
        db.commit()
        flash("Account used updated for the purchase!", "success")
    except Exception as e:
        db.rollback()  # Rollback in case of error
        flash(f"Failed to update account: {str(e)}", "danger")
    finally:
        cursor.close()
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
        part_number = request.form.get("part_number")  # Optional
        request_date = request.form["request_date"]
        needed_by = request.form["needed_by"]
        subteam = request.form["subteam"]
        notes = request.form.get("notes")  # Optional

        # Default team_account value (if not being set in the form)
        team_account = None  # Or set a default string value like "Unassigned"

        cursor = db.cursor()
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
        cursor.close()
        flash("Purchase request submitted!", "success")
        return redirect("/")
    return render_template("add.html")

# Route to request reimbursement
@app.route("/request_reimbursement", methods=["GET", "POST"])
@login_required
def request_reimbursement():
    if request.method == "POST":
        amount = request.form["amount"]
        reason = request.form["reason"]
        paypal = request.form["paypal"]

        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO Reimbursements (UserID, Amount, Reason, PayPal, Status) VALUES (%s, %s, %s, %s, 'Submitted')",
            (current_user.id, amount, reason, paypal)
        )
        db.commit()
        cursor.close()
        flash("Reimbursement request submitted!", "success")
        return redirect("/")
    return render_template("request_reimbursement.html")

# # Route to send purchase notification email
# @app.route("/notify/<int:purchase_id>")
# @login_required
# def notify(purchase_id):
#     cursor = db.cursor(dictionary=True)
#     cursor.execute("SELECT * FROM ClubPurchases WHERE PurchaseID = %s AND UserID = %s", (purchase_id, current_user.id))
#     purchase = cursor.fetchone()
#     cursor.close()
#     if purchase:
#         msg = Message(
#             "Your Package Has Been Received!",
#             sender=app.config["MAIL_USERNAME"],
#             recipients=[current_user.email]
#         )
#         msg.body = f"Hi {current_user.name},\n\nYour package for '{purchase['Description']}' has been received."
#         try:
#             mail.send(msg)
#             flash("Notification email sent!", "success")
#         except Exception as e:
#             flash(f"Failed to send email: {str(e)}", "danger")
#     else:
#         flash("Purchase not found or not associated with your account.", "danger")
#     return redirect("/")

# # Route to send reimbursement notification email
# @app.route("/notify_reimbursement/<int:reimbursement_id>")
# @admin_required
# def notify_reimbursement(reimbursement_id):
#     cursor = db.cursor(dictionary=True)
#     cursor.execute("SELECT Reimbursements.*, Users.Email, Users.Name FROM Reimbursements LEFT JOIN Users ON Reimbursements.UserID = Users.UserID WHERE ReimbursementID = %s", (reimbursement_id,))
#     reimbursement = cursor.fetchone()
#     if reimbursement:
#         msg = Message(
#             "Reimbursement Request Update",
#             sender=app.config["MAIL_USERNAME"],
#             recipients=[reimbursement["Email"]]
#         )
#         msg.body = f"Hi {reimbursement['Name']},\n\nYour reimbursement request for '{reimbursement['Reason']}' has been updated to '{reimbursement['Status']}'."
#         mail.send(msg)
#         flash("Notification email sent to user!", "success")
#     else:
#         flash("Reimbursement not found.", "danger")
#     return redirect("/admin/reimbursements")

# Registration route
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = bcrypt.generate_password_hash(request.form["password"]).decode("utf-8")
        email = request.form["email"]
        name = request.form["name"]

        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO Users (Username, PasswordHash, Email, Name, IsAdmin) VALUES (%s, %s, %s, %s, FALSE)",
            (username, password, email, name)
        )
        db.commit()
        cursor.close()
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

# Login route
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM Users WHERE Username = %s", (username,))
        user_data = cursor.fetchone()
        cursor.close()

        if user_data and bcrypt.check_password_hash(user_data["PasswordHash"], password):
            user = User(user_data["UserID"], user_data["Username"], user_data["Email"], user_data["Name"], user_data["IsAdmin"])
            login_user(user)
            flash("Login successful!", "success")
            return redirect("/")
        flash("Invalid username or password.", "danger")
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
    cursor = db.cursor()
    
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
    cursor.close()
    return "Database tables created successfully!"

# Run the Flask app
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
