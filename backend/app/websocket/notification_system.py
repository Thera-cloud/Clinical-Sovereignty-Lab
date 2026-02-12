"""
LITTLE NATE - Complete Notification System with SendGrid + Twilio SMS
Version: 2.1
Date: February 10, 2026

In-app notifications + SendGrid email + Twilio SMS integration.
"""

import json
import datetime
import secrets
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

# SendGrid import with fallback
try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Email, To, Content, Personalization
    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False
    print(">>> [NOTIFY] SendGrid not installed. Run: pip3 install sendgrid")

# Twilio import with fallback
try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    print(">>> [NOTIFY] Twilio not installed. Run: pip3 install twilio")


class NotificationSystem:
    """Complete notification system with in-app and email support."""
    
    # Email templates
    TEMPLATES = {
        "welcome": {
            "subject": "Welcome to Little Nate - Your AI Therapy Companion",
            "template_id": None,  # Can use SendGrid template IDs
        },
        "session_reminder": {
            "subject": "Reminder: Your session starts in {time}",
            "template_id": None,
        },
        "coach_assigned": {
            "subject": "Good news! You've been assigned a coach",
            "template_id": None,
        },
        "crisis_alert": {
            "subject": "⚠️ URGENT: Crisis Alert for {client_name}",
            "template_id": None,
        },
        "password_reset": {
            "subject": "Reset your Little Nate password",
            "template_id": None,
        },
        "subscription_confirmed": {
            "subject": "Your {plan} subscription is now active",
            "template_id": None,
        },
        "payment_failed": {
            "subject": "Action required: Payment failed for your subscription",
            "template_id": None,
        },
        "trial_ending": {
            "subject": "Your free trial ends in {days} days",
            "template_id": None,
        },
    }
    
    def __init__(self, data_dir, sendgrid_key=None):
        self.data_dir = Path(data_dir)
        self.notifications_file = self.data_dir / "notifications.json"
        self.email_log_file = self.data_dir / "email_log.json"
        self.sms_log_file = self.data_dir / "sms_log.json"
        self.sms_opt_out_file = self.data_dir / "sms_opt_out.json"
        self.active_connections: Dict[str, set] = {}
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize SendGrid
        self.sendgrid_enabled = False
        self.sendgrid_client = None
        self.from_email = os.getenv("SENDGRID_FROM_EMAIL") or os.getenv("FROM_EMAIL", "support@sovereignsanctuary.net")
        self.from_name = os.getenv("SENDGRID_FROM_NAME") or os.getenv("FROM_NAME", "Sovereign Sanctuary")
        
        if SENDGRID_AVAILABLE and sendgrid_key:
            try:
                self.sendgrid_client = SendGridAPIClient(sendgrid_key)
                self.sendgrid_enabled = True
                print(f">>> [NOTIFY] SendGrid initialized (from: {self.from_email})")
            except Exception as e:
                print(f">>> [NOTIFY] SendGrid init error: {e}")
        else:
            print(">>> [NOTIFY] SendGrid disabled - using in-app notifications only")
        
        # Initialize Twilio
        self.twilio_enabled = False
        self.twilio_client = None
        self.twilio_from_number = os.getenv("TWILIO_PHONE_NUMBER", "")
        
        twilio_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        twilio_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        
        if TWILIO_AVAILABLE and twilio_sid and twilio_token:
            try:
                self.twilio_client = TwilioClient(twilio_sid, twilio_token)
                self.twilio_enabled = True
                print(f">>> [NOTIFY] Twilio initialized (from: {self.twilio_from_number})")
            except Exception as e:
                print(f">>> [NOTIFY] Twilio init error: {e}")
        else:
            print(">>> [NOTIFY] Twilio disabled - SMS features unavailable")
    
    # =========================================================================
    # REAL-TIME WEBSOCKET CONNECTIONS
    # =========================================================================
    
    def register_connection(self, user_id: str, websocket):
        """Register WebSocket for real-time notifications."""
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)
    
    def unregister_connection(self, user_id: str, websocket):
        """Unregister WebSocket connection."""
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
    
    async def _push_to_websocket(self, user_id: str, notification: dict):
        """Push notification to connected WebSockets."""
        if user_id not in self.active_connections:
            return
        
        message = json.dumps({
            "type": "notification",
            "notification": notification
        })
        
        dead_sockets = set()
        for ws in self.active_connections[user_id]:
            try:
                await ws.send(message)
            except:
                dead_sockets.add(ws)
        
        # Cleanup dead connections
        for ws in dead_sockets:
            self.active_connections[user_id].discard(ws)
    
    # =========================================================================
    # IN-APP NOTIFICATIONS
    # =========================================================================
    
    def _load_notifications(self) -> List[dict]:
        if not self.notifications_file.exists():
            return []
        try:
            with open(self.notifications_file, 'r') as f:
                return json.load(f)
        except:
            return []
    
    def _save_notifications(self, notifications: List[dict]):
        with open(self.notifications_file, 'w') as f:
            json.dump(notifications[-2000:], f, indent=2, default=str)  # Keep last 2000
    
    async def send(self, recipient_id: str, notification_type: str, title: str, 
                   message: str, priority: str = "NORMAL", data: dict = None,
                   send_email: bool = False, email_address: str = None) -> dict:
        """
        Send an in-app notification and optionally an email.
        
        Args:
            recipient_id: User's hardware_id
            notification_type: Type of notification (info, success, warning, error, etc.)
            title: Notification title
            message: Notification message
            priority: LOW, NORMAL, HIGH, URGENT
            data: Additional data payload
            send_email: Whether to also send email
            email_address: Email address (if different from stored)
        """
        notification = {
            "id": secrets.token_hex(8),
            "recipient_id": recipient_id,
            "type": notification_type,
            "title": title,
            "message": message,
            "priority": priority,
            "data": data or {},
            "read": False,
            "created_at": datetime.datetime.now().isoformat()
        }
        
        # Save to storage
        notifications = self._load_notifications()
        notifications.append(notification)
        self._save_notifications(notifications)
        
        # Push to WebSocket if connected
        await self._push_to_websocket(recipient_id, notification)
        
        # Send email if requested
        if send_email and email_address:
            await self._send_email(
                to_email=email_address,
                subject=title,
                content=message,
                notification_type=notification_type
            )
        
        return notification
    
    def get_user_notifications(self, user_id: str, unread_only: bool = False, 
                                limit: int = 50) -> List[dict]:
        """Get notifications for a user."""
        notifications = self._load_notifications()
        user_notifs = [n for n in notifications if n.get("recipient_id") == user_id]
        
        if unread_only:
            user_notifs = [n for n in user_notifs if not n.get("read")]
        
        # Sort by date descending
        user_notifs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
        return user_notifs[:limit]
    
    def get_unread_count(self, user_id: str) -> int:
        """Get count of unread notifications."""
        notifications = self._load_notifications()
        return sum(1 for n in notifications 
                   if n.get("recipient_id") == user_id and not n.get("read"))
    
    def mark_read(self, notification_id: str) -> bool:
        """Mark a notification as read."""
        notifications = self._load_notifications()
        for n in notifications:
            if n.get("id") == notification_id:
                n["read"] = True
                n["read_at"] = datetime.datetime.now().isoformat()
                self._save_notifications(notifications)
                return True
        return False
    
    def mark_all_read(self, user_id: str) -> int:
        """Mark all notifications as read for a user."""
        notifications = self._load_notifications()
        count = 0
        for n in notifications:
            if n.get("recipient_id") == user_id and not n.get("read"):
                n["read"] = True
                n["read_at"] = datetime.datetime.now().isoformat()
                count += 1
        self._save_notifications(notifications)
        return count
    
    def delete_notification(self, notification_id: str) -> bool:
        """Delete a notification."""
        notifications = self._load_notifications()
        original_len = len(notifications)
        notifications = [n for n in notifications if n.get("id") != notification_id]
        if len(notifications) < original_len:
            self._save_notifications(notifications)
            return True
        return False
    
    # =========================================================================
    # EMAIL NOTIFICATIONS (SendGrid)
    # =========================================================================
    
    async def _send_email(self, to_email: str, subject: str, content: str,
                          notification_type: str = "general") -> bool:
        """Send email via SendGrid."""
        if not self.sendgrid_enabled:
            print(f">>> [NOTIFY] Email skipped (SendGrid disabled): {to_email}")
            self._log_email(to_email, subject, "skipped_disabled")
            return False
        
        try:
            message = Mail(
                from_email=Email(self.from_email, self.from_name),
                to_emails=To(to_email),
                subject=subject,
                html_content=self._format_email_html(content, notification_type)
            )
            
            response = self.sendgrid_client.send(message)
            
            success = response.status_code in [200, 201, 202]
            self._log_email(to_email, subject, "sent" if success else "failed", 
                           response.status_code)
            
            if success:
                print(f">>> [NOTIFY] Email sent to {to_email}")
            else:
                print(f">>> [NOTIFY] Email failed: {response.status_code}")
            
            return success
            
        except Exception as e:
            print(f">>> [NOTIFY] SendGrid error: {e}")
            self._log_email(to_email, subject, "error", str(e))
            return False
    
    def _format_email_html(self, content: str, notification_type: str) -> str:
        """Format email content as HTML."""
        # Color based on type
        colors = {
            "success": "#22c55e",
            "warning": "#f59e0b",
            "error": "#ef4444",
            "info": "#3b82f6",
            "crisis_alert": "#ef4444",
            "general": "#6366f1"
        }
        accent_color = colors.get(notification_type, colors["general"])
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                     background-color: #0f172a; color: #e2e8f0; padding: 20px; margin: 0;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #1e293b; 
                        border-radius: 12px; overflow: hidden; border: 1px solid #334155;">
                
                <!-- Header -->
                <div style="background: linear-gradient(135deg, {accent_color}, #1e293b); 
                            padding: 30px; text-align: center;">
                    <h1 style="margin: 0; color: #ffffff; font-size: 24px;">
                        🧠 Little Nate
                    </h1>
                    <p style="margin: 5px 0 0 0; color: #94a3b8; font-size: 14px;">
                        Your AI Therapy Companion
                    </p>
                </div>
                
                <!-- Content -->
                <div style="padding: 30px;">
                    <div style="color: #e2e8f0; font-size: 16px; line-height: 1.6;">
                        {content.replace(chr(10), '<br>')}
                    </div>
                </div>
                
                <!-- Footer -->
                <div style="background-color: #0f172a; padding: 20px; text-align: center; 
                            border-top: 1px solid #334155;">
                    <p style="margin: 0; color: #64748b; font-size: 12px;">
                        Clinical Sovereignty Lab • Sovereign Sanctuary
                    </p>
                    <p style="margin: 5px 0 0 0; color: #475569; font-size: 11px;">
                        This is an automated message. Please do not reply directly.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
    
    def _log_email(self, to_email: str, subject: str, status: str, 
                   details: Any = None):
        """Log email send attempt."""
        logs = []
        if self.email_log_file.exists():
            try:
                with open(self.email_log_file, 'r') as f:
                    logs = json.load(f)
            except:
                pass
        
        logs.append({
            "to": to_email,
            "subject": subject,
            "status": status,
            "details": details,
            "timestamp": datetime.datetime.now().isoformat()
        })
        
        with open(self.email_log_file, 'w') as f:
            json.dump(logs[-500:], f, indent=2)  # Keep last 500
    
    # =========================================================================
    # TEMPLATED EMAIL METHODS
    # =========================================================================
    
    async def send_welcome_email(self, to_email: str, name: str) -> bool:
        """Send welcome email to new user."""
        content = f"""
        <h2 style="color: #22d3ee; margin-bottom: 20px;">Welcome, {name}! 🎉</h2>
        
        <p>Thank you for joining Little Nate - your AI therapy companion.</p>
        
        <p>Here's what you can do:</p>
        <ul style="color: #94a3b8;">
            <li>Have unlimited conversations with Little Nate</li>
            <li>Track your emotional wellness over time</li>
            <li>Connect with professional coaches (optional)</li>
            <li>Add family members to your plan</li>
        </ul>
        
        <p>Your <strong>14-day free trial</strong> has started. Explore all features 
        and see how Little Nate can support your mental wellness journey.</p>
        
        <div style="text-align: center; margin: 30px 0;">
            <a href="https://app.sovereignsanctuary.ai" 
               style="background: linear-gradient(135deg, #22d3ee, #6366f1); 
                      color: white; padding: 12px 30px; border-radius: 8px; 
                      text-decoration: none; font-weight: bold;">
                Start Chatting with Nate
            </a>
        </div>
        
        <p style="color: #64748b; font-size: 14px;">
            If you have any questions, we're here to help.
        </p>
        """
        
        return await self._send_email(
            to_email=to_email,
            subject="Welcome to Little Nate - Your AI Therapy Companion 🧠",
            content=content,
            notification_type="success"
        )
    
    async def send_session_reminder(self, to_email: str, name: str, 
                                     coach_name: str, session_time: str,
                                     zoom_link: str = None) -> bool:
        """Send session reminder email."""
        content = f"""
        <h2 style="color: #22d3ee;">Session Reminder</h2>
        
        <p>Hi {name},</p>
        
        <p>This is a reminder that you have a session scheduled with 
        <strong>{coach_name}</strong> at:</p>
        
        <div style="background-color: #0f172a; padding: 20px; border-radius: 8px; 
                    text-align: center; margin: 20px 0;">
            <p style="font-size: 24px; color: #22d3ee; margin: 0;">{session_time}</p>
        </div>
        
        {"<p><a href='" + zoom_link + "' style='color: #22d3ee;'>Click here to join the session</a></p>" if zoom_link else ""}
        
        <p style="color: #94a3b8;">
            Please make sure you're in a quiet, private space for your session.
        </p>
        """
        
        return await self._send_email(
            to_email=to_email,
            subject=f"Reminder: Session with {coach_name} at {session_time}",
            content=content,
            notification_type="info"
        )
    
    async def send_coach_assigned_notification(self, to_email: str, name: str,
                                                coach_name: str, 
                                                specializations: List[str]) -> bool:
        """Send notification that a coach has been assigned."""
        specs = ", ".join(specializations) if specializations else "General wellness"
        
        content = f"""
        <h2 style="color: #22d3ee;">Great News! 🎉</h2>
        
        <p>Hi {name},</p>
        
        <p>You've been assigned a coach: <strong>{coach_name}</strong></p>
        
        <p><strong>Specializations:</strong> {specs}</p>
        
        <p>Your coach will be able to:</p>
        <ul style="color: #94a3b8;">
            <li>Review your progress with Little Nate</li>
            <li>Schedule live sessions with you</li>
            <li>Provide personalized guidance</li>
        </ul>
        
        <p>You can book your first session through the app.</p>
        """
        
        return await self._send_email(
            to_email=to_email,
            subject=f"You've been assigned a coach: {coach_name}",
            content=content,
            notification_type="success"
        )
    
    async def send_crisis_alert(self, admin_emails: List[str], client_name: str,
                                 client_id: str, trigger: str, 
                                 context: str) -> int:
        """Send crisis alert to admins. Returns number of emails sent."""
        content = f"""
        <h2 style="color: #ef4444;">⚠️ CRISIS ALERT</h2>
        
        <p><strong>Client:</strong> {client_name}</p>
        <p><strong>Client ID:</strong> {client_id}</p>
        <p><strong>Trigger:</strong> {trigger}</p>
        
        <div style="background-color: #450a0a; padding: 15px; border-radius: 8px; 
                    border-left: 4px solid #ef4444; margin: 20px 0;">
            <p style="color: #fca5a5; margin: 0;"><strong>Context:</strong></p>
            <p style="color: #fecaca; margin: 10px 0 0 0;">{context[:500]}...</p>
        </div>
        
        <p style="color: #f87171;">
            <strong>Please review this client's profile immediately.</strong>
        </p>
        
        <div style="text-align: center; margin: 20px 0;">
            <a href="https://app.sovereignsanctuary.ai/admin/crisis" 
               style="background-color: #ef4444; color: white; padding: 12px 30px; 
                      border-radius: 8px; text-decoration: none; font-weight: bold;">
                View Crisis Dashboard
            </a>
        </div>
        """
        
        sent_count = 0
        for email in admin_emails:
            success = await self._send_email(
                to_email=email,
                subject=f"⚠️ CRISIS ALERT: {client_name}",
                content=content,
                notification_type="crisis_alert"
            )
            if success:
                sent_count += 1
        
        return sent_count
    
    async def send_trial_ending_reminder(self, to_email: str, name: str, 
                                          days_remaining: int) -> bool:
        """Send trial ending reminder."""
        content = f"""
        <h2 style="color: #f59e0b;">Your Trial is Ending Soon</h2>
        
        <p>Hi {name},</p>
        
        <p>Your free trial of Little Nate will end in <strong>{days_remaining} days</strong>.</p>
        
        <p>To continue your mental wellness journey without interruption, 
        consider upgrading to one of our plans:</p>
        
        <table style="width: 100%; margin: 20px 0; border-collapse: collapse;">
            <tr>
                <td style="padding: 15px; background-color: #0f172a; border-radius: 8px; 
                           text-align: center; width: 33%;">
                    <p style="color: #22d3ee; font-size: 18px; margin: 0;">Standard</p>
                    <p style="color: #ffffff; font-size: 24px; margin: 10px 0;">$29/mo</p>
                    <p style="color: #64748b; font-size: 12px; margin: 0;">50,000 tokens</p>
                </td>
                <td style="padding: 15px; background: linear-gradient(135deg, #6366f1, #8b5cf6); 
                           border-radius: 8px; text-align: center; width: 33%;">
                    <p style="color: #ffffff; font-size: 18px; margin: 0;">Top Tier</p>
                    <p style="color: #ffffff; font-size: 24px; margin: 10px 0;">$199/mo</p>
                    <p style="color: #c4b5fd; font-size: 12px; margin: 0;">200K tokens + 4 coach sessions</p>
                </td>
                <td style="padding: 15px; background-color: #0f172a; border-radius: 8px; 
                           text-align: center; width: 33%;">
                    <p style="color: #22d3ee; font-size: 18px; margin: 0;">Family</p>
                    <p style="color: #ffffff; font-size: 24px; margin: 10px 0;">$299/mo</p>
                    <p style="color: #64748b; font-size: 12px; margin: 0;">300K tokens + 5 members</p>
                </td>
            </tr>
        </table>
        
        <div style="text-align: center; margin: 20px 0;">
            <a href="https://app.sovereignsanctuary.ai/billing" 
               style="background: linear-gradient(135deg, #22d3ee, #6366f1); 
                      color: white; padding: 12px 30px; border-radius: 8px; 
                      text-decoration: none; font-weight: bold;">
                Upgrade Now
            </a>
        </div>
        """
        
        return await self._send_email(
            to_email=to_email,
            subject=f"Your free trial ends in {days_remaining} days",
            content=content,
            notification_type="warning"
        )
    
    async def send_payment_failed_notification(self, to_email: str, 
                                                name: str) -> bool:
        """Send payment failed notification."""
        content = f"""
        <h2 style="color: #ef4444;">Payment Failed</h2>
        
        <p>Hi {name},</p>
        
        <p>We were unable to process your payment for your Little Nate subscription.</p>
        
        <p>Please update your payment method to continue enjoying uninterrupted service.</p>
        
        <div style="text-align: center; margin: 30px 0;">
            <a href="https://app.sovereignsanctuary.ai/billing" 
               style="background-color: #ef4444; color: white; padding: 12px 30px; 
                      border-radius: 8px; text-decoration: none; font-weight: bold;">
                Update Payment Method
            </a>
        </div>
        
        <p style="color: #94a3b8; font-size: 14px;">
            If you believe this is an error, please contact support.
        </p>
        """
        
        return await self._send_email(
            to_email=to_email,
            subject="Action Required: Payment Failed",
            content=content,
            notification_type="error"
        )
    
    async def send_subscription_confirmed(self, to_email: str, name: str,
                                           plan: str, tokens: int) -> bool:
        """Send subscription confirmation email."""
        content = f"""
        <h2 style="color: #22c55e;">Subscription Confirmed! ✅</h2>
        
        <p>Hi {name},</p>
        
        <p>Your <strong>{plan}</strong> subscription is now active!</p>
        
        <div style="background-color: #0f172a; padding: 20px; border-radius: 8px; 
                    margin: 20px 0;">
            <p style="color: #94a3b8; margin: 0 0 10px 0;">Your monthly tokens:</p>
            <p style="color: #22d3ee; font-size: 32px; margin: 0;">
                {tokens:,}
            </p>
        </div>
        
        <p>Thank you for choosing Little Nate for your mental wellness journey. 
        We're honored to be part of your path to better mental health.</p>
        
        <div style="text-align: center; margin: 20px 0;">
            <a href="https://app.sovereignsanctuary.ai" 
               style="background: linear-gradient(135deg, #22c55e, #16a34a); 
                      color: white; padding: 12px 30px; border-radius: 8px; 
                      text-decoration: none; font-weight: bold;">
                Continue to App
            </a>
        </div>
        """
        
        return await self._send_email(
            to_email=to_email,
            subject=f"Your {plan} subscription is now active!",
            content=content,
            notification_type="success"
        )

    async def send_password_reset_email(self, to_email: str, reset_link: str, 
                                        username: str = "") -> bool:
        """Send password reset email with link."""
        content = f"""
        <h2 style="color: #22d3ee;">Password Reset Request</h2>
        
        <p>Hi{f' {username}' if username else ''},</p>
        
        <p>You requested a password reset for your Little Nate / Sovereign Sanctuary account.</p>
        
        <p>Click the link below to set a new password (valid for 1 hour):</p>
        
        <div style="text-align: center; margin: 30px 0;">
            <a href="{reset_link}" 
               style="background-color: #22d3ee; color: #0f172a; padding: 12px 30px; 
                      border-radius: 8px; text-decoration: none; font-weight: bold;">
                Reset Password
            </a>
        </div>
        
        <p style="color: #64748b; font-size: 12px;">If you did not request this, you can safely ignore this email.</p>
        """
        return await self._send_email(
            to_email=to_email,
            subject="Reset your Little Nate password",
            content=content,
            notification_type="info"
        )

    async def send_forgot_username_email(self, to_email: str, username: str) -> bool:
        """Send forgot username email with the username."""
        content = f"""
        <h2 style="color: #22d3ee;">Your Username</h2>
        
        <p>You requested a reminder of your Sovereign Sanctuary username.</p>
        
        <div style="background-color: #0f172a; padding: 20px; border-radius: 8px; 
                    text-align: center; margin: 20px 0;">
            <p style="color: #94a3b8; margin: 0 0 10px 0;">Your username:</p>
            <p style="color: #22d3ee; font-size: 24px; font-weight: bold; margin: 0;">
                {username}
            </p>
        </div>
        
        <p>You can use this username to log in at the app.</p>
        """
        return await self._send_email(
            to_email=to_email,
            subject="Your Sovereign Sanctuary username",
            content=content,
            notification_type="info"
        )
    
    # =========================================================================
    # SMS NOTIFICATIONS (Twilio)
    # =========================================================================
    
    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """Normalize phone to E.164 format for Twilio (+1XXXXXXXXXX for US numbers)."""
        import re
        digits = re.sub(r'[^\d]', '', phone)
        if len(digits) == 10:
            digits = '1' + digits  # Assume US
        if not digits.startswith('+'):
            digits = '+' + digits
        return digits

    # ----- SMS Opt-Out (A2P 10DLC STOP compliance) -----

    def _load_opt_outs(self) -> set:
        """Load the set of opted-out phone numbers."""
        if self.sms_opt_out_file.exists():
            try:
                with open(self.sms_opt_out_file, 'r') as f:
                    return set(json.load(f))
            except Exception:
                pass
        return set()

    def _save_opt_outs(self, numbers: set):
        with open(self.sms_opt_out_file, 'w') as f:
            json.dump(sorted(numbers), f, indent=2)

    def save_opt_out(self, phone: str):
        """Add a phone number to the opt-out list (STOP)."""
        phone = self._normalize_phone(phone)
        numbers = self._load_opt_outs()
        numbers.add(phone)
        self._save_opt_outs(numbers)
        print(f">>> [NOTIFY] Phone opted out: {phone}")

    def remove_opt_out(self, phone: str):
        """Remove a phone number from the opt-out list (START)."""
        phone = self._normalize_phone(phone)
        numbers = self._load_opt_outs()
        numbers.discard(phone)
        self._save_opt_outs(numbers)
        print(f">>> [NOTIFY] Phone re-subscribed: {phone}")

    def is_opted_out(self, phone: str) -> bool:
        """Check if a phone number has opted out of SMS."""
        phone = self._normalize_phone(phone)
        return phone in self._load_opt_outs()

    # ----- Core SMS send -----

    async def send_sms(self, to_phone: str, body: str) -> bool:
        """Send SMS via Twilio."""
        if not self.twilio_enabled:
            print(f">>> [NOTIFY] SMS skipped (Twilio disabled): {to_phone}")
            self._log_sms(to_phone, body[:50], "skipped_disabled")
            return False
        
        to_phone = self._normalize_phone(to_phone)

        # A2P 10DLC: block sends to opted-out numbers
        if self.is_opted_out(to_phone):
            print(f">>> [NOTIFY] SMS blocked (opted out): {to_phone}")
            self._log_sms(to_phone, body[:50], "blocked_opt_out")
            return False

        try:
            message = self.twilio_client.messages.create(
                body=body,
                from_=self.twilio_from_number,
                to=to_phone
            )
            
            success = message.sid is not None
            self._log_sms(to_phone, body[:50], "sent" if success else "failed",
                         message.sid)
            
            if success:
                print(f">>> [NOTIFY] SMS sent to {to_phone} (SID: {message.sid})")
            else:
                print(f">>> [NOTIFY] SMS failed to {to_phone}")
            
            return success
            
        except Exception as e:
            print(f">>> [NOTIFY] Twilio error: {e}")
            self._log_sms(to_phone, body[:50], "error", str(e))
            return False
    
    async def send_password_reset_sms(self, to_phone: str, code: str) -> bool:
        """Send password reset verification code via SMS."""
        body = (
            f"Your Sovereign Sanctuary password reset code is: {code}\n\n"
            f"Valid for 10 minutes. Do not share this code with anyone."
        )
        return await self.send_sms(to_phone, body)

    async def send_family_invitation(self, contact: str, inviter_name: str,
                                     token: str, invitee_name: str = "") -> bool:
        """Send family invite via Twilio (phone) or SendGrid (email).
        contact: email or phone number. Detected by presence of @.
        """
        contact = (contact or "").strip()
        if not contact:
            return False
        app_url = os.getenv("APP_BASE_URL", "https://app.sovereignsanctuary.net")
        invite_url = f"{app_url.rstrip('/')}/family-invite?code={token}"
        privacy_url = f"{app_url.rstrip('/')}/privacy.html"
        terms_url = f"{app_url.rstrip('/')}/terms.html"
        msg = (
            f"{inviter_name} has invited you to join their Family Circle on Sovereign Sanctuary. "
            f"Accept here: {invite_url}\n\n"
            f"Privacy: {privacy_url}\n"
            f"Terms: {terms_url}\n\n"
            f"Reply STOP to opt out of messages."
        )
        if "@" in contact:
            content = f"""
            <h2 style="color: #C9A962;">Family Invitation</h2>
            <p>Hi{f' {invitee_name}' if invitee_name else ''},</p>
            <p><strong>{inviter_name}</strong> has invited you to join their Family Circle in the Sovereign Sanctuary.</p>
            <p>As a family member, you'll have access to unlimited conversations with Nate AI, voice mode, full progress tracking, and private sessions.</p>
            <p style="text-align:center; margin: 24px 0;">
                <a href="{invite_url}" style="background:#C9A962;color:#050505;text-decoration:none;padding:12px 28px;font-weight:bold;letter-spacing:1px;">Accept Invitation</a>
            </p>
            <p style="font-size:12px;color:#9A9A9A;">
                By accepting, you agree to our <a href="{privacy_url}" style="color:#4ECDC4;">Privacy Policy</a>
                and <a href="{terms_url}" style="color:#4ECDC4;">Terms of Use</a>.
                This invitation expires in 7 days.
            </p>
            """
            return await self._send_email(
                to_email=contact,
                subject=f"{inviter_name} invited you to Sovereign Sanctuary",
                content=content,
                notification_type="info"
            )
        else:
            return await self.send_sms(contact, msg)

    async def send_coach_invite_client(self, contact: str, coach_name: str,
                                       invite_token: str, client_name: str = "",
                                       tier: str = "STANDARD") -> bool:
        """Send coach invite to client prospect via Twilio (phone) or SendGrid (email)."""
        contact = (contact or "").strip()
        if not contact:
            return False
        app_url = os.getenv("APP_BASE_URL", "https://app.sovereignsanctuary.net")
        signup_url = f"{app_url.rstrip('/')}/#/?invite={invite_token}"
        privacy_url = f"{app_url.rstrip('/')}/privacy.html"
        terms_url = f"{app_url.rstrip('/')}/terms.html"
        tier_display = tier.replace("_", " ").title()
        msg = (
            f"{coach_name} has invited you to Sovereign Sanctuary. "
            f"Sign up with invite code {invite_token}: {signup_url}\n\n"
            f"Privacy: {privacy_url}\n"
            f"Terms: {terms_url}\n\n"
            f"Reply STOP to opt out of messages."
        )
        if "@" in contact:
            content = f"""
            <h2 style="color: #C9A962;">Your Coach Invited You</h2>
            <p>Hi{f' {client_name}' if client_name else ''},</p>
            <p><strong>{coach_name}</strong> has invited you to join Sovereign Sanctuary and work with them.</p>
            <p>Sign up here using invite code: <strong>{invite_token}</strong></p>
            <p style="text-align:center; margin: 24px 0;">
                <a href="{signup_url}" style="background:#C9A962;color:#050505;text-decoration:none;padding:12px 28px;font-weight:bold;letter-spacing:1px;">Create Your Account</a>
            </p>
            <p>Plan: {tier_display}</p>
            <p style="font-size:12px;color:#9A9A9A;">
                By signing up, you agree to our <a href="{privacy_url}" style="color:#4ECDC4;">Privacy Policy</a>
                and <a href="{terms_url}" style="color:#4ECDC4;">Terms of Use</a>.
            </p>
            """
            return await self._send_email(
                to_email=contact,
                subject=f"{coach_name} invited you to Sovereign Sanctuary",
                content=content,
                notification_type="info"
            )
        else:
            return await self.send_sms(contact, msg)
    
    def _log_sms(self, to_phone: str, body_preview: str, status: str,
                 details: Any = None):
        """Log SMS send attempt."""
        logs = []
        if self.sms_log_file.exists():
            try:
                with open(self.sms_log_file, 'r') as f:
                    logs = json.load(f)
            except:
                pass
        
        logs.append({
            "to": to_phone,
            "body_preview": body_preview,
            "status": status,
            "details": details,
            "timestamp": datetime.datetime.now().isoformat()
        })
        
        with open(self.sms_log_file, 'w') as f:
            json.dump(logs[-500:], f, indent=2)  # Keep last 500
