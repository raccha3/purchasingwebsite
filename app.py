# Add this after your other imports
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Replace your mail configuration section with this:
# Mail configuration - Updated for better reliability
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.environ.get('MAIL_USERNAME', 'uwfsaepurchasing@gmail.com')
app.config["MAIL_PASSWORD"] = os.environ.get('MAIL_PASSWORD', 'your-app-password-here')
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get('MAIL_USERNAME', 'uwfsaepurchasing@gmail.com')

# Add this helper function for sending emails with timeout handling
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

# Updated update_status route with working email
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
