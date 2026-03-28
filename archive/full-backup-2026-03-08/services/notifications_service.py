"""
LITTLE NATE — Email & Notification Service
Version: 1.0
Date: January 21, 2026

Email templates and notification logic for:
- Welcome / Onboarding
- Trial expiration reminders
- Payment notifications
- Family invitations
- Coaching session reminders
- Crisis alerts (internal)

Uses: SendGrid, Twilio (SMS), or generic SMTP
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum
import asyncio
from jinja2 import Environment, BaseLoader
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# =============================================================================
# CONFIGURATION
# =============================================================================

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.sendgrid.net")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "apikey")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")  # SendGrid API key
FROM_EMAIL = os.getenv("FROM_EMAIL", "sanctuary@littlenate.ai")
FROM_NAME = os.getenv("FROM_NAME", "Sovereign Sanctuary")

from app.config import settings as _app_settings
APP_URL = _app_settings.APP_URL

# =============================================================================
# EMAIL TEMPLATES
# =============================================================================

TEMPLATES = {
    # -------------------------------------------------------------------------
    # WELCOME
    # -------------------------------------------------------------------------
    "welcome": {
        "subject": "Welcome to the Sanctuary",
        "html": """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Georgia', serif; background: #050505; color: #F5F5F5; margin: 0; padding: 40px; }
        .container { max-width: 600px; margin: 0 auto; }
        .header { text-align: center; margin-bottom: 40px; }
        .logo { font-size: 32px; color: #C9A962; letter-spacing: 4px; }
        .content { background: #111111; border: 1px solid #1A1A1A; padding: 40px; border-radius: 4px; }
        h1 { font-weight: 300; font-size: 28px; color: #F5F5F5; margin-bottom: 20px; }
        p { color: #9A9A9A; line-height: 1.8; margin-bottom: 20px; }
        .cta { display: inline-block; background: #C9A962; color: #050505; text-decoration: none; padding: 14px 32px; font-size: 14px; letter-spacing: 1px; margin-top: 20px; }
        .footer { text-align: center; margin-top: 40px; color: #5A5A5A; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">SANCTUARY</div>
        </div>
        <div class="content">
            <h1>Welcome, {{ name }}.</h1>
            <p>You've taken the first step into a space designed for growth, reflection, and healing.</p>
            <p>Your 7-day trial begins now. During this time, you'll have access to Nate, your AI companion, who will be with you whenever you need support.</p>
            <p>There's no pressure here. Move at your own pace. Explore. Reflect. Begin.</p>
            <a href="{{ app_url }}" class="cta">Enter the Sanctuary</a>
        </div>
        <div class="footer">
            <p>Sovereign Sanctuary — A space for your journey</p>
        </div>
    </div>
</body>
</html>
"""
    },
    
    # -------------------------------------------------------------------------
    # TRIAL EXPIRING (Day 5)
    # -------------------------------------------------------------------------
    "trial_expiring_soon": {
        "subject": "Your trial journey continues...",
        "html": """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Georgia', serif; background: #050505; color: #F5F5F5; margin: 0; padding: 40px; }
        .container { max-width: 600px; margin: 0 auto; }
        .header { text-align: center; margin-bottom: 40px; }
        .logo { font-size: 32px; color: #C9A962; letter-spacing: 4px; }
        .content { background: #111111; border: 1px solid #1A1A1A; padding: 40px; border-radius: 4px; }
        h1 { font-weight: 300; font-size: 28px; color: #F5F5F5; margin-bottom: 20px; }
        p { color: #9A9A9A; line-height: 1.8; margin-bottom: 20px; }
        .stats { display: flex; justify-content: space-around; margin: 30px 0; }
        .stat { text-align: center; }
        .stat-value { font-size: 36px; color: #4ECDC4; }
        .stat-label { font-size: 11px; color: #5A5A5A; text-transform: uppercase; letter-spacing: 1px; }
        .cta { display: inline-block; background: #C9A962; color: #050505; text-decoration: none; padding: 14px 32px; font-size: 14px; letter-spacing: 1px; margin-top: 20px; }
        .secondary { color: #9A9A9A; text-decoration: underline; font-size: 13px; margin-top: 16px; display: inline-block; }
        .footer { text-align: center; margin-top: 40px; color: #5A5A5A; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">SANCTUARY</div>
        </div>
        <div class="content">
            <h1>{{ name }}, your trial ends in 2 days.</h1>
            <p>In just 5 days, you've already begun something meaningful:</p>
            <div class="stats">
                <div class="stat">
                    <div class="stat-value">{{ sessions }}</div>
                    <div class="stat-label">Sessions</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{{ coherence_change }}</div>
                    <div class="stat-label">Coherence</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{{ insights }}</div>
                    <div class="stat-label">Insights</div>
                </div>
            </div>
            <p>To continue your journey, choose a path that fits your needs. Your progress will remain yours, always.</p>
            <a href="{{ app_url }}/membership" class="cta">View Membership Options</a>
            <br>
            <a href="{{ app_url }}" class="secondary">Continue exploring (2 days left)</a>
        </div>
        <div class="footer">
            <p>Sovereign Sanctuary — Your data remains yours. Always.</p>
        </div>
    </div>
</body>
</html>
"""
    },
    
    # -------------------------------------------------------------------------
    # TRIAL EXPIRED
    # -------------------------------------------------------------------------
    "trial_expired": {
        "subject": "Your trial has ended — but your journey doesn't have to",
        "html": """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Georgia', serif; background: #050505; color: #F5F5F5; margin: 0; padding: 40px; }
        .container { max-width: 600px; margin: 0 auto; }
        .header { text-align: center; margin-bottom: 40px; }
        .logo { font-size: 32px; color: #C9A962; letter-spacing: 4px; }
        .content { background: #111111; border: 1px solid #1A1A1A; padding: 40px; border-radius: 4px; }
        h1 { font-weight: 300; font-size: 28px; color: #F5F5F5; margin-bottom: 20px; }
        p { color: #9A9A9A; line-height: 1.8; margin-bottom: 20px; }
        .plans { display: flex; gap: 16px; margin: 30px 0; }
        .plan { flex: 1; background: #161616; border: 1px solid #1A1A1A; padding: 24px; text-align: center; }
        .plan.featured { border-color: #8B7355; }
        .plan-name { font-size: 12px; color: #5A5A5A; text-transform: uppercase; letter-spacing: 1px; }
        .plan-price { font-size: 32px; color: #F5F5F5; margin: 8px 0; }
        .plan-period { font-size: 13px; color: #5A5A5A; }
        .cta { display: inline-block; background: #C9A962; color: #050505; text-decoration: none; padding: 14px 32px; font-size: 14px; letter-spacing: 1px; margin-top: 20px; }
        .note { font-size: 13px; color: #5A5A5A; margin-top: 24px; }
        .footer { text-align: center; margin-top: 40px; color: #5A5A5A; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">SANCTUARY</div>
        </div>
        <div class="content">
            <h1>{{ name }}, your trial has ended.</h1>
            <p>The door remains open. Your conversations, your progress, your insights — they're all waiting for you.</p>
            <div class="plans">
                <div class="plan">
                    <div class="plan-name">Standard</div>
                    <div class="plan-price">$49</div>
                    <div class="plan-period">/month</div>
                </div>
                <div class="plan featured">
                    <div class="plan-name">Sovereign Circle</div>
                    <div class="plan-price">$149</div>
                    <div class="plan-period">/month</div>
                </div>
            </div>
            <a href="{{ app_url }}/membership" class="cta">Continue Your Journey</a>
            <p class="note">You have a 3-day grace period. After that, your account will be paused (not deleted).</p>
        </div>
        <div class="footer">
            <p>Sovereign Sanctuary — We'll be here when you're ready.</p>
        </div>
    </div>
</body>
</html>
"""
    },

    # -------------------------------------------------------------------------
    # TRIAL PHASE 2 (Week 2 reduced access)
    # -------------------------------------------------------------------------
    "trial_phase2_reduced": {
        "subject": "Week 2 of your trial — reduced AI access",
        "html": """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Georgia', serif; background: #050505; color: #F5F5F5; margin: 0; padding: 40px; }
        .container { max-width: 600px; margin: 0 auto; }
        .header { text-align: center; margin-bottom: 40px; }
        .logo { font-size: 32px; color: #C9A962; letter-spacing: 4px; }
        .content { background: #111111; border: 1px solid #1A1A1A; padding: 40px; border-radius: 4px; }
        h1 { font-weight: 300; font-size: 28px; color: #F5F5F5; margin-bottom: 20px; }
        p { color: #9A9A9A; line-height: 1.8; margin-bottom: 20px; }
        .upgrade { background: rgba(201, 169, 98, 0.1); border-left: 3px solid #C9A962; padding: 16px; margin: 24px 0; }
        .upgrade p { color: #E8D5A3; margin: 0; }
        .cta { display: inline-block; background: #C9A962; color: #050505; text-decoration: none; padding: 14px 32px; font-size: 14px; letter-spacing: 1px; margin-top: 20px; }
        .footer { text-align: center; margin-top: 40px; color: #5A5A5A; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">SANCTUARY</div>
        </div>
        <div class="content">
            <h1>Hey {{ name }}, you're entering Week 2.</h1>
            <p>Your AI access is now limited to 30 minutes per day (down from full access in Week 1).</p>
            <div class="upgrade">
                <p>{{ coherence_prompt }}</p>
            </div>
            <a href="{{ app_url }}/membership" class="cta">Upgrade to Inner Chamber</a>
        </div>
        <div class="footer">
            <p>Sovereign Sanctuary — A space for your journey</p>
        </div>
    </div>
</body>
</html>
"""
    },

    # -------------------------------------------------------------------------
    # PAYMENT FAILED
    # -------------------------------------------------------------------------
    "payment_failed": {
        "subject": "Action needed: Payment unsuccessful",
        "html": """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Georgia', serif; background: #050505; color: #F5F5F5; margin: 0; padding: 40px; }
        .container { max-width: 600px; margin: 0 auto; }
        .header { text-align: center; margin-bottom: 40px; }
        .logo { font-size: 32px; color: #C9A962; letter-spacing: 4px; }
        .content { background: #111111; border: 1px solid #1A1A1A; padding: 40px; border-radius: 4px; }
        .alert { background: rgba(239, 68, 68, 0.1); border-left: 3px solid #EF4444; padding: 16px; margin-bottom: 24px; }
        .alert p { color: #F5F5F5; margin: 0; }
        h1 { font-weight: 300; font-size: 28px; color: #F5F5F5; margin-bottom: 20px; }
        p { color: #9A9A9A; line-height: 1.8; margin-bottom: 20px; }
        .cta { display: inline-block; background: #C9A962; color: #050505; text-decoration: none; padding: 14px 32px; font-size: 14px; letter-spacing: 1px; margin-top: 20px; }
        .footer { text-align: center; margin-top: 40px; color: #5A5A5A; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">SANCTUARY</div>
        </div>
        <div class="content">
            <div class="alert">
                <p>Your payment of ${{ amount }} on {{ date }} was unsuccessful.</p>
            </div>
            <h1>Let's resolve this together.</h1>
            <p>Your access continues for now, but please update your payment method to avoid any interruption to your journey.</p>
            <p>If you're experiencing financial difficulties, reach out — we may be able to help.</p>
            <a href="{{ app_url }}/settings/billing" class="cta">Update Payment Method</a>
        </div>
        <div class="footer">
            <p>Questions? Reply to this email or contact support@littlenate.ai</p>
        </div>
    </div>
</body>
</html>
"""
    },
    
    # -------------------------------------------------------------------------
    # FAMILY INVITATION
    # -------------------------------------------------------------------------
    "family_invitation": {
        "subject": "{{ inviter_name }} has invited you to join their Family Circle",
        "html": """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Georgia', serif; background: #050505; color: #F5F5F5; margin: 0; padding: 40px; }
        .container { max-width: 600px; margin: 0 auto; }
        .header { text-align: center; margin-bottom: 40px; }
        .logo { font-size: 32px; color: #C9A962; letter-spacing: 4px; }
        .content { background: #111111; border: 1px solid #1A1A1A; padding: 40px; border-radius: 4px; }
        h1 { font-weight: 300; font-size: 28px; color: #F5F5F5; margin-bottom: 20px; }
        p { color: #9A9A9A; line-height: 1.8; margin-bottom: 20px; }
        .highlight { color: #C9A962; }
        .features { background: #161616; padding: 24px; margin: 24px 0; }
        .features li { color: #9A9A9A; margin-bottom: 12px; }
        .cta { display: inline-block; background: #C9A962; color: #050505; text-decoration: none; padding: 14px 32px; font-size: 14px; letter-spacing: 1px; margin-top: 20px; }
        .footer { text-align: center; margin-top: 40px; color: #5A5A5A; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">SANCTUARY</div>
        </div>
        <div class="content">
            <h1>You've been invited.</h1>
            <p><span class="highlight">{{ inviter_name }}</span> wants you to join their Family Circle in the Sovereign Sanctuary.</p>
            <p>As a family member, you'll have access to:</p>
            <div class="features">
                <ul>
                    <li>Unlimited conversations with Nate AI</li>
                    <li>Voice mode</li>
                    <li>Full progress tracking</li>
                    <li>Private — your conversations remain yours alone</li>
                </ul>
            </div>
            <p>This invitation is at no cost to you.</p>
            <a href="{{ accept_url }}" class="cta">Accept Invitation</a>
        </div>
        <div class="footer">
            <p>This invitation expires in 7 days.</p>
        </div>
    </div>
</body>
</html>
"""
    },
    
    # -------------------------------------------------------------------------
    # COACHING SESSION CONFIRMATION
    # -------------------------------------------------------------------------
    "coaching_confirmation": {
        "subject": "Your coaching session is confirmed — {{ date }}",
        "html": """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Georgia', serif; background: #050505; color: #F5F5F5; margin: 0; padding: 40px; }
        .container { max-width: 600px; margin: 0 auto; }
        .header { text-align: center; margin-bottom: 40px; }
        .logo { font-size: 32px; color: #C9A962; letter-spacing: 4px; }
        .content { background: #111111; border: 1px solid #1A1A1A; padding: 40px; border-radius: 4px; }
        h1 { font-weight: 300; font-size: 28px; color: #F5F5F5; margin-bottom: 20px; }
        p { color: #9A9A9A; line-height: 1.8; margin-bottom: 20px; }
        .session-card { background: #161616; border: 1px solid #2D7A75; padding: 24px; margin: 24px 0; }
        .session-detail { display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid #1A1A1A; }
        .session-detail:last-child { border-bottom: none; }
        .session-detail .label { color: #5A5A5A; }
        .session-detail .value { color: #F5F5F5; }
        .coach { display: flex; align-items: center; gap: 16px; margin-top: 24px; }
        .coach-avatar { width: 48px; height: 48px; border-radius: 50%; background: #7C5DBF; display: flex; align-items: center; justify-content: center; color: white; font-size: 18px; }
        .coach-name { color: #F5F5F5; }
        .coach-title { color: #5A5A5A; font-size: 13px; }
        .note { background: rgba(201, 169, 98, 0.1); border-left: 3px solid #C9A962; padding: 16px; margin-top: 24px; }
        .note p { margin: 0; color: #C9A962; font-size: 14px; }
        .cta { display: inline-block; background: #4ECDC4; color: #050505; text-decoration: none; padding: 14px 32px; font-size: 14px; letter-spacing: 1px; margin-top: 20px; }
        .footer { text-align: center; margin-top: 40px; color: #5A5A5A; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">SANCTUARY</div>
        </div>
        <div class="content">
            <h1>Your session is confirmed.</h1>
            <div class="session-card">
                <div class="session-detail">
                    <span class="label">Date</span>
                    <span class="value">{{ date }}</span>
                </div>
                <div class="session-detail">
                    <span class="label">Time</span>
                    <span class="value">{{ time }} ({{ timezone }})</span>
                </div>
                <div class="session-detail">
                    <span class="label">Duration</span>
                    <span class="value">45 minutes</span>
                </div>
                <div class="coach">
                    <div class="coach-avatar">{{ coach_initials }}</div>
                    <div>
                        <div class="coach-name">{{ coach_name }}</div>
                        <div class="coach-title">{{ coach_credentials }}</div>
                    </div>
                </div>
            </div>
            <div class="note">
                <p>Nate will brief {{ coach_name }} before your session with relevant context from your journey. Your privacy settings determine what is shared.</p>
            </div>
            <a href="{{ join_url }}" class="cta">Add to Calendar</a>
        </div>
        <div class="footer">
            <p>Need to reschedule? You can do so up to 24 hours before the session.</p>
        </div>
    </div>
</body>
</html>
"""
    },
    
    # -------------------------------------------------------------------------
    # COACHING SESSION REMINDER (24h)
    # -------------------------------------------------------------------------
    "coaching_reminder": {
        "subject": "Reminder: Session with {{ coach_name }} tomorrow",
        "html": """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Georgia', serif; background: #050505; color: #F5F5F5; margin: 0; padding: 40px; }
        .container { max-width: 600px; margin: 0 auto; }
        .content { background: #111111; border: 1px solid #1A1A1A; padding: 40px; border-radius: 4px; }
        h1 { font-weight: 300; font-size: 24px; color: #F5F5F5; margin-bottom: 20px; }
        p { color: #9A9A9A; line-height: 1.8; margin-bottom: 20px; }
        .time-badge { display: inline-block; background: #4ECDC4; color: #050505; padding: 8px 16px; font-size: 14px; font-weight: 500; margin-bottom: 20px; }
        .cta { display: inline-block; background: #C9A962; color: #050505; text-decoration: none; padding: 14px 32px; font-size: 14px; letter-spacing: 1px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="content">
            <div class="time-badge">Tomorrow at {{ time }}</div>
            <h1>Your session with {{ coach_name }}</h1>
            <p>Take a moment to reflect on what you'd like to explore. There's no need to prepare anything specific — just bring yourself.</p>
            <a href="{{ app_url }}" class="cta">Open Sanctuary</a>
        </div>
    </div>
</body>
</html>
"""
    },

    # -------------------------------------------------------------------------
    # CLASSROOM: Session ready for assessment (coach/assistant)
    # -------------------------------------------------------------------------
    "classroom_ready_for_assessment": {
        "subject": "Session ready for assessment — open CLASSROOM and choose DOJOs",
        "html": """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Georgia', serif; background: #050505; color: #F5F5F5; margin: 0; padding: 40px; }
        .container { max-width: 600px; margin: 0 auto; }
        .logo { font-size: 32px; color: #C9A962; letter-spacing: 4px; text-align: center; margin-bottom: 40px; }
        .content { background: #111111; border: 1px solid #1A1A1A; padding: 40px; border-radius: 4px; }
        h1 { font-weight: 300; font-size: 28px; color: #F5F5F5; margin-bottom: 20px; }
        p { color: #9A9A9A; line-height: 1.8; margin-bottom: 20px; }
        .cta { display: inline-block; background: #C9A962; color: #050505; text-decoration: none; padding: 14px 32px; font-size: 14px; letter-spacing: 1px; margin-top: 20px; }
        .footer { text-align: center; margin-top: 40px; color: #5A5A5A; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">SANCTUARY</div>
        <div class="content">
            <h1>Session ready for assessment</h1>
            <p>A session with <strong>{{ client_name }}</strong> has been archived and analyzed. Open the CLASSROOM tab and choose which DOJOs to assess for this session.</p>
            <a href="{{ app_url }}" class="cta">Open CLASSROOM</a>
        </div>
        <div class="footer"><p>Sovereign Sanctuary — Coach Development</p></div>
    </div>
</body>
</html>
"""
    },
    # -------------------------------------------------------------------------
    # CLASSROOM: Analysis pending (master coach)
    # -------------------------------------------------------------------------
    "classroom_analysis_pending": {
        "subject": "Analysis pending — session ready for assessment",
        "html": """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Georgia', serif; background: #050505; color: #F5F5F5; margin: 0; padding: 40px; }
        .container { max-width: 600px; margin: 0 auto; }
        .logo { font-size: 32px; color: #C9A962; letter-spacing: 4px; text-align: center; margin-bottom: 40px; }
        .content { background: #111111; border: 1px solid #1A1A1A; padding: 40px; border-radius: 4px; }
        h1 { font-weight: 300; font-size: 28px; color: #F5F5F5; margin-bottom: 20px; }
        p { color: #9A9A9A; line-height: 1.8; margin-bottom: 20px; }
        .footer { text-align: center; margin-top: 40px; color: #5A5A5A; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">SANCTUARY</div>
        <div class="content">
            <h1>Analysis pending</h1>
            <p>A session with <strong>{{ client_name }}</strong> (coach: {{ coach_name }}) has been archived. The session is ready for assessment in CLASSROOM; you can complete DOJO selection if needed.</p>
        </div>
        <div class="footer"><p>Sovereign Sanctuary — Coach Development</p></div>
    </div>
</body>
</html>
"""
    },
    # -------------------------------------------------------------------------
    # CLASSROOM: Assessment ready in FOLDER
    # -------------------------------------------------------------------------
    "classroom_assessment_in_folder": {
        "subject": "Assessment ready for {{ client_name }} in FOLDER",
        "html": """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Georgia', serif; background: #050505; color: #F5F5F5; margin: 0; padding: 40px; }
        .container { max-width: 600px; margin: 0 auto; }
        .logo { font-size: 32px; color: #C9A962; letter-spacing: 4px; text-align: center; margin-bottom: 40px; }
        .content { background: #111111; border: 1px solid #1A1A1A; padding: 40px; border-radius: 4px; }
        h1 { font-weight: 300; font-size: 28px; color: #F5F5F5; margin-bottom: 20px; }
        p { color: #9A9A9A; line-height: 1.8; margin-bottom: 20px; }
        .cta { display: inline-block; background: #C9A962; color: #050505; text-decoration: none; padding: 14px 32px; font-size: 14px; letter-spacing: 1px; margin-top: 20px; }
        .footer { text-align: center; margin-top: 40px; color: #5A5A5A; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">SANCTUARY</div>
        <div class="content">
            <h1>Assessment ready</h1>
            <p>The PhD-level assessment for <strong>{{ client_name }}</strong> has been completed and filed in your FOLDER tab under this client.</p>
            <a href="{{ app_url }}" class="cta">View in FOLDER</a>
        </div>
        <div class="footer"><p>Sovereign Sanctuary — Coach Development</p></div>
    </div>
</body>
</html>
"""
    },
    # -------------------------------------------------------------------------
    # CLASSROOM: Client engaged with session takeaways
    # -------------------------------------------------------------------------
    "classroom_client_engaged": {
        "subject": "{{ client_name }} engaged with session takeaways",
        "html": """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Georgia', serif; background: #050505; color: #F5F5F5; margin: 0; padding: 40px; }
        .container { max-width: 600px; margin: 0 auto; }
        .logo { font-size: 32px; color: #C9A962; letter-spacing: 4px; text-align: center; margin-bottom: 40px; }
        .content { background: #111111; border: 1px solid #1A1A1A; padding: 40px; border-radius: 4px; }
        h1 { font-weight: 300; font-size: 28px; color: #F5F5F5; margin-bottom: 20px; }
        p { color: #9A9A9A; line-height: 1.8; margin-bottom: 20px; }
        .footer { text-align: center; margin-top: 40px; color: #5A5A5A; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">SANCTUARY</div>
        <div class="content">
            <h1>Client engaged</h1>
            <p><strong>{{ client_name }}</strong> chatted with Little Nate about their session. Little Nate is supporting your client between live sessions in line with your guidance.</p>
        </div>
        <div class="footer"><p>Sovereign Sanctuary — Coach Development</p></div>
    </div>
</body>
</html>
"""
    },
}


# =============================================================================
# EMAIL SERVICE
# =============================================================================

class EmailService:
    def __init__(self):
        self.jinja_env = Environment(loader=BaseLoader())
    
    def _render_template(self, template_name: str, context: Dict[str, Any]) -> tuple:
        """Render email template with context."""
        template = TEMPLATES.get(template_name)
        if not template:
            raise ValueError(f"Unknown template: {template_name}")
        
        # Add default context
        context.setdefault('app_url', APP_URL)
        
        subject = self.jinja_env.from_string(template['subject']).render(**context)
        html = self.jinja_env.from_string(template['html']).render(**context)
        
        return subject, html
    
    async def send_email(
        self,
        to_email: str,
        template_name: str,
        context: Dict[str, Any],
        from_email: str = FROM_EMAIL,
        from_name: str = FROM_NAME,
        transit_guardian=None,
    ) -> bool:
        """Send email using template. Optionally inspects for PII via Transit Guardian."""
        
        subject, html_content = self._render_template(template_name, context)

        # ── HIVE DEFENSE v4.3: Inspect outbound notification for PII ──
        # Email subjects and preview text are visible in lock-screen notifications,
        # so they must be scrubbed of PII before sending.
        if transit_guardian is not None:
            try:
                inspection = await transit_guardian.inspect_push_notification(
                    title=subject,
                    body=html_content[:500],
                    user_id=to_email,
                    destination="sendgrid",
                )
                if not inspection["safe"]:
                    subject = inspection["scrubbed_title"]
                    logger.warning(
                        "PII scrubbed from email subject to %s: %s",
                        to_email[:10], [p["type"] for p in inspection["pii_found"]],
                    )
            except Exception as _tg_err:
                logger.debug("Transit Guardian email inspection non-blocking: %s", _tg_err)
        
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = f"{from_name} <{from_email}>"
        message["To"] = to_email
        
        html_part = MIMEText(html_content, "html")
        message.attach(html_part)
        
        try:
            await aiosmtplib.send(
                message,
                hostname=SMTP_HOST,
                port=SMTP_PORT,
                username=SMTP_USER,
                password=SMTP_PASSWORD,
                use_tls=True
            )
            return True
        except Exception as e:
            print(f"Email send failed: {e}")
            return False
    
    # -------------------------------------------------------------------------
    # CONVENIENCE METHODS
    # -------------------------------------------------------------------------
    
    async def send_welcome(self, to_email: str, name: str) -> bool:
        return await self.send_email(to_email, "welcome", {"name": name})
    
    async def send_trial_expiring(
        self, to_email: str, name: str, 
        sessions: int, coherence_change: str, insights: int
    ) -> bool:
        return await self.send_email(to_email, "trial_expiring_soon", {
            "name": name,
            "sessions": sessions,
            "coherence_change": coherence_change,
            "insights": insights
        })
    
    async def send_trial_expired(self, to_email: str, name: str) -> bool:
        return await self.send_email(to_email, "trial_expired", {"name": name})

    async def send_trial_phase2_reduced_access(
        self, to_email: str, name: str, coherence_prompt: str
    ) -> bool:
        return await self.send_email(to_email, "trial_phase2_reduced", {
            "name": name,
            "coherence_prompt": coherence_prompt,
        })
    
    async def send_payment_failed(self, to_email: str, amount: str, date: str) -> bool:
        return await self.send_email(to_email, "payment_failed", {
            "amount": amount,
            "date": date
        })
    
    async def send_family_invitation(
        self, to_email: str, inviter_name: str, accept_url: str
    ) -> bool:
        return await self.send_email(to_email, "family_invitation", {
            "inviter_name": inviter_name,
            "accept_url": accept_url
        })
    
    async def send_coaching_confirmation(
        self, to_email: str,
        date: str, time: str, timezone: str,
        coach_name: str, coach_initials: str, coach_credentials: str,
        join_url: str
    ) -> bool:
        return await self.send_email(to_email, "coaching_confirmation", {
            "date": date,
            "time": time,
            "timezone": timezone,
            "coach_name": coach_name,
            "coach_initials": coach_initials,
            "coach_credentials": coach_credentials,
            "join_url": join_url
        })
    
    async def send_coaching_reminder(
        self, to_email: str, time: str, coach_name: str
    ) -> bool:
        return await self.send_email(to_email, "coaching_reminder", {
            "time": time,
            "coach_name": coach_name
        })

    async def send_classroom_ready_for_assessment(
        self, to_email: str, client_name: str
    ) -> bool:
        return await self.send_email(to_email, "classroom_ready_for_assessment", {
            "client_name": client_name or "your client",
            "app_url": APP_URL,
        })

    async def send_classroom_analysis_pending(
        self, to_email: str, client_name: str, coach_name: str
    ) -> bool:
        return await self.send_email(to_email, "classroom_analysis_pending", {
            "client_name": client_name or "client",
            "coach_name": coach_name or "assistant coach",
        })

    async def send_classroom_assessment_in_folder(
        self, to_email: str, client_name: str
    ) -> bool:
        return await self.send_email(to_email, "classroom_assessment_in_folder", {
            "client_name": client_name or "client",
            "app_url": APP_URL,
        })

    async def send_classroom_client_engaged(
        self, to_email: str, client_name: str
    ) -> bool:
        return await self.send_email(to_email, "classroom_client_engaged", {
            "client_name": client_name or "Your client",
        })


# =============================================================================
# NOTIFICATION SCHEDULER (Cron Jobs)
# =============================================================================

class NotificationScheduler:
    """Handles scheduled notifications like trial reminders."""
    
    def __init__(self, db_pool, email_service: EmailService):
        self.db = db_pool
        self.email = email_service
    
    async def check_trial_expiring(self):
        """Send reminders to users whose trial expires in 2 days."""
        
        # Find users with trial ending in 2 days
        users = await self.db.fetch(
            """
            SELECT u.id, u.email, u.name, s.trial_end
            FROM users u
            JOIN subscriptions s ON u.id = s.user_id
            WHERE s.tier = 'TRIAL' 
            AND s.status = 'ACTIVE'
            AND s.trial_end BETWEEN NOW() + INTERVAL '1 day' AND NOW() + INTERVAL '3 days'
            AND u.id NOT IN (
                SELECT DISTINCT target_id FROM audit_log 
                WHERE action_type = 'TRIAL_REMINDER_SENT' 
                AND logged_at > NOW() - INTERVAL '5 days'
            )
            """
        )
        
        for user in users:
            # Get their stats
            stats = await self.db.fetchrow(
                """
                SELECT 
                    COUNT(*) as sessions,
                    COUNT(DISTINCT DATE(created_at)) as days_active
                FROM sessions 
                WHERE user_id = $1
                """,
                user['id']
            )
            
            # Calculate actual coherence change from nevedal_metrics
            coherence_change = "+0%"
            try:
                first_c_emo = await self.db.fetchval(
                    """SELECT c_emo FROM nevedal_metrics
                       WHERE user_id = $1 ORDER BY recorded_at ASC LIMIT 1""",
                    user['id'],
                )
                latest_c_emo = await self.db.fetchval(
                    """SELECT c_emo FROM nevedal_metrics
                       WHERE user_id = $1 ORDER BY recorded_at DESC LIMIT 1""",
                    user['id'],
                )
                if first_c_emo and latest_c_emo and float(first_c_emo) > 0:
                    pct = ((float(latest_c_emo) - float(first_c_emo)) / float(first_c_emo)) * 100
                    sign = "+" if pct >= 0 else ""
                    coherence_change = f"{sign}{pct:.0f}%"
            except Exception as e:
                logger.debug("Coherence calc fallback: %s", e)
                coherence_change = "+0%"  # Graceful fallback

            await self.email.send_trial_expiring(
                user['email'],
                user['name'],
                sessions=stats['sessions'] or 0,
                coherence_change=coherence_change,
                insights=stats['sessions'] * 4  # Rough estimate
            )
            
            # Log that we sent reminder
            await self.db.execute(
                """
                INSERT INTO audit_log (action_type, target_id, description)
                VALUES ('TRIAL_REMINDER_SENT', $1, 'Trial expiring reminder email sent')
                """,
                user['id']
            )
    
    async def check_trial_expired(self):
        """Notify users whose trial has expired."""
        
        users = await self.db.fetch(
            """
            SELECT u.id, u.email, u.name
            FROM users u
            JOIN subscriptions s ON u.id = s.user_id
            WHERE s.tier = 'TRIAL' 
            AND s.trial_end < NOW()
            AND s.status = 'ACTIVE'
            """
        )
        
        for user in users:
            await self.email.send_trial_expired(user['email'], user['name'])
            
            # Update status to grace period
            await self.db.execute(
                "UPDATE subscriptions SET status = 'GRACE_PERIOD' WHERE user_id = $1",
                user['id']
            )
    
    async def check_coaching_reminders(self):
        """Send 24-hour reminders for coaching sessions."""
        
        sessions = await self.db.fetch(
            """
            SELECT 
                cs.id, cs.scheduled_at,
                c.email as client_email,
                coach.name as coach_name
            FROM coaching_sessions cs
            JOIN users c ON cs.client_id = c.id
            JOIN users coach ON cs.coach_id = coach.id
            WHERE cs.status = 'SCHEDULED'
            AND cs.scheduled_at BETWEEN NOW() + INTERVAL '23 hours' AND NOW() + INTERVAL '25 hours'
            AND cs.id NOT IN (
                SELECT DISTINCT target_id::uuid FROM audit_log 
                WHERE action_type = 'COACHING_REMINDER_SENT'
            )
            """
        )
        
        for session in sessions:
            time_str = session['scheduled_at'].strftime("%I:%M %p")
            await self.email.send_coaching_reminder(
                session['client_email'],
                time_str,
                session['coach_name']
            )
            
            await self.db.execute(
                """
                INSERT INTO audit_log (action_type, target_id, description)
                VALUES ('COACHING_REMINDER_SENT', $1, '24h reminder sent')
                """,
                str(session['id'])
            )


# =============================================================================
# USAGE EXAMPLE
# =============================================================================

"""
# In your FastAPI startup:

from app.services.notifications_service import EmailService, NotificationScheduler
import asyncio

email_service = EmailService()
scheduler = NotificationScheduler(db_pool, email_service)

# Run scheduled tasks
async def run_scheduled_tasks():
    while True:
        await scheduler.check_trial_expiring()
        await scheduler.check_trial_expired()
        await scheduler.check_coaching_reminders()
        await asyncio.sleep(3600)  # Run every hour

# Or use APScheduler / Celery for production
"""
