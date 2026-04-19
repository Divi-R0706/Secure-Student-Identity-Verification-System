import base64
import csv
import hashlib
import io
import mimetypes
import os
import random
import re
import smtplib
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from uuid import uuid4

import qrcode
from flask import Flask, abort, flash, has_request_context, jsonify, redirect, render_template, request, send_file, session, url_for


app = Flask(__name__)
app.secret_key = "secret123"
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
app.permanent_session_lifetime = timedelta(minutes=20)

MOJIBAKE_MARKERS = ("à", "â", "Ã", "Â", "Ø", "Ù", "Ð", "Ñ")
CP1252_REVERSE = {
    ord(char): byte
    for byte, char in enumerate(bytes(range(256)).decode("cp1252", errors="replace"))
    if ord(char) > 255
}

DB_NAME = "database.db"
CSV_STUDENT_DATA_FILE = "final_data_500.csv"
CSV_LOGIN_EMAIL_DOMAIN = "student.local"
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".docx"}
UPLOADS_DIR = os.path.join("static", "uploads")
LOCKOUT_LIMIT = 5
LOCKOUT_MINUTES = 15
SESSION_TIMEOUT_MINUTES = 20
SESSION_WARNING_MINUTES = 18


def repair_mojibake_text(value):
    if not isinstance(value, str) or not any(marker in value for marker in MOJIBAKE_MARKERS):
        return value
    try:
        raw_bytes = bytes(
            CP1252_REVERSE.get(ord(char), ord(char) if ord(char) <= 255 else 63)
            for char in value
        )
        repaired = raw_bytes.decode("utf-8")
        if repaired:
            return repaired
    except UnicodeError:
        pass
    return value


def repair_mojibake_structure(value):
    if isinstance(value, dict):
        return {key: repair_mojibake_structure(item) for key, item in value.items()}
    if isinstance(value, list):
        return [repair_mojibake_structure(item) for item in value]
    if isinstance(value, tuple):
        return tuple(repair_mojibake_structure(item) for item in value)
    return repair_mojibake_text(value)
SCHOOLS = [
    {"id": 1, "name": "1 - GHSS - Madurai East", "location": "Madurai"},
    {"id": 2, "name": "2 - GHSS - Coimbatore Town", "location": "Coimbatore"},
    {"id": 3, "name": "3 - GHSS - Salem North", "location": "Salem"},
    {"id": 4, "name": "4 - GHSS - Trichy Central", "location": "Trichy"},
]
SEEDED_SCHOOL_ADMINS = [
    ("Ravi Kumar", "admin1@gmail.com", "Admin@123", 1, "active"),
    ("Priya Devi", "admin2@gmail.com", "Admin@123", 2, "active"),
    ("Arun Raj", "admin3@gmail.com", "Admin@123", 3, "active"),
    ("Meena Lakshmi", "admin4@gmail.com", "Admin@123", 4, "active"),
]

SAVED_QR_FILENAMES = ("qr.png", "qr.jpg", "qr.jpeg", "qrcode.png", "qrcode.jpg")
ACADEMIC_YEAR = "2025-2026"
DEFAULT_LANGUAGE = "en"
LANGUAGE_OPTIONS = [
    {"code": "en", "label": "English"},
    {"code": "hi", "label": "हिन्दी"},
    {"code": "ta", "label": "தமிழ்"},
]
SUPPORTED_LANGUAGE_CODES = {item["code"] for item in LANGUAGE_OPTIONS}
GLOBAL_POPUP_DEFAULT_MODE = "once"
GLOBAL_POPUP_DEFAULT_DELAY_MS = 60000
GLOBAL_POPUP_DEFAULT_TITLE = "Welcome!"
GLOBAL_POPUP_DEFAULT_MESSAGE = "Explore our features."
GLOBAL_POPUP_ROUTE_MESSAGES = {
    "/": {"title": "Welcome!", "message": "Welcome to IDENZA!"},
    "/student/login": {"title": "Welcome!", "message": "Login to continue!"},
    "/student/dashboard": {"title": "Welcome!", "message": "Check your analytics!"},
    "/student/upload": {"title": "Welcome!", "message": "Upload documents to complete verification."},
    "/student/portals": {"title": "Welcome!", "message": "Explore useful learning portals."},
    "/student/tasks": {"title": "Welcome!", "message": "Keep track of your tasks and deadlines."},
    "/student/id-card": {"title": "Welcome!", "message": "Open your digital ID card."},
    "/admin/login": {"title": "Welcome!", "message": "Sign in to review student records."},
    "/admin/dashboard": {"title": "Welcome!", "message": "Manage students and verification activity."},
    "/admin/students": {"title": "Welcome!", "message": "Open a student to review documents."},
    "/audit-log": {"title": "Welcome!", "message": "Review administrative changes."},
    "/superadmin/dashboard": {"title": "Welcome!", "message": "Monitor schools and manage admins."},
    "/verify/": {"title": "Welcome!", "message": "Review the public verification details."},
}
TAMIL_SECTION_MAP = {
    "A": "à®…",
    "B": "à®†",
    "C": "à®‡",
    "D": "à®ˆ",
    "E": "à®‰",
    "F": "à®Š",
    "G": "à®Ž",
    "H": "à®",
    "I": "à®",
    "J": "à®’",
    "K": "à®“",
    "L": "à®”",
}
TAMIL_NAME_OVERRIDES = {
    "loganadhan": "à®²à¯‹à®•à®¨à®¾à®¤à®©à¯",
    "mani": "à®®à®£à®¿",
    "bharani": "à®ªà®°à®£à®¿",
    "anbarasu": "à®…à®©à¯à®ªà®°à®šà¯",
    "kaviya": "à®•à®¾à®µà®¿à®¯à®¾",
    "kavipriya": "à®•à®µà®¿à®ªà¯à®ªà®¿à®°à®¿à®¯à®¾",
    "kaviyapriya": "à®•à®µà®¿à®ªà¯à®ªà®¿à®°à®¿à®¯à®¾",
    "selvi": "à®šà¯†à®²à¯à®µà®¿",
    "kaviyarasu": "à®•à®µà®¿à®¯à®°à®šà¯",
    "manikandan": "à®®à®£à®¿à®•à®£à¯à®Ÿà®©à¯",
    "manimaran": "à®®à®£à®¿à®®à®¾à®±à®©à¯",
    "ravi": "à®°à®µà®¿",
    "priya": "à®ªà®¿à®°à®¿à®¯à®¾",
    "arun": "à®…à®°à¯à®£à¯",
    "meena": "à®®à¯€à®©à®¾",
    "lakshmi": "à®²à®•à¯à®·à¯à®®à®¿",
    "pradeepa": "à®ªà®¿à®°à®¤à¯€à®ªà®¾",
    "pari": "à®ªà®¾à®°à®¿",
    "tamil": "à®¤à®®à®¿à®´à¯",
    "kaviya devi": "à®•à®¾à®µà®¿à®¯à®¾ à®¤à¯‡à®µà®¿",
    "kaviya rajan": "à®•à®¾à®µà®¿à®¯à®¾ à®°à®¾à®œà®©à¯",
    "kaviya babu": "à®•à®¾à®µà®¿à®¯à®¾ à®ªà®¾à®ªà¯",
    "selvi babu": "à®šà¯†à®²à¯à®µà®¿ à®ªà®¾à®ªà¯",
    "selvi rajan": "à®šà¯†à®²à¯à®µà®¿ à®°à®¾à®œà®©à¯",
    "selvi pandian": "à®šà¯†à®²à¯à®µà®¿ à®ªà®¾à®£à¯à®Ÿà®¿à®¯à®©à¯",
    "anbarasu rajan": "à®…à®©à¯à®ªà®°à®šà¯ à®°à®¾à®œà®©à¯",
    "mani babu": "à®®à®£à®¿ à®ªà®¾à®ªà¯",
    "ravi mani": "à®°à®µà®¿ à®®à®£à®¿",
    "paari": "à®ªà®¾à®°à®¿",
    "iniya rajan": "இனியா ராஜன்",
    "dhanalakshmi": "தனலட்சுமி",
    "navanidhan": "நவநிதன்",
}
TAMIL_NAME_TOKEN_OVERRIDES = {
    "ajay": "அஜய்",
    "ajith": "அஜித்",
    "anbarasu": "அன்பரசு",
    "anupriya": "அனுப்ரியா",
    "arasu": "அரசு",
    "arun": "அருண்",
    "arunkumar": "அருண்குமார்",
    "arunmozli": "அருண்மொழி",
    "babu": "பாபு",
    "balan": "பாலன்",
    "bharani": "பரணி",
    "bhaskar": "பாஸ்கர்",
    "chitra": "சித்ரா",
    "chitradevi": "சித்ராதேவி",
    "deepa": "தீபா",
    "devi": "தேவி",
    "dhanalakshmi": "தனலட்சுமி",
    "dharani": "தரணி",
    "dinesh": "தினேஷ்",
    "dineshkumar": "தினேஷ்குமார்",
    "divyavarshini": "திவ்யவர்ஷினி",
    "ezhil": "எழில்",
    "ezhillarasi": "எழிலரசி",
    "gokul": "கோகுல்",
    "gokulan": "கோகுலன்",
    "haviska": "ஹவிஸ்கா",
    "iniya": "இனியா",
    "iniyan": "இனியன்",
    "jeeva": "ஜீவா",
    "jeevitha": "ஜீவிதா",
    "kanaga": "கனகா",
    "kaviya": "காவியா",
    "kavipriya": "கவிப்பிரியா",
    "kaviyapriya": "கவிப்பிரியா",
    "kaviyarasu": "கவியரசு",
    "kumar": "குமார்",
    "lathika": "லதிகா",
    "loganadhan": "லோகநாதன்",
    "lokesh": "லோகேஷ்",
    "madhu": "மது",
    "mani": "மணி",
    "manikandan": "மணிகண்டன்",
    "manimaran": "மணிமாறன்",
    "maran": "மாறன்",
    "mohan": "மோகன்",
    "murugan": "முருகன்",
    "navanidhan": "நவநிதன்",
    "nila": "நிலா",
    "nivetha": "நிவேதா",
    "oviya": "ஓவியா",
    "pandian": "பாண்டியன்",
    "pari": "பாரி",
    "paari": "பாரி",
    "pradeepa": "பிரதீபா",
    "praveen": "பிரவீன்",
    "priya": "பிரியா",
    "rajan": "ராஜன்",
    "raman": "ராமன்",
    "ravi": "ரவி",
    "ravikumar": "ரவிகுமார்",
    "ruba": "ரூபா",
    "sadhana": "சாதனா",
    "sandhiya": "சந்தியா",
    "sarmatha": "சர்மதா",
    "sarumathi": "சாருமதி",
    "selvam": "செல்வம்",
    "tamil": "தமிழ்",
    "vel": "வேல்",
}
TAMIL_VOWEL_SIGNS = {
    "a": "",
    "aa": "à®¾",
    "i": "à®¿",
    "ii": "à¯€",
    "ee": "à¯€",
    "u": "à¯",
    "uu": "à¯‚",
    "oo": "à¯‚",
    "e": "à¯†",
    "o": "à¯Š",
    "ai": "à¯ˆ",
    "au": "à¯Œ",
}
TAMIL_INDEPENDENT_VOWELS = {
    "a": "à®…",
    "aa": "à®†",
    "i": "à®‡",
    "ii": "à®ˆ",
    "ee": "à®ˆ",
    "u": "à®‰",
    "uu": "à®Š",
    "oo": "à®Š",
    "e": "à®Ž",
    "o": "à®’",
    "ai": "à®",
    "au": "à®”",
}
TAMIL_CONSONANTS = {
    "k": "à®•",
    "g": "à®•",
    "c": "à®š",
    "j": "à®œ",
    "t": "à®Ÿ",
    "d": "à®Ÿ",
    "n": "à®¨",
    "p": "à®ª",
    "b": "à®ª",
    "m": "à®®",
    "y": "à®¯",
    "r": "à®°",
    "l": "à®²",
    "v": "à®µ",
    "s": "à®š",
    "h": "à®¹",
    "f": "à®ƒà®ª",
    "z": "à®œ",
    "q": "à®•",
    "x": "à®•à¯à®¸à¯",
}
TAMIL_DIGRAPHS = {
    "ng": "à®™",
    "ch": "à®š",
    "sh": "à®·",
    "th": "à®¤",
    "dh": "à®¤",
    "ph": "à®ª",
    "bh": "à®ª",
    "kh": "à®•",
    "gh": "à®•",
    "zh": "à®´",
    "rr": "à®±",
    "ll": "à®³",
    "nn": "à®©",
}
TRANSLATIONS = {
    "hi": {
        "Dashboard": "à¤¡à¥ˆà¤¶à¤¬à¥‹à¤°à¥à¤¡",
        "Upload Documents": "à¤¦à¤¸à¥à¤¤à¤¾à¤µà¥‡à¤œà¤¼ à¤…à¤ªà¤²à¥‹à¤¡ à¤•à¤°à¥‡à¤‚",
        "My Tasks": "à¤®à¥‡à¤°à¥‡ à¤•à¤¾à¤°à¥à¤¯",
        "Portals": "à¤ªà¥‹à¤°à¥à¤Ÿà¤²",
        "Manage Students": "à¤›à¤¾à¤¤à¥à¤° à¤ªà¥à¤°à¤¬à¤‚à¤§à¤¨",
        "Secure student verification": "à¤¸à¥à¤°à¤•à¥à¤·à¤¿à¤¤ à¤›à¤¾à¤¤à¥à¤° à¤¸à¤¤à¥à¤¯à¤¾à¤ªà¤¨",
        "Notifications": "à¤¸à¥‚à¤šà¤¨à¤¾à¤à¤‚",
        "Overdue tasks": "à¤²à¤‚à¤¬à¤¿à¤¤ à¤•à¤¾à¤°à¥à¤¯",
        "Student alerts": "छात्र सूचनाएं",
        "Task overdue": "कार्य की समयसीमा समाप्त",
        "Document rejected": "दस्तावेज़ अस्वीकृत",
        "Please review the rejection reason and upload a corrected file.": "कृपया अस्वीकृति कारण देखें और सही फ़ाइल फिर से अपलोड करें।",
        "Rejected documents need correction and re-upload.": "अस्वीकृत दस्तावेज़ों को सुधारकर फिर से अपलोड करना होगा।",
        "View uploads": "अपलोड देखें",
        "No notifications right now.": "à¤…à¤­à¥€ à¤•à¥‹à¤ˆ à¤¸à¥‚à¤šà¤¨à¤¾ à¤¨à¤¹à¥€à¤‚ à¤¹à¥ˆà¥¤",
        "Student": "à®®à®¾à®£à®µà®°à¯",
        "Super Admin": "à®šà¯‚à®ªà¯à®ªà®°à¯ à®…à®Ÿà¯à®®à®¿à®©à¯",
        "Logout": "à®µà¯†à®³à®¿à®¯à¯‡à®±à¯",
        "Language": "à®®à¯Šà®´à®¿",
        "Student identity verification access": "à®®à®¾à®£à®µà®°à¯ à®…à®Ÿà¯ˆà®¯à®¾à®³ à®šà®°à®¿à®ªà®¾à®°à¯à®ªà¯à®ªà¯ à®…à®£à¯à®•à®²à¯",
        "Administrative access": "à®¨à®¿à®°à¯à®µà®¾à®• à®…à®£à¯à®•à®²à¯",
        "Super admin control center": "à®šà¯‚à®ªà¯à®ªà®°à¯ à®…à®Ÿà¯à®®à®¿à®©à¯ à®•à®Ÿà¯à®Ÿà¯à®ªà¯à®ªà®¾à®Ÿà¯à®Ÿà¯ à®®à¯ˆà®¯à®®à¯",
        "Admin Login": "à®…à®Ÿà¯à®®à®¿à®©à¯ à®‰à®³à¯à®¨à¯à®´à¯ˆà®µà¯",
        "Super Admin Login": "à®šà¯‚à®ªà¯à®ªà®°à¯ à®…à®Ÿà¯à®®à®¿à®©à¯ à®‰à®³à¯à®¨à¯à®´à¯ˆà®µà¯",
        "Email": "à®®à®¿à®©à¯à®©à®žà¯à®šà®²à¯",
        "Password": "à®•à®Ÿà®µà¯à®šà¯à®šà¯Šà®²à¯",
        "Forgot password?": "à®•à®Ÿà®µà¯à®šà¯à®šà¯Šà®²à¯ à®®à®±à®¨à¯à®¤à¯à®µà®¿à®Ÿà¯à®Ÿà®¤à®¾?",
        "Student ID": "à®®à®¾à®£à®µà®°à¯ à®à®Ÿà®¿",
        "Enter student ID": "à®®à®¾à®£à®µà®°à¯ à®à®Ÿà®¿à®¯à¯ˆ à®‰à®³à¯à®³à®¿à®Ÿà®µà¯à®®à¯",
        "Send OTP": "à®“à®Ÿà®¿à®ªà®¿ à®…à®©à¯à®ªà¯à®ªà¯",
        "Verify OTP": "à®“à®Ÿà®¿à®ªà®¿ à®šà®°à®¿à®ªà®¾à®°à¯",
        "Resend OTP": "à®“à®Ÿà®¿à®ªà®¿ à®®à¯€à®£à¯à®Ÿà¯à®®à¯ à®…à®©à¯à®ªà¯à®ªà¯",
        "OTP Verification": "à®“à®Ÿà®¿à®ªà®¿ à®šà®°à®¿à®ªà®¾à®°à¯à®ªà¯à®ªà¯",
        "Enter OTP": "à®“à®Ÿà®¿à®ªà®¿ à®‰à®³à¯à®³à®¿à®Ÿà®µà¯à®®à¯",
        "Identity Verification": "à®…à®Ÿà¯ˆà®¯à®¾à®³ à®šà®°à®¿à®ªà®¾à®°à¯à®ªà¯à®ªà¯",
        "Status": "à®¨à®¿à®²à¯ˆ",
        "Academic Year": "à®•à®²à¯à®µà®¿à®¯à®¾à®£à¯à®Ÿà¯",
        "Verification URL": "à®šà®°à®¿à®ªà®¾à®°à¯à®ªà¯à®ªà¯ à®‡à®£à¯ˆà®ªà¯à®ªà¯",
        "Verification Time": "à®šà®°à®¿à®ªà®¾à®°à¯à®ªà¯à®ªà¯ à®¨à¯‡à®°à®®à¯",
        "This identity has been verified by IDENZA.": "à®‡à®¨à¯à®¤ à®…à®Ÿà¯ˆà®¯à®¾à®³à®®à¯ IDENZA à®®à¯‚à®²à®®à¯ à®šà®°à®¿à®ªà®¾à®°à¯à®•à¯à®•à®ªà¯à®ªà®Ÿà¯à®Ÿà®¤à¯.",
        "This identity record is currently marked as rejected in IDENZA.": "à®‡à®¨à¯à®¤ à®…à®Ÿà¯ˆà®¯à®¾à®³ à®ªà®¤à®¿à®µà¯ à®¤à®±à¯à®ªà¯‹à®¤à¯ IDENZA-à®µà®¿à®²à¯ à®¨à®¿à®°à®¾à®•à®°à®¿à®•à¯à®•à®ªà¯à®ªà®Ÿà¯à®Ÿà®¤à®¾à®• à®•à¯à®±à®¿à®•à¯à®•à®ªà¯à®ªà®Ÿà¯à®Ÿà¯à®³à¯à®³à®¤à¯.",
        "This identity is currently pending confirmation in IDENZA.": "à®‡à®¨à¯à®¤ à®…à®Ÿà¯ˆà®¯à®¾à®³à®®à¯ à®¤à®±à¯à®ªà¯‹à®¤à¯ IDENZA-à®µà®¿à®²à¯ à®‰à®±à¯à®¤à®¿à®ªà¯à®ªà®Ÿà¯à®¤à¯à®¤à®ªà¯à®ªà®Ÿà®¾à®®à®²à¯ à®¨à®¿à®²à¯à®µà¯ˆà®¯à®¿à®²à¯ à®‰à®³à¯à®³à®¤à¯.",
        "Student identity details for secure verification.": "à®ªà®¾à®¤à¯à®•à®¾à®ªà¯à®ªà®¾à®© à®šà®°à®¿à®ªà®¾à®°à¯à®ªà¯à®ªà®¿à®±à¯à®•à®¾à®© à®®à®¾à®£à®µà®°à¯ à®…à®Ÿà¯ˆà®¯à®¾à®³ à®µà®¿à®µà®°à®™à¯à®•à®³à¯.",
        "Role: School Admin | Scope:": "à®ªà®™à¯à®•à¯: à®ªà®³à¯à®³à®¿ à®¨à®¿à®°à¯à®µà®¾à®•à®¿ | à®µà®°à®®à¯à®ªà¯:",
        "School Admin only |": "à®ªà®³à¯à®³à®¿ à®¨à®¿à®°à¯à®µà®¾à®•à®¿ à®®à®Ÿà¯à®Ÿà¯à®®à¯ |",
        "Add Student": "à®®à®¾à®£à®µà®°à¯ˆ à®šà¯‡à®°à¯à®•à¯à®•",
        "Student Name": "à®®à®¾à®£à®µà®°à¯ à®ªà¯†à®¯à®°à¯",
        "Class & Section": "à®µà®•à¯à®ªà¯à®ªà¯ à®®à®±à¯à®±à¯à®®à¯ à®ªà®¿à®°à®¿à®µà¯",
        "Parent Mobile": "à®ªà¯†à®±à¯à®±à¯‹à®°à¯ à®•à¯ˆà®ªà¯‡à®šà®¿",
        "Date of Birth": "à®ªà®¿à®±à®¨à¯à®¤ à®¤à¯‡à®¤à®¿",
        "Search Students": "à®®à®¾à®£à®µà®°à¯à®•à®³à¯ˆ à®¤à¯‡à®Ÿà¯à®•",
        "Student Directory": "à®®à®¾à®£à®µà®°à¯ à®ªà®Ÿà¯à®Ÿà®¿à®¯à®²à¯",
        "Actions": "à®šà¯†à®¯à®²à¯à®•à®³à¯",
        "Edit Student": "à®®à®¾à®£à®µà®°à¯ˆ à®¤à®¿à®°à¯à®¤à¯à®¤à¯",
        "Edit Student Details": "à®®à®¾à®£à®µà®°à¯ à®µà®¿à®µà®°à®™à¯à®•à®³à¯ˆ à®¤à®¿à®°à¯à®¤à¯à®¤à¯",
        "EMIS ID": "EMIS à®à®Ÿà®¿",
        "Class": "à®µà®•à¯à®ªà¯à®ªà¯",
        "Document Types": "à®†à®µà®£ à®µà®•à¯ˆà®•à®³à¯",
        "Document Type": "à®†à®µà®£ à®µà®•à¯ˆ",
        "File Name": "à®•à¯‹à®ªà¯à®ªà¯ à®ªà¯†à®¯à®°à¯",
        "Uploaded At": "à®ªà®¤à®¿à®µà¯‡à®±à¯à®±à®ªà¯à®ªà®Ÿà¯à®Ÿ à®¨à¯‡à®°à®®à¯",
        "Action": "à®šà¯†à®¯à®²à¯",
        "Task Description": "à®ªà®£à®¿ à®µà®¿à®³à®•à¯à®•à®®à¯",
        "Date & Time": "à®¤à¯‡à®¤à®¿ à®®à®±à¯à®±à¯à®®à¯ à®¨à¯‡à®°à®®à¯",
        "School Admin Accounts": "à®ªà®³à¯à®³à®¿ à®¨à®¿à®°à¯à®µà®¾à®•à®¿ à®•à®£à®•à¯à®•à¯à®•à®³à¯",
        "Name": "à®ªà¯†à®¯à®°à¯",
        "Search": "à®¤à¯‡à®Ÿà¯à®•",
        "Student Name / ID / EMIS / School / Status": "à®®à®¾à®£à®µà®°à¯ à®ªà¯†à®¯à®°à¯ / à®à®Ÿà®¿ / EMIS / à®ªà®³à¯à®³à®¿ / à®¨à®¿à®²à¯ˆ",
        "Due": "à®•à®Ÿà¯ˆà®šà®¿ à®¤à¯‡à®¤à®¿",
        "Student alerts": "மாணவர் அறிவிப்புகள்",
        "Task overdue": "பணி காலாவதியானது",
        "Document rejected": "ஆவணம் நிராகரிக்கப்பட்டது",
        "Please review the rejection reason and upload a corrected file.": "நிராகரிப்பு காரணத்தை பார்த்து சரியான கோப்பை மீண்டும் பதிவேற்றவும்.",
        "Rejected documents need correction and re-upload.": "நிராகரிக்கப்பட்ட ஆவணங்கள் திருத்தப்பட்டு மீண்டும் பதிவேற்றப்பட வேண்டும்.",
        "View uploads": "பதிவேற்றங்களை பார்",
        "Deadline ended. Please update this task now.": "à®•à®¾à®²à®•à¯à®•à¯†à®Ÿà¯ à®®à¯à®Ÿà®¿à®¨à¯à®¤à¯à®µà®¿à®Ÿà¯à®Ÿà®¤à¯. à®‡à®¨à¯à®¤ à®ªà®£à®¿à®¯à¯ˆ à®‡à®ªà¯à®ªà¯‹à®¤à¯ à®ªà¯à®¤à¯à®ªà¯à®ªà®¿à®•à¯à®•à®µà¯à®®à¯.",
        "Create your first task to start tracking deadlines.": "à®•à®¾à®²à®•à¯à®•à¯†à®Ÿà¯à®•à®³à¯ˆ à®•à®£à¯à®•à®¾à®£à®¿à®•à¯à®• à®‰à®™à¯à®•à®³à¯ à®®à¯à®¤à®²à¯ à®ªà®£à®¿à®¯à¯ˆ à®‰à®°à¯à®µà®¾à®•à¯à®•à®µà¯à®®à¯.",
        "Ready to deploy the project": "à®¤à®¿à®Ÿà¯à®Ÿà®¤à¯à®¤à¯ˆ à®µà¯†à®³à®¿à®¯à®¿à®Ÿ à®¤à®¯à®¾à®°à®¾à®• à®‰à®³à¯à®³à®¤à¯",
        "complete the project and deploy": "à®¤à®¿à®Ÿà¯à®Ÿà®¤à¯à®¤à¯ˆ à®®à¯à®Ÿà®¿à®¤à¯à®¤à¯ à®µà¯†à®³à®¿à®¯à®¿à®Ÿà®µà¯à®®à¯",
        "pradeepa": "à®ªà®¿à®°à®¤à¯€à®ªà®¾",
        "Pradeepa": "à®ªà®¿à®°à®¤à¯€à®ªà®¾",
        "Ravi Kumar": "à®°à®µà®¿à®•à¯à®®à®¾à®°à¯",
        "Priya Devi": "à®ªà®¿à®°à®¿à®¯à®¾ à®¤à¯‡à®µà®¿",
        "Arun Raj": "à®…à®°à¯à®£à¯ à®°à®¾à®œà¯",
        "Meena Lakshmi": "à®®à¯€à®©à®¾ à®²à®Ÿà¯à®šà¯à®®à®¿",
        "Class-wise Distribution": "à®µà®•à¯à®ªà¯à®ªà¯ à®µà®¾à®°à®¿à®¯à®¾à®• à®ªà®•à®¿à®°à¯à®µà¯",
        "Schools currently onboarded into the IDENZA network.": "à®¤à®±à¯à®ªà¯‹à®¤à¯ IDENZA à®µà®²à¯ˆà®¯à®®à¯ˆà®ªà¯à®ªà®¿à®²à¯ à®‡à®£à¯ˆà®•à¯à®•à®ªà¯à®ªà®Ÿà¯à®Ÿà¯à®³à¯à®³ à®ªà®³à¯à®³à®¿à®•à®³à¯.",
        "Add Course": "à®ªà®¾à®Ÿà®¤à¯à®¤à¯ˆ à®šà¯‡à®°à¯à®•à¯à®•",
        "Save Academic Data": "à®•à®²à¯à®µà®¿ à®¤à®•à®µà®²à¯ˆ à®šà¯‡à®®à®¿à®•à¯à®•",
        "No students found.": "à®®à®¾à®£à®µà®°à¯à®•à®³à¯ à®Žà®µà®°à¯à®®à¯ à®•à®¿à®Ÿà¯ˆà®•à¯à®•à®µà®¿à®²à¯à®²à¯ˆ.",
        "School issued identity card": "à®ªà®³à¯à®³à®¿ à®µà®´à®™à¯à®•à®¿à®¯ à®…à®Ÿà¯ˆà®¯à®¾à®³ à®…à®Ÿà¯à®Ÿà¯ˆ",
        "1 - GHSS - Madurai East": "1 - à®…à®°à®šà¯ à®®à¯‡à®²à¯à®¨à®¿à®²à¯ˆà®ªà¯à®ªà®³à¯à®³à®¿ - à®®à®¤à¯à®°à¯ˆ à®•à®¿à®´à®•à¯à®•à¯",
        "2 - GHSS - Coimbatore Town": "2 - à®…à®°à®šà¯ à®®à¯‡à®²à¯à®¨à®¿à®²à¯ˆà®ªà¯à®ªà®³à¯à®³à®¿ - à®•à¯‹à®¯à®®à¯à®ªà¯à®¤à¯à®¤à¯‚à®°à¯ à®¨à®•à®°à®®à¯",
        "3 - GHSS - Salem North": "3 - à®…à®°à®šà¯ à®®à¯‡à®²à¯à®¨à®¿à®²à¯ˆà®ªà¯à®ªà®³à¯à®³à®¿ - à®šà¯‡à®²à®®à¯ à®µà®Ÿà®•à¯à®•à¯",
        "4 - GHSS - Trichy Central": "4 - à®…à®°à®šà¯ à®®à¯‡à®²à¯à®¨à®¿à®²à¯ˆà®ªà¯à®ªà®³à¯à®³à®¿ - à®¤à®¿à®°à¯à®šà¯à®šà®¿ à®®à¯ˆà®¯à®®à¯",
        "ID Card": "à®…à®Ÿà¯ˆà®¯à®¾à®³ à®…à®Ÿà¯à®Ÿà¯ˆ",
        "Birth Certificate": "à®ªà®¿à®±à®ªà¯à®ªà¯à®šà¯ à®šà®¾à®©à¯à®±à®¿à®¤à®´à¯",
        "Aadhaar": "à®†à®¤à®¾à®°à¯",
        "Transfer Certificate": "à®®à®¾à®±à¯à®±à¯à®šà¯ à®šà®¾à®©à¯à®±à®¿à®¤à®´à¯",
        "Community Certificate": "à®šà®®à¯‚à®•à®šà¯ à®šà®¾à®©à¯à®±à®¿à®¤à®´à¯",
        "Bank Passbook": "à®µà®™à¯à®•à®¿ à®ªà®¾à®¸à¯à®ªà¯à®•à¯",
        "School": "à®ªà®³à¯à®³à®¿",
        "EMIS ID": "EMIS à®à®Ÿà®¿",
        "Class": "à®µà®•à¯à®ªà¯à®ªà¯",
        "Date of Birth": "à®ªà®¿à®±à®¨à¯à®¤ à®¤à¯‡à®¤à®¿",
        "Current Class & Section": "à®¤à®±à¯à®ªà¯‹à®¤à¯ˆà®¯ à®µà®•à¯à®ªà¯à®ªà¯",
        "Live class assignment from the student profile.": "à®®à®¾à®£à®µà®°à¯ à®šà¯à®¯à®µà®¿à®µà®°à®¤à¯à®¤à®¿à®²à¯ à®‰à®³à¯à®³ à®¤à®±à¯à®ªà¯‹à®¤à¯ˆà®¯ à®µà®•à¯à®ªà¯à®ªà¯ à®µà®¿à®µà®°à®®à¯.",
        "Current verification cycle used for your ID card.": "à®‰à®™à¯à®•à®³à¯ à®…à®Ÿà¯ˆà®¯à®¾à®³ à®…à®Ÿà¯à®Ÿà¯ˆà®•à¯à®•à¯ à®ªà®¯à®©à¯à®ªà®Ÿà¯à®¤à¯à®¤à®ªà¯à®ªà®Ÿà¯à®®à¯ à®¤à®±à¯à®ªà¯‹à®¤à¯ˆà®¯ à®šà®°à®¿à®ªà®¾à®°à¯à®ªà¯à®ªà¯ à®šà¯à®±à¯à®±à¯.",
        "Recent Activity": "à®šà®®à¯€à®ªà®¤à¯à®¤à®¿à®¯ à®šà¯†à®¯à®²à¯à®ªà®¾à®Ÿà¯",
        "Latest documents uploaded to your profile.": "à®‰à®™à¯à®•à®³à¯ à®šà¯à®¯à®µà®¿à®µà®°à®¤à¯à®¤à®¿à®²à¯ à®šà®®à¯€à®ªà®¤à¯à®¤à®¿à®²à¯ à®ªà®¤à®¿à®µà¯‡à®±à¯à®±à®ªà¯à®ªà®Ÿà¯à®Ÿ à®†à®µà®£à®™à¯à®•à®³à¯.",
        "items": "à®‰à®°à¯à®ªà¯à®ªà®Ÿà®¿à®•à®³à¯",
        "No recent uploads yet": "à®‡à®©à¯à®©à¯à®®à¯ à®šà®®à¯€à®ªà®¤à¯à®¤à®¿à®¯ à®ªà®¤à®¿à®µà¯‡à®±à¯à®±à®™à¯à®•à®³à¯ à®‡à®²à¯à®²à¯ˆ",
        "Your uploaded documents will appear here once they are submitted.": "à®¨à¯€à®™à¯à®•à®³à¯ à®ªà®¤à®¿à®µà¯‡à®±à¯à®±à®¿à®¯ à®†à®µà®£à®™à¯à®•à®³à¯ à®šà®®à®°à¯à®ªà¯à®ªà®¿à®•à¯à®•à®ªà¯à®ªà®Ÿà¯à®Ÿà®¤à¯à®®à¯ à®‡à®™à¯à®•à¯‡ à®¤à¯‹à®©à¯à®±à¯à®®à¯.",
        "QR Verification": "QR à®šà®°à®¿à®ªà®¾à®°à¯à®ªà¯à®ªà¯",
        "Shareable identity verification details for your school record.": "à®‰à®™à¯à®•à®³à¯ à®ªà®³à¯à®³à®¿ à®ªà®¤à®¿à®µà®¿à®±à¯à®•à®¾à®© à®ªà®•à®¿à®°à®•à¯à®•à¯‚à®Ÿà®¿à®¯ à®…à®Ÿà¯ˆà®¯à®¾à®³ à®šà®°à®¿à®ªà®¾à®°à¯à®ªà¯à®ªà¯ à®µà®¿à®µà®°à®™à¯à®•à®³à¯.",
        "Instant ID Verification": "à®‰à®Ÿà®©à®Ÿà®¿ à®…à®Ÿà¯ˆà®¯à®¾à®³ à®šà®°à®¿à®ªà®¾à®°à¯à®ªà¯à®ªà¯",
        "Present this secure digital pass for entrance or document verification at campus terminals.": "à®µà®³à®¾à®• à®¨à¯à®´à¯ˆà®µà¯ à®…à®²à¯à®²à®¤à¯ à®†à®µà®£ à®šà®°à®¿à®ªà®¾à®°à¯à®ªà¯à®ªà®¿à®±à¯à®•à®¾à®• à®‡à®¨à¯à®¤ à®ªà®¾à®¤à¯à®•à®¾à®ªà¯à®ªà®¾à®© à®Ÿà®¿à®œà®¿à®Ÿà¯à®Ÿà®²à¯ à®…à®Ÿà¯ˆà®¯à®¾à®³à®¤à¯à®¤à¯ˆ à®ªà®¯à®©à¯à®ªà®Ÿà¯à®¤à¯à®¤à®µà¯à®®à¯.",
        "Class Group": "à®µà®•à¯à®ªà¯à®ªà¯ à®•à¯à®´à¯",
        "Global Status": "à®®à¯Šà®¤à¯à®¤ à®¨à®¿à®²à¯ˆ",
        "School Admin Dashboard": "à®ªà®³à¯à®³à®¿ à®…à®Ÿà¯à®®à®¿à®©à¯ à®Ÿà®¾à®·à¯à®ªà¯‹à®°à¯à®Ÿà¯",
        "Super Admin Dashboard": "à®šà¯‚à®ªà¯à®ªà®°à¯ à®…à®Ÿà¯à®®à®¿à®©à¯ à®Ÿà®¾à®·à¯à®ªà¯‹à®°à¯à®Ÿà¯",
        "Total Students": "à®®à¯Šà®¤à¯à®¤ à®®à®¾à®£à®µà®°à¯à®•à®³à¯",
        "Total Schools": "à®®à¯Šà®¤à¯à®¤ à®ªà®³à¯à®³à®¿à®•à®³à¯",
        "Open Portal": "à®¤à®³à®¤à¯à®¤à¯ˆà®¤à¯ à®¤à®¿à®±",
        "Step 1": "à®ªà®Ÿà®¿ 1",
        "Step 2": "à®ªà®Ÿà®¿ 2",
        "Step 3": "à®ªà®Ÿà®¿ 3",
        "Credentials submitted": "à®šà®¾à®©à¯à®±à¯à®•à®³à¯ à®šà®®à®°à¯à®ªà¯à®ªà®¿à®•à¯à®•à®ªà¯à®ªà®Ÿà¯à®Ÿà®©",
        "We sent a 6-digit verification code for your student login.": "à®‰à®™à¯à®•à®³à¯ à®®à®¾à®£à®µà®°à¯ à®‰à®³à¯à®¨à¯à®´à¯ˆà®µà¯à®•à¯à®•à®¾à®• 6 à®‡à®²à®•à¯à®• à®šà®°à®¿à®ªà®¾à®°à¯à®ªà¯à®ªà¯ à®•à¯à®±à®¿à®¯à¯€à®Ÿà¯ à®…à®©à¯à®ªà¯à®ªà®ªà¯à®ªà®Ÿà¯à®Ÿà¯à®³à¯à®³à®¤à¯.",
        "Upload Document": "à®†à®µà®£à®¤à¯à®¤à¯ˆ à®ªà®¤à®¿à®µà¯‡à®±à¯à®±à¯",
        "Uploaded Files": "à®ªà®¤à®¿à®µà¯‡à®±à¯à®±à®ªà¯à®ªà®Ÿà¯à®Ÿ à®•à¯‹à®ªà¯à®ªà¯à®•à®³à¯",
        "Download": "à®ªà®¤à®¿à®µà®¿à®±à®•à¯à®•à¯",
        "Delete": "à®¨à¯€à®•à¯à®•à¯",
        "Create Task": "à®ªà®£à®¿ à®‰à®°à¯à®µà®¾à®•à¯à®•à¯",
        "Add Task": "à®ªà®£à®¿ à®šà¯‡à®°à¯à®•à¯à®•",
        "Pending": "à®¨à®¿à®²à¯à®µà¯ˆà®¯à®¿à®²à¯",
        "Completed": "à®®à¯à®Ÿà®¿à®¨à¯à®¤à®¤à¯",
        "Overdue": "à®•à®¾à®²à®¾à®µà®¤à®¿à®¯à®¾à®©à®¤à¯",
        "Verified": "à®šà®°à®¿à®ªà®¾à®°à¯à®•à¯à®•à®ªà¯à®ªà®Ÿà¯à®Ÿà®¤à¯",
        "Rejected": "à®¨à®¿à®°à®¾à®•à®°à®¿à®•à¯à®•à®ªà¯à®ªà®Ÿà¯à®Ÿà®¤à¯",
        "Active": "à®šà¯†à®¯à®²à®¿à®²à¯",
        "Inactive": "à®šà¯†à®¯à®²à®±à¯à®±à®¤à¯",
        "No tasks added yet": "à®‡à®©à¯à®©à¯à®®à¯ à®ªà®£à®¿à®•à®³à¯ à®šà¯‡à®°à¯à®•à¯à®•à®ªà¯à®ªà®Ÿà®µà®¿à®²à¯à®²à¯ˆ.",
        "Student Identity Card": "à®®à®¾à®£à®µà®°à¯ à®…à®Ÿà¯ˆà®¯à®¾à®³ à®…à®Ÿà¯à®Ÿà¯ˆ",
        "Download ID Card": "à®…à®Ÿà¯ˆà®¯à®¾à®³ à®…à®Ÿà¯à®Ÿà¯ˆà®¯à¯ˆ à®ªà®¤à®¿à®µà®¿à®±à®•à¯à®•à¯",
        "Refresh QR": "QR-à® à®ªà¯à®¤à¯à®ªà¯à®ªà®¿",
        "Open QR Details": "QR à®µà®¿à®µà®°à®™à¯à®•à®³à¯ˆà®¤à¯ à®¤à®¿à®±",
        "Forgot Password": "à®•à®Ÿà®µà¯à®šà¯à®šà¯Šà®²à¯ à®®à®±à®¨à¯à®¤à¯à®µà®¿à®Ÿà¯à®Ÿà®¤à¯",
        "New Password": "à®ªà¯à®¤à®¿à®¯ à®•à®Ÿà®µà¯à®šà¯à®šà¯Šà®²à¯",
        "Confirm Password": "à®•à®Ÿà®µà¯à®šà¯à®šà¯Šà®²à¯à®²à¯ˆ à®‰à®±à¯à®¤à®¿à®ªà¯à®ªà®Ÿà¯à®¤à¯à®¤à¯",
        "Reset Password": "à®•à®Ÿà®µà¯à®šà¯à®šà¯Šà®²à¯à®²à¯ˆ à®®à¯€à®Ÿà¯à®Ÿà®®à¯ˆ",
        "Back to Login": "à®‰à®³à¯à®¨à¯à®´à¯ˆà®µà¯à®•à¯à®•à¯ à®¤à®¿à®°à¯à®®à¯à®ªà¯",
    },
}


TRANSLATIONS.setdefault("ta", {}).update(
    {
        "Learning": "à®•à®±à¯à®±à®²à¯",
        "Courses": "à®ªà®¾à®Ÿà®¤à¯à®¤à®¿à®Ÿà¯à®Ÿà®™à¯à®•à®³à¯",
        "Scholarships": "à®®à®¾à®£à®µà®°à¯ à®‰à®¤à®µà®¿",
        "Career": "à®¤à¯Šà®´à®¿à®²à¯",
        "DIKSHA": "à®¤à¯€à®•à¯à®·à®¾",
        "SWAYAM": "à®¸à¯à®µà®¯à®®à¯",
        "National Scholarship Portal": "à®¤à¯‡à®šà®¿à®¯ à®®à¯‡à®±à¯à®ªà¯à®²à¯ˆ à®¤à®¿à®Ÿà¯à®Ÿà®¤à¯à®¤à®³à®®à¯",
        "National Career Service": "à®¤à¯‡à®šà®¿à®¯ à®¤à¯Šà®´à®¿à®²à¯ à®šà¯‡à®µà¯ˆ",
        "National digital infrastructure for school education": "à®ªà®³à¯à®³à®¿ à®•à®²à¯à®µà®¿à®•à¯à®•à®¾à®© à®¤à¯‡à®šà®¿à®¯ à®Ÿà®¿à®œà®¿à®Ÿà¯à®Ÿà®²à¯ à®…à®®à¯ˆà®ªà¯à®ªà¯",
        "Government online courses and certification platform": "à®…à®°à®šà¯ à®¨à¯‡à®°à®Ÿà®¿ à®ªà®¾à®Ÿà®™à¯à®•à®³à¯ à®®à®±à¯à®±à¯à®®à¯ à®šà®¾à®©à¯à®±à®¿à®¤à®´à¯ à®¤à®³à®®à¯",
        "Centralized scholarship applications and status tracking": "à®®à¯ˆà®¯à®ªà¯à®ªà®Ÿà¯à®¤à¯à®¤à®ªà¯à®ªà®Ÿà¯à®Ÿ à®•à®²à¯à®µà®¿ à®‰à®¤à®µà®¿ à®µà®¿à®£à¯à®£à®ªà¯à®ªà®™à¯à®•à®³à¯ à®®à®±à¯à®±à¯à®®à¯ à®¨à®¿à®²à¯ˆ à®•à®£à¯à®•à®¾à®£à®¿à®ªà¯à®ªà¯",
        "Career guidance, skill opportunities, and job search resources": "à®¤à¯Šà®´à®¿à®²à¯ à®µà®´à®¿à®•à®¾à®Ÿà¯à®Ÿà®²à¯, à®¤à®¿à®±à®©à¯ à®µà®¾à®¯à¯à®ªà¯à®ªà¯à®•à®³à¯, à®®à®±à¯à®±à¯à®®à¯ à®µà¯‡à®²à¯ˆ à®¤à¯‡à®Ÿà®²à¯ à®µà®³à®™à¯à®•à®³à¯",
        "Recent logins": "à®šà®®à¯€à®ªà®¤à¯à®¤à®¿à®¯ à®‰à®³à¯à®¨à¯à®´à¯ˆà®µà¯à®•à®³à¯",
        "Last successful account access records.": "à®•à®Ÿà¯ˆà®šà®¿à®¯à®¾à®• à®µà¯†à®±à¯à®±à®¿à®¯à®Ÿà¯ˆà®¨à¯à®¤ à®•à®£à®•à¯à®•à¯ à®…à®£à¯à®•à®²à¯ à®ªà®¤à®¿à®µà¯à®•à®³à¯.",
        "No recent logins yet": "à®‡à®©à¯à®©à¯à®®à¯ à®šà®®à¯€à®ªà®¤à¯à®¤à®¿à®¯ à®‰à®³à¯à®¨à¯à®´à¯ˆà®µà¯à®•à®³à¯ à®‡à®²à¯à®²à¯ˆ",
    }
)

TRANSLATIONS["hi"].update(
    {
        "Student": "छात्र",
        "Super Admin": "सुपर एडमिन",
        "Logout": "लॉग आउट",
        "Language": "भाषा",
        "Student identity verification access": "छात्र पहचान सत्यापन पहुँच",
        "Administrative access": "प्रशासनिक पहुँच",
        "Super admin control center": "सुपर एडमिन नियंत्रण केंद्र",
        "Admin Login": "एडमिन लॉगिन",
        "Super Admin Login": "सुपर एडमिन लॉगिन",
        "Email": "ईमेल",
        "Password": "पासवर्ड",
        "Forgot password?": "पासवर्ड भूल गए?",
        "Enter student ID": "छात्र आईडी दर्ज करें",
        "Send OTP": "ओटीपी भेजें",
        "Verify OTP": "ओटीपी सत्यापित करें",
        "Resend OTP": "ओटीपी फिर से भेजें",
        "OTP Verification": "ओटीपी सत्यापन",
        "Enter OTP": "ओटीपी दर्ज करें",
        "Identity Verification": "पहचान सत्यापन",
        "Status": "स्थिति",
        "Verification URL": "सत्यापन लिंक",
        "Verification Time": "सत्यापन समय",
        "This identity has been verified by IDENZA.": "यह पहचान IDENZA द्वारा सत्यापित की गई है।",
        "This identity record is currently marked as rejected in IDENZA.": "यह पहचान रिकॉर्ड वर्तमान में IDENZA में अस्वीकृत के रूप में चिह्नित है।",
        "This identity is currently pending confirmation in IDENZA.": "यह पहचान वर्तमान में IDENZA में पुष्टि की प्रतीक्षा में है।",
        "Student identity details for secure verification.": "सुरक्षित सत्यापन के लिए छात्र पहचान विवरण।",
        "Role: School Admin | Scope:": "भूमिका: स्कूल प्रशासक | क्षेत्र:",
        "School Admin only |": "केवल स्कूल प्रशासक |",
        "Date & Time": "तारीख और समय",
        "Name": "नाम",
        "Step 1": "चरण 1",
        "Step 2": "चरण 2",
        "Step 3": "चरण 3",
        "Credentials submitted": "प्रमाण-पत्र जमा किए गए",
        "pradeepa": "Pradeepa",
        "Pradeepa": "Pradeepa",
        "Ravi Kumar": "Ravi Kumar",
        "Priya Devi": "Priya Devi",
        "Arun Raj": "Arun Raj",
        "Meena Lakshmi": "Meena Lakshmi",
        "1 - GHSS - Madurai East": "1 - राजकीय उच्चतर माध्यमिक विद्यालय - मदुरै पूर्व",
        "2 - GHSS - Coimbatore Town": "2 - राजकीय उच्चतर माध्यमिक विद्यालय - कोयंबटूर नगर",
        "3 - GHSS - Salem North": "3 - राजकीय उच्चतर माध्यमिक विद्यालय - सेलम उत्तर",
        "4 - GHSS - Trichy Central": "4 - राजकीय उच्चतर माध्यमिक विद्यालय - तिरुचि केंद्र",
        "GHSS - Madurai East": "राजकीय उच्चतर माध्यमिक विद्यालय - मदुरै पूर्व",
        "GHSS - Coimbatore Town": "राजकीय उच्चतर माध्यमिक विद्यालय - कोयंबटूर नगर",
        "GHSS - Salem North": "राजकीय उच्चतर माध्यमिक विद्यालय - सेलम उत्तर",
        "GHSS - Trichy Central": "राजकीय उच्चतर माध्यमिक विद्यालय - तिरुचि केंद्र",
        "Live class assignment from the student profile.": "छात्र प्रोफ़ाइल से वर्तमान कक्षा आवंटन।",
        "items": "आइटम",
        "No recent uploads yet": "अभी तक कोई हालिया अपलोड नहीं हैं",
        "Your uploaded documents will appear here once they are submitted.": "आपके अपलोड किए गए दस्तावेज़ जमा होने के बाद यहाँ दिखाई देंगे।",
        "Class Group": "कक्षा समूह",
        "Global Status": "वैश्विक स्थिति",
        "Recent Activity": "हाल की गतिविधि",
        "Latest documents uploaded to your profile.": "आपकी प्रोफ़ाइल में हाल ही में अपलोड किए गए दस्तावेज़।",
        "Current Class & Section": "वर्तमान कक्षा और अनुभाग",
        "Current verification cycle used for your ID card.": "आपके आईडी कार्ड के लिए वर्तमान सत्यापन चक्र।",
        "Academic Year": "शैक्षणिक वर्ष",
        "School": "विद्यालय",
        "Learning": "सीखना",
        "Courses": "पाठ्यक्रम",
        "Scholarships": "छात्रवृत्तियाँ",
        "Career": "करियर",
        "Open Portal": "पोर्टल खोलें",
        "DIKSHA": "दीक्षा",
        "SWAYAM": "स्वयं",
        "National Scholarship Portal": "राष्ट्रीय छात्रवृत्ति पोर्टल",
        "National Career Service": "राष्ट्रीय करियर सेवा",
        "National digital infrastructure for school education": "विद्यालय शिक्षा के लिए राष्ट्रीय डिजिटल अवसंरचना",
        "Government online courses and certification platform": "सरकारी ऑनलाइन पाठ्यक्रम और प्रमाणन मंच",
        "Centralized scholarship applications and status tracking": "केंद्रीकृत छात्रवृत्ति आवेदन और स्थिति ट्रैकिंग",
        "Career guidance, skill opportunities, and job search resources": "करियर मार्गदर्शन, कौशल अवसर और नौकरी खोज संसाधन",
        "QR Verification": "क्यूआर सत्यापन",
        "Shareable identity verification details for your school record.": "आपके विद्यालय रिकॉर्ड के लिए साझा करने योग्य पहचान सत्यापन विवरण।",
        "Instant ID Verification": "तत्काल आईडी सत्यापन",
        "Present this secure digital pass for entrance or document verification at campus terminals.": "प्रवेश या दस्तावेज़ सत्यापन के लिए इस सुरक्षित डिजिटल पास को परिसर टर्मिनलों पर प्रस्तुत करें।",
        "Recent logins": "हाल की लॉगिन गतिविधियाँ",
        "Last successful account access records.": "सफल खाते तक पहुँच के हाल के रिकॉर्ड।",
        "No recent logins yet": "अभी तक कोई हाल की लॉगिन गतिविधि नहीं",
        "Welcome!": "स्वागत है!",
        "Explore our features.": "हमारी सुविधाओं का अन्वेषण करें।",
        "Got it": "समझ गया",
        "Reset popup": "पॉपअप रीसेट करें",
        "Close": "बंद करें",
        "Welcome to IDENZA!": "IDENZA में आपका स्वागत है!",
        "Login to continue!": "जारी रखने के लिए लॉगिन करें!",
        "Check your analytics!": "अपना विश्लेषण देखें!",
        "Upload documents to complete verification.": "सत्यापन पूरा करने के लिए दस्तावेज़ अपलोड करें।",
        "Explore useful learning portals.": "उपयोगी शिक्षण पोर्टल देखें।",
        "Keep track of your tasks and deadlines.": "अपने कार्यों और समय-सीमाओं पर नज़र रखें।",
        "Open your digital ID card.": "अपना डिजिटल आईडी कार्ड खोलें।",
        "Sign in to review student records.": "छात्र रिकॉर्ड देखने के लिए साइन इन करें।",
        "Manage students and verification activity.": "छात्रों और सत्यापन गतिविधि का प्रबंधन करें।",
        "Open a student to review documents.": "दस्तावेज़ों की समीक्षा के लिए छात्र खोलें।",
        "Review administrative changes.": "प्रशासनिक परिवर्तनों की समीक्षा करें।",
        "Monitor schools and manage admins.": "स्कूलों की निगरानी करें और एडमिन प्रबंधित करें।",
        "Review the public verification details.": "सार्वजनिक सत्यापन विवरण देखें।",
        "Verification rejected": "सत्यापन अस्वीकृत",
        "Re-upload documents": "दस्तावेज़ फिर से अपलोड करें",
        "Student identity details for secure verification.": "सुरक्षित सत्यापन के लिए छात्र पहचान विवरण।",
        "Dashboard": "डैशबोर्ड",
        "Upload Documents": "दस्तावेज़ अपलोड करें",
        "My Tasks": "मेरे कार्य",
        "Portals": "पोर्टल",
        "Manage Students": "छात्र प्रबंधन",
        "Review Documents": "दस्तावेज़ों की समीक्षा करें",
        "Edit Student": "छात्र संपादित करें",
        "Edit Student Details": "छात्र विवरण संपादित करें",
        "Document Review": "दस्तावेज़ समीक्षा",
        "Approve or reject each uploaded document individually.": "प्रत्येक अपलोड किए गए दस्तावेज़ को अलग-अलग स्वीकृत या अस्वीकृत करें।",
        "View File": "फ़ाइल देखें",
        "Approve": "स्वीकृत करें",
        "Reject": "अस्वीकृत करें",
        "Reason": "कारण",
        "Rejection reason": "अस्वीकृति का कारण",
        "Enter rejection reason": "अस्वीकृति का कारण दर्ज करें",
        "Recent verification scans": "हाल के सत्यापन स्कैन",
        "Last 24 hours QR verification visits for this school.": "इस विद्यालय के पिछले 24 घंटों के क्यूआर सत्यापन विज़िट।",
        "Viewed By": "देखने वाला",
        "Viewer Role": "दर्शक भूमिका",
        "Scanned At": "स्कैन समय",
        "No scans recorded yet.": "अभी तक कोई स्कैन दर्ज नहीं हुआ है।",
        "Student ID": "छात्र आईडी",
        "Student Name": "छात्र का नाम",
        "EMIS ID": "ईएमआईएस आईडी",
        "Class": "कक्षा",
        "Class & Section": "कक्षा और अनुभाग",
        "Parent Mobile": "अभिभावक मोबाइल",
        "Date of Birth": "जन्म तिथि",
        "Actions": "कार्रवाई",
        "Action": "कार्रवाई",
        "Search Students": "छात्र खोजें",
        "Student Directory": "छात्र निर्देशिका",
        "Add Student": "छात्र जोड़ें",
        "Search": "खोजें",
        "Student Name / ID / EMIS / School / Status": "छात्र का नाम / आईडी / ईएमआईएस / विद्यालय / स्थिति",
        "No students found.": "कोई छात्र नहीं मिला।",
        "Student alerts": "छात्र सूचनाएँ",
        "Admin alerts": "एडमिन सूचनाएँ",
        "New document uploaded": "नया दस्तावेज़ अपलोड किया गया",
        "Reviewed and approved by admin.": "एडमिन द्वारा समीक्षा कर स्वीकृत किया गया।",
        "Task overdue": "कार्य देरी से",
        "Document rejected": "दस्तावेज़ अस्वीकृत",
        "Please review the rejection reason and upload a corrected file.": "कृपया अस्वीकृति का कारण देखें और सही फ़ाइल पुनः अपलोड करें।",
        "Rejected documents need correction and re-upload.": "अस्वीकृत दस्तावेज़ों को सुधारकर पुनः अपलोड करना होगा।",
        "View uploads": "अपलोड देखें",
        "No notifications right now.": "फिलहाल कोई सूचना नहीं है।",
        "Change language": "भाषा बदलें",
        "Your session will expire in 2 minutes": "आपका सत्र 2 मिनट में समाप्त हो जाएगा",
        "School Admin Dashboard": "विद्यालय प्रशासक डैशबोर्ड",
        "Super Admin Dashboard": "सुपर एडमिन डैशबोर्ड",
        "School Admin only |": "केवल विद्यालय प्रशासक |",
        "Role: School Admin | Scope:": "भूमिका: विद्यालय प्रशासक | क्षेत्र:",
        "Total Students": "कुल छात्र",
        "Total Schools": "कुल विद्यालय",
        "Top Schools": "शीर्ष विद्यालय",
        "Ranked by student count.": "छात्र संख्या के आधार पर क्रमबद्ध।",
        "Create School Admin": "विद्यालय प्रशासक बनाएँ",
        "Provision a school admin account with direct access to one school.": "किसी एक विद्यालय के लिए सीधे पहुँच वाला विद्यालय प्रशासक खाता बनाएँ।",
        "Create Admin": "प्रशासक बनाएँ",
        "Active and inactive school admin records with direct actions.": "सक्रिय और निष्क्रिय विद्यालय प्रशासक रिकॉर्ड, सीधे कार्यों के साथ।",
        "Deactivate Admin": "प्रशासक निष्क्रिय करें",
        "Activate Admin": "प्रशासक सक्रिय करें",
        "Global overview, school ranking, and admin account management.": "वैश्विक अवलोकन, विद्यालय रैंकिंग, और प्रशासक खाता प्रबंधन।",
        "All student profiles across the platform.": "प्लेटफ़ॉर्म भर के सभी छात्र प्रोफ़ाइल।",
        "School Admin Accounts": "विद्यालय प्रशासक खाते",
        "Schools currently onboarded into the IDENZA network.": "वर्तमान में IDENZA नेटवर्क में शामिल विद्यालय।",
        "Class-wise Distribution": "कक्षा-वार वितरण",
        "All classes from 1-A to 12-B with current student counts.": "1-A से 12-B तक सभी कक्षाएँ वर्तमान छात्र संख्या के साथ।",
        "Last 10 QR verification visits for this school.": "इस विद्यालय के लिए अंतिम 10 क्यूआर सत्यापन विज़िट।",
        "Add Course": "पाठ्यक्रम जोड़ें",
        "Save Academic Data": "शैक्षणिक डेटा सहेजें",
        "Updated profile and set status Pending": "प्रोफ़ाइल अपडेट की गई और स्थिति लंबित सेट की गई",
        "Updated profile and set status Verified": "प्रोफ़ाइल अपडेट की गई और स्थिति सत्यापित सेट की गई",
        "Updated profile and set status Rejected": "प्रोफ़ाइल अपडेट की गई और स्थिति अस्वीकृत सेट की गई",
        "Marked student as verified": "छात्र को सत्यापित चिह्नित किया गया",
        "Marked student as rejected": "छात्र को अस्वीकृत चिह्नित किया गया",
        "Deleted student profile and related records": "छात्र प्रोफ़ाइल और संबंधित रिकॉर्ड हटाए गए",
        "Created student with status Pending": "लंबित स्थिति के साथ छात्र बनाया गया",
        "Created student with status Verified": "सत्यापित स्थिति के साथ छात्र बनाया गया",
        "Created student with status Rejected": "अस्वीकृत स्थिति के साथ छात्र बनाया गया",
        "Verified documents": "सत्यापित दस्तावेज़",
        "No verified documents available.": "कोई सत्यापित दस्तावेज़ उपलब्ध नहीं है।",
        "QR scans": "क्यूआर स्कैन",
        "Verified by": "सत्यापनकर्ता",
        "This verification link has expired. Please request a new one from your school.": "यह सत्यापन लिंक समाप्त हो गया है। कृपया अपने विद्यालय से नया लिंक माँगें।",
        "Student Identity Card": "छात्र पहचान पत्र",
        "Download ID Card": "पहचान पत्र डाउनलोड करें",
        "Refresh QR": "क्यूआर रीफ़्रेश करें",
        "Open QR Details": "क्यूआर विवरण खोलें",
        "Printable ID card styled to match the authenticated design system.": "सत्यापित डिज़ाइन सिस्टम के अनुरूप प्रिंट करने योग्य आईडी कार्ड।",
        "Scan to Verify": "सत्यापन के लिए स्कैन करें",
        "Student Identity": "छात्र पहचान",
        "Expires": "समाप्ति",
        "Digitally generated and secured by IDENZA": "IDENZA द्वारा डिजिटल रूप से निर्मित और सुरक्षित",
        "Issued": "जारी",
        "Open Portal": "पोर्टल खोलें",
        "Dashboard": "डैशबोर्ड",
        "Upload Document": "दस्तावेज़ अपलोड करें",
        "Choose a document type, attach a file, and send it for verification.": "एक दस्तावेज़ प्रकार चुनें, फ़ाइल संलग्न करें, और सत्यापन के लिए भेजें।",
        "Document Types": "दस्तावेज़ प्रकार",
        "Document Type": "दस्तावेज़ प्रकार",
        "Choose File": "फ़ाइल चुनें",
        "Drag & Drop Your Files Here": "अपनी फ़ाइलें यहाँ खींचें और छोड़ें",
        "Or": "या",
        "Browse Files": "फ़ाइलें ब्राउज़ करें",
        "Maximum size: 100MB": "अधिकतम आकार: 100MB",
        "Upload Progress": "अपलोड प्रगति",
        "Uploaded Files": "अपलोड की गई फ़ाइलें",
        "Documents currently stored in your profile.": "आपकी प्रोफ़ाइल में वर्तमान में संग्रहीत दस्तावेज़।",
        "All uploaded student documents displayed in a consistent table format.": "सभी अपलोड किए गए छात्र दस्तावेज़ एक समान तालिका प्रारूप में प्रदर्शित।",
        "File Name": "फ़ाइल नाम",
        "File integrity": "फ़ाइल अखंडता",
        "Tampered": "छेड़छाड़ की गई",
        "Size": "आकार",
        "Uploaded At": "अपलोड समय",
        "Download": "डाउनलोड",
        "Delete": "हटाएँ",
        "Language updated.": "भाषा अपडेट हो गई।",
        "Notification removed.": "सूचना हटा दी गई।",
        "Opening uploads.": "अपलोड पेज खोला जा रहा है।",
        "School admin not found.": "स्कूल एडमिन नहीं मिला।",
        "Confirm Deletion": "हटाने की पुष्टि करें",
        "Are you sure you want to delete this item?": "क्या आप वाकई इस आइटम को हटाना चाहते हैं?",
        "Yes, Delete": "हाँ, हटाएँ",
        "No": "नहीं",
        "No documents uploaded yet.": "अभी तक कोई दस्तावेज़ अपलोड नहीं किया गया है।",
        "ID Card": "आईडी कार्ड",
        "Birth Certificate": "जन्म प्रमाणपत्र",
        "Aadhaar": "आधार",
        "Transfer Certificate": "स्थानांतरण प्रमाणपत्र",
        "Community Certificate": "जाति प्रमाणपत्र",
        "Bank Passbook": "बैंक पासबुक",
        "Medical Fitness Certificate": "चिकित्सीय फिटनेस प्रमाणपत्र",
        "School issued identity card": "विद्यालय द्वारा जारी पहचान पत्र",
        "Proof of date of birth": "जन्म तिथि का प्रमाण",
        "Government identity reference": "सरकारी पहचान संदर्भ",
        "Previous institution transfer proof": "पिछले संस्थान के स्थानांतरण का प्रमाण",
        "Reserved category supporting record": "आरक्षित वर्ग समर्थन रिकॉर्ड",
        "Bank account holder details": "बैंक खाता धारक विवरण",
        "Doctor certified medical fitness proof": "डॉक्टर द्वारा प्रमाणित चिकित्सीय फिटनेस प्रमाण",
        "Unknown Document": "अज्ञात दस्तावेज़",
        "Create Task": "कार्य बनाएँ",
        "Task Description": "कार्य विवरण",
        "Add Task": "कार्य जोड़ें",
        "Deadline is required.": "समय-सीमा आवश्यक है।",
        "Invalid deadline format.": "समय-सीमा का प्रारूप अमान्य है।",
        "Deadline must be in the future.": "समय-सीमा भविष्य की होनी चाहिए।",
        "Due": "देय",
        "Completed": "पूर्ण",
        "Overdue": "समय-सीमा पार",
        "Deadline ended. Please update this task now.": "समय-सीमा समाप्त हो गई है। कृपया इस कार्य को अभी अपडेट करें।",
        "No tasks added yet": "अभी तक कोई कार्य नहीं जोड़ा गया है।",
        "Create your first task to start tracking deadlines.": "समय-सीमा ट्रैक करने के लिए अपना पहला कार्य बनाएँ।",
        "Ready to deploy the project": "प्रोजेक्ट को तैनात करने के लिए तैयार",
        "complete the project and deploy": "प्रोजेक्ट पूरा करें और तैनात करें",
        "complete the project within today": "प्रोजेक्ट आज ही पूरा करें",
        "Complete the project within today": "प्रोजेक्ट आज ही पूरा करें",
        "update project": "प्रोजेक्ट अपडेट करें",
        "Update project": "प्रोजेक्ट अपडेट करें",
        "Update Project": "प्रोजेक्ट अपडेट करें",
        "deploy project": "प्रोजेक्ट डिप्लॉय करें",
        "Deploy project": "प्रोजेक्ट डिप्लॉय करें",
        "Deploy Project": "प्रोजेक्ट डिप्लॉय करें",
        "Pending": "लंबित",
        "Verified": "सत्यापित",
        "Rejected": "अस्वीकृत",
        "Active": "सक्रिय",
        "Inactive": "निष्क्रिय",
        "Forgot Password": "पासवर्ड भूल गए",
        "New Password": "नया पासवर्ड",
        "Confirm Password": "पासवर्ड की पुष्टि करें",
        "Reset Password": "पासवर्ड रीसेट करें",
        "Back to Login": "लॉगिन पर वापस जाएँ",
        "Student password recovery": "छात्र पासवर्ड पुनर्प्राप्ति",
        "School admin password recovery": "स्कूल एडमिन पासवर्ड पुनर्प्राप्ति",
        "Super admin password recovery": "सुपर एडमिन पासवर्ड पुनर्प्राप्ति",
        "Student ID / Username": "छात्र आईडी / उपयोगकर्ता नाम",
        "Student ID / Email": "छात्र आईडी / ईमेल",
        "Admin Email": "एडमिन ईमेल",
        "Super Admin Email": "सुपर एडमिन ईमेल",
        "Enter admin email": "एडमिन ईमेल दर्ज करें",
        "Enter super admin email": "सुपर एडमिन ईमेल दर्ज करें",
        "No OTP found. Please request a new one.": "कोई OTP नहीं मिला। कृपया नया अनुरोध करें।",
        "We sent a 6-digit verification code for your student login.": "आपके छात्र लॉगिन के लिए 6 अंकों का सत्यापन कोड भेजा गया है।",
        "Document approved": "दस्तावेज़ स्वीकृत",
        "Audit Log": "ऑडिट लॉग",
        "Administrative change history for student records.": "छात्र रिकॉर्ड के लिए प्रशासनिक परिवर्तन इतिहास।",
        "Time": "समय",
        "Admin": "प्रशासक",
        "Details": "विवरण",
        "No audit records found.": "कोई ऑडिट रिकॉर्ड नहीं मिला।",
        "Update Student": "छात्र अपडेट करें",
        "Verify": "सत्यापित करें",
        "Add a task title and deadline in the two-column planner below.": "नीचे दिए गए दो-स्तंभ प्लानर में कार्य शीर्षक और समय-सीमा जोड़ें।",
        "Enter new task": "नया कार्य दर्ज करें",
        "Undo task": "कार्य पूर्ववत करें",
        "Mark task done": "कार्य पूर्ण चिह्नित करें",
        "Use the grid below to create a student profile without leaving this page.": "इस पेज को छोड़े बिना छात्र प्रोफ़ाइल बनाने के लिए नीचे दिया गया ग्रिड उपयोग करें।",
        "Filter by Student Name, Student ID, EMIS, School, or Status.": "छात्र नाम, छात्र आईडी, EMIS, विद्यालय या स्थिति से फ़िल्टर करें।",
        "Verified, pending, and rejected student records with edit and delete actions.": "संपादन और हटाने की क्रियाओं के साथ सत्यापित, लंबित और अस्वीकृत छात्र रिकॉर्ड।",
        "Pre-filled student profile form.": "पहले से भरा हुआ छात्र प्रोफ़ाइल फ़ॉर्म।",
        "Update the profile fields while keeping the same verification workflow intact.": "समान सत्यापन प्रक्रिया बनाए रखते हुए प्रोफ़ाइल फ़ील्ड अपडेट करें।",
        "Save Changes": "परिवर्तन सहेजें",
        "Delete this student?": "क्या इस छात्र को हटाना है?",
        "Add Academic Data": "शैक्षणिक डेटा जोड़ें",
        "Academic profile details for the selected student, styled with the same authenticated layout.": "चयनित छात्र के शैक्षणिक प्रोफ़ाइल विवरण, उसी प्रमाणित लेआउट शैली के साथ।",
        "Back to Admin": "एडमिन पर वापस जाएँ",
        "Attendance Percentage": "उपस्थिति प्रतिशत",
        "Enter attendance percentage": "उपस्थिति प्रतिशत दर्ज करें",
        "Current Semester": "वर्तमान सेमेस्टर",
        "Enter current semester": "वर्तमान सेमेस्टर दर्ज करें",
        "Year Of Study": "अध्ययन वर्ष",
        "Enter year": "वर्ष दर्ज करें",
        "Arrear Count": "अरियर संख्या",
        "Enter arrear count": "अरियर संख्या दर्ज करें",
        "Boarding Status": "आवास स्थिति",
        "Hosteller or Day Scholar": "हॉस्टलर या डे स्कॉलर",
        "Warden Name": "वार्डन का नाम",
        "Enter/select warden name": "वार्डन का नाम दर्ज/चयन करें",
        "Enter SGPA": "SGPA दर्ज करें",
        "Enter CGPA": "CGPA दर्ज करें",
        "Course (Course ID - Course Name)": "पाठ्यक्रम (पाठ्यक्रम आईडी - पाठ्यक्रम नाम)",
        "Enter course id - course name": "पाठ्यक्रम आईडी - पाठ्यक्रम नाम दर्ज करें",
        "Remove course": "पाठ्यक्रम हटाएँ",
        "Example: CS101 - Database Management Systems": "उदाहरण: CS101 - डेटाबेस मैनेजमेंट सिस्टम्स",
    }
)


TRANSLATIONS.setdefault("ta", {}).update(
    {
        "Audit Log": "à®†à®¯à¯à®µà¯ à®ªà®¤à®¿à®µà¯",
        "Administrative change history for student records.": "à®®à®¾à®£à®µà®°à¯ à®ªà®¤à®¿à®µà¯à®•à®³à®¿à®²à¯ à®¨à®¿à®°à¯à®µà®¾à®• à®®à®¾à®±à¯à®±à®™à¯à®•à®³à®¿à®©à¯ à®µà®°à®²à®¾à®±à¯.",
        "Time": "à®¨à¯‡à®°à®®à¯",
        "Admin": "à®¨à®¿à®°à¯à®µà®¾à®•à®¿",
        "Details": "à®µà®¿à®µà®°à®™à¯à®•à®³à¯",
        "No audit records found.": "à®†à®¯à¯à®µà¯ à®ªà®¤à®¿à®µà¯à®•à®³à¯ à®Žà®¤à¯à®µà¯à®®à¯ à®•à®¿à®Ÿà¯ˆà®•à¯à®•à®µà®¿à®²à¯à®²à¯ˆ.",
        "Update Student": "à®®à®¾à®£à®µà®°à¯ˆ à®ªà¯à®¤à¯à®ªà¯à®ªà®¿",
        "Review Documents": "à®†à®µà®£à®™à¯à®•à®³à¯ˆà®ªà¯ à®ªà®°à®¿à®šà¯€à®²à®¿",
        "Change language": "à®®à¯Šà®´à®¿à®¯à¯ˆ à®®à®¾à®±à¯à®±à¯",
        "Approve or reject each uploaded document individually.": "à®ªà®¤à®¿à®µà¯‡à®±à¯à®±à®ªà¯à®ªà®Ÿà¯à®Ÿ à®’à®µà¯à®µà¯Šà®°à¯ à®†à®µà®£à®¤à¯à®¤à¯ˆà®¯à¯à®®à¯ à®¤à®©à®¿à®¤à¯à®¤à®©à®¿à®¯à®¾à®• à®à®±à¯à®•à®µà¯à®®à¯ à®…à®²à¯à®²à®¤à¯ à®¨à®¿à®°à®¾à®•à®°à®¿à®•à¯à®•à®µà¯à®®à¯.",
        "View File": "à®•à¯‹à®ªà¯à®ªà¯ˆà®ªà¯ à®ªà®¾à®°à¯",
    }
)

TRANSLATIONS.setdefault("ta", {}).update(
    {
        "Choose a document type, attach a file, and send it for verification.": "à®’à®°à¯ à®†à®µà®£ à®µà®•à¯ˆà®¯à¯ˆà®¤à¯ à®¤à¯‡à®°à¯à®¨à¯à®¤à¯†à®Ÿà¯à®¤à¯à®¤à¯, à®•à¯‹à®ªà¯à®ªà¯ˆ à®‡à®£à¯ˆà®¤à¯à®¤à¯, à®šà®°à®¿à®ªà®¾à®°à¯à®ªà¯à®ªà®¿à®±à¯à®•à®¾à®• à®…à®©à¯à®ªà¯à®ªà®µà¯à®®à¯.",
        "Proof of date of birth": "à®ªà®¿à®±à®¨à¯à®¤ à®¤à¯‡à®¤à®¿ à®šà®¾à®©à¯à®±à¯",
        "Government identity reference": "à®…à®°à®šà¯ à®…à®Ÿà¯ˆà®¯à®¾à®³à®•à¯ à®•à¯à®±à®¿à®ªà¯à®ªà¯",
        "Previous institution transfer proof": "à®®à¯à®©à¯à®©à¯ˆà®¯ à®•à®²à¯à®µà®¿ à®¨à®¿à®±à¯à®µà®© à®®à®¾à®±à¯à®±à¯à®šà¯ à®šà®¾à®©à¯à®±à¯",
        "Reserved category supporting record": "à®’à®¤à¯à®•à¯à®•à®ªà¯à®ªà®Ÿà¯à®Ÿ à®ªà®¿à®°à®¿à®µà¯à®•à¯à®•à®¾à®© à®†à®¤à®¾à®°à®ªà¯ à®ªà®¤à®¿à®µà¯",
        "Bank account holder details": "à®µà®™à¯à®•à®¿ à®•à®£à®•à¯à®•à¯ à®µà¯ˆà®¤à¯à®¤à®¿à®°à¯à®ªà¯à®ªà®µà®°à®¿à®©à¯ à®µà®¿à®µà®°à®™à¯à®•à®³à¯",
        "Choose File": "à®•à¯‹à®ªà¯à®ªà¯ˆà®¤à¯ à®¤à¯‡à®°à¯à®¨à¯à®¤à¯†à®Ÿà¯à®•à¯à®•à®µà¯à®®à¯",
        "Drag & Drop Your Files Here": "à®‰à®™à¯à®•à®³à¯ à®•à¯‹à®ªà¯à®ªà¯à®•à®³à¯ˆ à®‡à®™à¯à®•à¯‡ à®‡à®´à¯à®¤à¯à®¤à¯ à®µà®¿à®Ÿà®µà¯à®®à¯",
        "Or": "à®…à®²à¯à®²à®¤à¯",
        "Browse Files": "à®•à¯‹à®ªà¯à®ªà¯à®•à®³à¯ˆ à®‰à®²à®¾à®µà¯à®•",
        "Maximum size: 100MB": "à®…à®¤à®¿à®•à®ªà®Ÿà¯à®š à®…à®³à®µà¯: 100MB",
        "Upload Progress": "à®ªà®¤à®¿à®µà¯‡à®±à¯à®± à®®à¯à®©à¯à®©à¯‡à®±à¯à®±à®®à¯",
        "Documents currently stored in your profile.": "à®‰à®™à¯à®•à®³à¯ à®šà¯à®¯à®µà®¿à®µà®°à®¤à¯à®¤à®¿à®²à¯ à®¤à®±à¯à®ªà¯‹à®¤à¯ à®šà¯‡à®®à®¿à®•à¯à®•à®ªà¯à®ªà®Ÿà¯à®Ÿà¯à®³à¯à®³ à®†à®µà®£à®™à¯à®•à®³à¯.",
        "All uploaded student documents displayed in a consistent table format.": "à®ªà®¤à®¿à®µà¯‡à®±à¯à®±à®ªà¯à®ªà®Ÿà¯à®Ÿ à®…à®©à¯ˆà®¤à¯à®¤à¯ à®®à®¾à®£à®µà®°à¯ à®†à®µà®£à®™à¯à®•à®³à¯à®®à¯ à®’à®°à¯‡ à®®à®¾à®¤à®¿à®°à®¿à®¯à®¾à®© à®…à®Ÿà¯à®Ÿà®µà®£à¯ˆ à®µà®Ÿà®¿à®µà®¿à®²à¯ à®•à®¾à®Ÿà¯à®Ÿà®ªà¯à®ªà®Ÿà¯à®®à¯.",
        "Size": "à®…à®³à®µà¯",
        "No documents uploaded yet.": "à®‡à®©à¯à®©à¯à®®à¯ à®Žà®¨à¯à®¤ à®†à®µà®£à®®à¯à®®à¯ à®ªà®¤à®¿à®µà¯‡à®±à¯à®±à®ªà¯à®ªà®Ÿà®µà®¿à®²à¯à®²à¯ˆ.",
    }
)

LANGUAGE_OPTIONS = repair_mojibake_structure(LANGUAGE_OPTIONS)
TAMIL_SECTION_MAP = repair_mojibake_structure(TAMIL_SECTION_MAP)
TAMIL_NAME_OVERRIDES = repair_mojibake_structure(TAMIL_NAME_OVERRIDES)
TAMIL_NAME_TOKEN_OVERRIDES = repair_mojibake_structure(TAMIL_NAME_TOKEN_OVERRIDES)
TAMIL_VOWEL_SIGNS = repair_mojibake_structure(TAMIL_VOWEL_SIGNS)
TAMIL_INDEPENDENT_VOWELS = repair_mojibake_structure(TAMIL_INDEPENDENT_VOWELS)
TAMIL_CONSONANTS = repair_mojibake_structure(TAMIL_CONSONANTS)
TAMIL_DIGRAPHS = repair_mojibake_structure(TAMIL_DIGRAPHS)
TRANSLATIONS = repair_mojibake_structure(TRANSLATIONS)

TAMIL_NAME_OVERRIDES.update(
    {
        "loganadhan": "லோகநாதன்",
        "mani": "மணி",
        "bharani": "பரணி",
        "anbarasu": "அன்பரசு",
        "kaviya": "காவியா",
        "kavipriya": "கவிப்பிரியா",
        "kaviyapriya": "கவிப்பிரியா",
        "selvi": "செல்வி",
        "kaviyarasu": "கவியரசு",
        "manikandan": "மணிகண்டன்",
        "manimaran": "மணிமாறன்",
        "ravi": "ரவி",
        "priya": "பிரியா",
        "arun": "அருண்",
        "meena": "மீனா",
        "lakshmi": "லட்சுமி",
        "pradeepa": "பிரதீபா",
        "praveen r": "பிரவீன் ஆர்",
        "pari": "பாரி",
        "paari": "பாரி",
        "ravi kumar": "ரவி குமார்",
        "divyavarshini r": "திவ்யவர்ஷிணி ஆர்",
        "priya devi": "பிரியா தேவி",
        "arun raj": "அருண் ராஜ்",
        "meena lakshmi": "மீனா லட்சுமி",
        "kaviya devi": "காவியா தேவி",
        "kaviya rajan": "காவியா ராஜன்",
        "kaviya babu": "காவியா பாபு",
        "selvi babu": "செல்வி பாபு",
        "selvi rajan": "செல்வி ராஜன்",
        "selvi pandian": "செல்வி பாண்டியன்",
        "anbarasu rajan": "அன்பரசு ராஜன்",
        "mani babu": "மணி பாபு",
        "ravi mani": "ரவி மணி",
        "udayakumar": "உதயகுமார்",
        "udhayakumar": "உதயகுமார்",
        "udaya kumar": "உதய குமார்",
        "udhay kumar": "உதய குமார்",
        "uday kumar": "உதய் குமார்",
        "tamilarasi": "தமிழரசி",
        "selvamurugan": "செல்வமுருகன்",
        "suganya": "சுகன்யா",
        "vibishika": "விபிஷிகா",
        "viyanka": "வியங்கா",
        "valli": "வள்ளி",
        "selvi arasu": "செல்வி அரசு",
        "selvi babu": "செல்வி பாபு",
        "selvi devi": "செல்வி தேவி",
        "selvi mani": "செல்வி மணி",
        "selvi murugan": "செல்வி முருகன்",
        "selvi pandian": "செல்வி பாண்டியன்",
        "selvi rajan": "செல்வி ராஜன்",
        "selvi selvam": "செல்வி செல்வம்",
        "selvi vel": "செல்வி வேல்",
    }
)

TAMIL_NAME_TOKEN_OVERRIDES.update(
    {
        "udaya": "உதய",
        "udhay": "உதய",
        "uday": "உதய்",
        "udayakumar": "உதயகுமார்",
        "udhayakumar": "உதயகுமார்",
        "tamilarasi": "தமிழரசி",
        "selvamurugan": "செல்வமுருகன்",
        "suganya": "சுகன்யா",
        "vibishika": "விபிஷிகா",
        "viyanka": "வியங்கா",
        "valli": "வள்ளி",
        "selvi": "செல்வி",
        "selvam": "செல்வம்",
        "selvan": "செல்வன்",
    }
)

HI_NAME_OVERRIDES = {
    "pradeepa": "प्रदीपा",
    "ravi kumar": "रवि कुमार",
    "priya devi": "प्रिया देवी",
    "arun raj": "अरुण राज",
    "meena lakshmi": "मीना लक्ष्मी",
    "loganadhan": "लोकनाथन",
    "mani": "मणि",
    "bharani": "भरानी",
    "anbarasu": "अनबरसू",
    "kaviya": "काविया",
    "kavipriya": "कविप्रिया",
    "kaviyapriya": "कविप्रिया",
    "selvi": "सेल्वी",
    "kaviyarasu": "कावियरसु",
    "manikandan": "मणिकंदन",
    "manimaran": "मणिमारन",
    "ravi": "रवि",
    "priya": "प्रिया",
    "arun": "अरुण",
    "meena": "मीना",
    "lakshmi": "लक्ष्मी",
    "pari": "पारी",
    "paari": "पारी",
    "kanaga": "कनगा",
    "sandhiya": "संधिया",
    "praveen": "प्रवीन",
    "iniya": "इनिया",
    "iniya rajan": "इनिया राजन",
    "dhanalakshmi": "धनलक्ष्मी",
    "navanidhan": "नवनिधन",
}

HI_NAME_TOKEN_OVERRIDES = {
    "ravi": "रवि",
    "kumar": "कुमार",
    "priya": "प्रिया",
    "devi": "देवी",
    "arun": "अरुण",
    "raj": "राज",
    "meena": "मीना",
    "lakshmi": "लक्ष्मी",
    "kanaga": "कनगा",
    "sandhiya": "संधिया",
    "praveen": "प्रवीन",
    "iniya": "इनिया",
    "rajan": "राजन",
    "dhanalakshmi": "धनलक्ष्मी",
    "navanidhan": "नवनिधन",
}

TA_TASK_TOKEN_OVERRIDES = {
    "update": "புதுப்பி",
    "deploy": "வெளியிடு",
    "project": "திட்டம்",
    "task": "பணி",
    "tasks": "பணிகள்",
    "complete": "முடிக்க",
    "completed": "முடிந்தது",
    "pending": "நிலுவையில்",
    "today": "இன்று",
    "tomorrow": "நாளை",
    "verify": "சரிபார்",
    "upload": "பதிவேற்று",
    "document": "ஆவணம்",
    "documents": "ஆவணங்கள்",
    "review": "பரிசீலனை",
    "new": "புதிய",
}

HI_TASK_TOKEN_OVERRIDES = {
    "update": "अपडेट",
    "deploy": "डिप्लॉय",
    "project": "प्रोजेक्ट",
    "task": "कार्य",
    "tasks": "कार्य",
    "complete": "पूरा",
    "completed": "पूर्ण",
    "pending": "लंबित",
    "today": "आज",
    "tomorrow": "कल",
    "verify": "सत्यापित",
    "upload": "अपलोड",
    "document": "दस्तावेज़",
    "documents": "दस्तावेज़",
    "review": "समीक्षा",
    "new": "नया",
}

TRANSLATIONS.setdefault("ta", {})
TRANSLATIONS["ta"].update(
    {
        "Dashboard": "டாஷ்போர்டு",
        "Upload Documents": "ஆவணங்களை பதிவேற்று",
        "My Tasks": "என் பணிகள்",
        "Portals": "தளங்கள்",
        "Manage Students": "மாணவர் மேலாண்மை",
        "School Admin Dashboard": "பள்ளி நிர்வாகி டாஷ்போர்டு",
        "Secure student verification": "பாதுகாப்பான மாணவர் சரிபார்ப்பு",
        "Notifications": "அறிவிப்புகள்",
        "Overdue tasks": "தாமதமான பணிகள்",
        "Student alerts": "மாணவர் அறிவிப்புகள்",
        "Admin alerts": "நிர்வாகி அறிவிப்புகள்",
        "New document uploaded": "புதிய ஆவணம் பதிவேற்றப்பட்டது",
        "Reviewed and approved by admin.": "நிர்வாகியால் பரிசீலித்து ஏற்கப்பட்டது.",
        "Task overdue": "பணி காலாவதியானது",
        "No notifications right now.": "இப்போது அறிவிப்புகள் இல்லை.",
        "Student": "மாணவர்",
        "Super Admin": "சூப்பர் அட்மின்",
        "Logout": "வெளியேறு",
        "Language": "மொழி",
        "Change language": "மொழியை மாற்று",
        "Your session will expire in 2 minutes": "உங்கள் அமர்வு 2 நிமிடங்களில் முடிவடையும்",
        "Student identity verification access": "மாணவர் அடையாள சரிபார்ப்பு அணுகல்",
        "Administrative access": "நிர்வாக அணுகல்",
        "Super admin control center": "சூப்பர் அட்மின் கட்டுப்பாட்டு மையம்",
        "Admin Login": "அட்மின் உள்நுழைவு",
        "Super Admin Login": "சூப்பர் அட்மின் உள்நுழைவு",
        "Email": "மின்னஞ்சல்",
        "Password": "கடவுச்சொல்",
        "Step 1": "படி 1",
        "Step 2": "படி 2",
        "Step 3": "படி 3",
        "Credentials submitted": "சான்றுகள் சமர்ப்பிக்கப்பட்டன",
        "OTP Verification": "ஓடிபி சரிபார்ப்பு",
        "Enter OTP": "ஓடிபி உள்ளிடவும்",
        "Verify OTP": "ஓடிபி சரிபார்",
        "Send OTP": "ஓடிபி அனுப்பு",
        "Resend OTP": "ஓடிபி மீண்டும் அனுப்பு",
        "Forgot password?": "கடவுச்சொல் மறந்துவிட்டதா?",
        "Student ID": "மாணவர் ஐடி",
        "Enter student ID": "மாணவர் ஐடியை உள்ளிடவும்",
        "Identity Verification": "அடையாள சரிபார்ப்பு",
        "Status": "நிலை",
        "Academic Year": "கல்வியாண்டு",
        "Verification URL": "சரிபார்ப்பு இணைப்பு",
        "Verification Time": "சரிபார்ப்பு நேரம்",
        "Verification rejected": "சரிபார்ப்பு நிராகரிக்கப்பட்டது",
        "Re-upload documents": "ஆவணங்களை மீண்டும் பதிவேற்று",
        "Recent Activity": "சமீபத்திய செயல்பாடு",
        "Latest documents uploaded to your profile.": "உங்கள் சுயவிவரத்தில் சமீபத்தில் பதிவேற்றப்பட்ட ஆவணங்கள்.",
        "QR Verification": "QR சரிபார்ப்பு",
        "Recent logins": "சமீபத்திய உள்நுழைவுகள்",
        "Last successful account access records.": "கடைசியாக வெற்றிகரமாக நடந்த கணக்கு அணுகல் பதிவுகள்.",
        "No recent logins yet": "இன்னும் சமீபத்திய உள்நுழைவுகள் இல்லை",
        "Welcome!": "வரவேற்கிறோம்!",
        "Explore our features.": "எங்கள் அம்சங்களை ஆராயுங்கள்.",
        "Got it": "சரி",
        "Reset popup": "பாப்அப்பை மீட்டமை",
        "Close": "மூடு",
        "Welcome to IDENZA!": "IDENZA-க்கு வரவேற்கிறோம்!",
        "Login to continue!": "தொடர உள்நுழையவும்!",
        "Check your analytics!": "உங்கள் பகுப்பாய்வை பார்க்கவும்!",
        "Upload documents to complete verification.": "சரிபார்ப்பை முடிக்க ஆவணங்களை பதிவேற்றவும்.",
        "Explore useful learning portals.": "பயனுள்ள கற்றல் போர்டல்களை ஆராயுங்கள்.",
        "Keep track of your tasks and deadlines.": "உங்கள் பணிகள் மற்றும் கடைசி தேதிகளை கண்காணிக்கவும்.",
        "Open your digital ID card.": "உங்கள் டிஜிட்டல் ஐடி அட்டையைத் திறக்கவும்.",
        "Sign in to review student records.": "மாணவர் பதிவுகளைப் பார்க்க உள்நுழையவும்.",
        "Manage students and verification activity.": "மாணவர்களையும் சரிபார்ப்பு செயல்பாடுகளையும் நிர்வகிக்கவும்.",
        "Open a student to review documents.": "ஆவணங்களைப் பார்க்க ஒரு மாணவரைத் திறக்கவும்.",
        "Review administrative changes.": "நிர்வாக மாற்றங்களைப் பார்வையிடவும்.",
        "Monitor schools and manage admins.": "பள்ளிகளை கண்காணித்து நிர்வாகிகளை நிர்வகிக்கவும்.",
        "Review the public verification details.": "பொது சரிபார்ப்பு விவரங்களைப் பார்க்கவும்.",
        "Date & Time": "தேதி மற்றும் நேரம்",
        "Current Class & Section": "தற்போதைய வகுப்பு",
        "School": "பள்ளி",
        "Class Group": "வகுப்பு பிரிவு",
        "Global Status": "மொத்த நிலை",
        "items": "உருப்படிகள்",
        "No recent uploads yet": "இன்னும் சமீபத்திய பதிவேற்றங்கள் இல்லை",
        "Your uploaded documents will appear here once they are submitted.": "நீங்கள் பதிவேற்றிய ஆவணங்கள் சமர்ப்பிக்கப்பட்டதும் இங்கே தோன்றும்.",
        "Live class assignment from the student profile.": "மாணவர் சுயவிவரத்தில் உள்ள தற்போதைய வகுப்பு விவரம்.",
        "Current verification cycle used for your ID card.": "உங்கள் அடையாள அட்டைக்கான தற்போதைய சரிபார்ப்பு சுற்று.",
        "Instant ID Verification": "உடனடி அடையாள சரிபார்ப்பு",
        "Present this secure digital pass for entrance or document verification at campus terminals.": "வளாக நுழைவு அல்லது ஆவண சரிபார்ப்பிற்காக இந்த பாதுகாப்பான டிஜிட்டல் அடையாளத்தை பயன்படுத்தவும்.",
        "New login location detected": "புதிய உள்நுழைவு இடம் கண்டறியப்பட்டது",
        "This identity has been verified by IDENZA.": "இந்த அடையாளம் IDENZA மூலம் சரிபார்க்கப்பட்டது.",
        "This identity record is currently marked as rejected in IDENZA.": "இந்த அடையாள பதிவு தற்போது IDENZA-வில் நிராகரிக்கப்பட்டதாக குறிக்கப்பட்டுள்ளது.",
        "This identity is currently pending confirmation in IDENZA.": "இந்த அடையாளம் தற்போது IDENZA-வில் உறுதிப்படுத்தப்படாமல் நிலுவையில் உள்ளது.",
        "Student identity details for secure verification.": "பாதுகாப்பான சரிபார்ப்பிற்கான மாணவர் அடையாள விவரங்கள்.",
        "Verified documents": "சரிபார்க்கப்பட்ட ஆவணங்கள்",
        "No verified documents available.": "சரிபார்க்கப்பட்ட ஆவணங்கள் இல்லை.",
        "QR scans": "QR ஸ்கான்கள்",
        "Verified by": "சரிபார்த்தவர்",
        "This verification link has expired. Please request a new one from your school.": "இந்த சரிபார்ப்பு இணைப்பு காலாவதியானது. உங்கள் பள்ளியிலிருந்து புதிய இணைப்பை கோரவும்.",
        "Recent verification scans": "சமீபத்திய சரிபார்ப்பு ஸ்கான்கள்",
        "Last 24 hours QR verification visits for this school.": "இந்த பள்ளிக்கான கடைசி 24 மணி நேர QR சரிபார்ப்பு பார்வைகள்.",
        "Viewed By": "பார்த்தவர்",
        "Viewer Role": "பார்வையாளர் பங்கு",
        "Scanned At": "ஸ்கேன் செய்யப்பட்ட நேரம்",
        "No scans recorded yet.": "இன்னும் ஸ்கான் பதிவுகள் இல்லை.",
        "All classes from 1-A to 12-B with current student counts.": "1-A முதல் 12-B வரை உள்ள அனைத்து வகுப்புகளும் தற்போதைய மாணவர் எண்ணிக்கையுடன்.",
        "Last 10 QR verification visits for this school.": "இந்த பள்ளிக்கான கடைசி 10 QR சரிபார்ப்பு பார்வைகள்.",
        "Audit Log": "தணிக்கை பதிவு",
        "Administrative change history for student records.": "மாணவர் பதிவுகளுக்கான நிர்வாக மாற்ற வரலாறு.",
        "Time": "நேரம்",
        "Admin": "நிர்வாகி",
        "Details": "விவரங்கள்",
        "No audit records found.": "தணிக்கை பதிவுகள் எதுவும் இல்லை.",
        "Review Documents": "ஆவணங்களை பரிசீலிக்க",
        "Update Student": "மாணவரை புதுப்பி",
        "Verify": "சரிபார்",
        "Edit Student": "மாணவரை திருத்து",
        "Edit Student Details": "மாணவர் விவரங்களை திருத்து",
        "Approve or reject each uploaded document individually.": "பதிவேற்றப்பட்ட ஒவ்வொரு ஆவணத்தையும் தனித்தனியாக ஏற்கவும் அல்லது நிராகரிக்கவும்.",
        "Document Review": "ஆவண பரிசீலனை",
        "View File": "கோப்பைப் பார்",
        "Approve": "ஏற்கவும்",
        "Reject": "நிராகரி",
        "Reason": "காரணம்",
        "Rejection reason": "நிராகரிப்பு காரணம்",
        "Enter rejection reason": "நிராகரிப்பு காரணத்தை உள்ளிடவும்",
        "Search Students": "மாணவர்களை தேடு",
        "Student Directory": "மாணவர் பட்டியல்",
        "Student Name": "மாணவர் பெயர்",
        "EMIS ID": "EMIS ஐடி",
        "Class": "வகுப்பு",
        "Class & Section": "வகுப்பு மற்றும் பிரிவு",
        "Parent Mobile": "பெற்றோர் கைபேசி",
        "Date of Birth": "பிறந்த தேதி",
        "Actions": "செயல்கள்",
        "Action": "செயல்",
        "Search": "தேடு",
        "Student Name / ID / EMIS / School / Status": "மாணவர் பெயர் / ஐடி / EMIS / பள்ளி / நிலை",
        "Add Student": "மாணவரை சேர்",
        "Add Course": "பாடத்தை சேர்",
        "No students found.": "மாணவர்கள் எவரும் கிடைக்கவில்லை.",
        "Name": "பெயர்",
        "Role: School Admin | Scope:": "பங்கு: பள்ளி நிர்வாகி | வரம்பு:",
        "School Admin only |": "பள்ளி நிர்வாகிக்கு மட்டும் |",
        "Total Students": "மொத்த மாணவர்கள்",
        "Total Schools": "மொத்த பள்ளிகள்",
        "Top Schools": "சிறந்த பள்ளிகள்",
        "Ranked by student count.": "மாணவர் எண்ணிக்கையின் அடிப்படையில் தரவரிசை.",
        "Create School Admin": "பள்ளி நிர்வாகியை உருவாக்கு",
        "Provision a school admin account with direct access to one school.": "ஒரு பள்ளிக்கான நேரடி அணுகலுடன் பள்ளி நிர்வாகி கணக்கை உருவாக்கவும்.",
        "Create Admin": "நிர்வாகியை உருவாக்கு",
        "Active and inactive school admin records with direct actions.": "செயலில் உள்ள மற்றும் செயலற்ற பள்ளி நிர்வாகி பதிவுகள், நேரடி செயல்களுடன்.",
        "Deactivate Admin": "நிர்வாகியை செயலிழக்கு",
        "Activate Admin": "நிர்வாகியை செயல்படுத்து",
        "Global overview, school ranking, and admin account management.": "உலகளாவிய பார்வை, பள்ளி தரவரிசை, மற்றும் நிர்வாகி கணக்கு மேலாண்மை.",
        "All student profiles across the platform.": "தளமெங்கும் உள்ள அனைத்து மாணவர் சுயவிவரங்களும்.",
        "Class-wise Distribution": "வகுப்பு வாரியான பகிர்வு",
        "School Admin Accounts": "பள்ளி நிர்வாகி கணக்குகள்",
        "Schools currently onboarded into the IDENZA network.": "தற்போது IDENZA வலையமைப்பில் இணைக்கப்பட்டுள்ள பள்ளிகள்.",
        "Learning": "கற்றல்",
        "Courses": "பாடத்திட்டங்கள்",
        "Scholarships": "உதவித்தொகைகள்",
        "Career": "தொழில்",
        "DIKSHA": "தீக்ஷா",
        "SWAYAM": "ஸ்வயம்",
        "National Scholarship Portal": "தேசிய உதவித்தொகை தளம்",
        "National Career Service": "தேசிய தொழில் சேவை",
        "National digital infrastructure for school education": "பள்ளி கல்விக்கான தேசிய டிஜிட்டல் அமைப்பு",
        "Government online courses and certification platform": "அரசு ஆன்லைன் பாடங்கள் மற்றும் சான்றிதழ் தளம்",
        "Centralized scholarship applications and status tracking": "மையப்படுத்தப்பட்ட உதவித்தொகை விண்ணப்பங்கள் மற்றும் நிலை கண்காணிப்பு",
        "Career guidance, skill opportunities, and job search resources": "தொழில் வழிகாட்டல், திறன் வாய்ப்புகள், மற்றும் வேலைதேடல் ஆதாரங்கள்",
        "Open Portal": "தளத்தை திற",
        "Upload Document": "ஆவணத்தை பதிவேற்று",
        "Choose a document type, attach a file, and send it for verification.": "ஒரு ஆவண வகையைத் தேர்ந்தெடுத்து, கோப்பை இணைத்து, சரிபார்ப்பிற்காக அனுப்பவும்.",
        "Shareable identity verification details for your school record.": "உங்கள் பள்ளி பதிவுக்காக பகிரக்கூடிய அடையாள சரிபார்ப்பு விவரங்கள்.",
        "Document Types": "ஆவண வகைகள்",
        "Document Type": "ஆவண வகை",
        "Choose File": "கோப்பை தேர்ந்தெடுக்கவும்",
        "Drag & Drop Your Files Here": "உங்கள் கோப்புகளை இங்கே இழுத்து விடவும்",
        "Or": "அல்லது",
        "Browse Files": "கோப்புகளை உலாவு",
        "Maximum size: 100MB": "அதிகபட்ச அளவு: 100MB",
        "Upload Progress": "பதிவேற்ற முன்னேற்றம்",
        "Uploaded Files": "பதிவேற்றப்பட்ட கோப்புகள்",
        "Documents currently stored in your profile.": "உங்கள் சுயவிவரத்தில் தற்போது சேமிக்கப்பட்டுள்ள ஆவணங்கள்.",
        "All uploaded student documents displayed in a consistent table format.": "பதிவேற்றப்பட்ட அனைத்து மாணவர் ஆவணங்களும் ஒரே மாதிரியான அட்டவணை வடிவில் காட்டப்படும்.",
        "File Name": "கோப்பு பெயர்",
        "File integrity": "கோப்பு ஒருமைத்தன்மை",
        "Tampered": "மாற்றப்பட்டுள்ளது",
        "Size": "அளவு",
        "Uploaded At": "பதிவேற்றப்பட்ட நேரம்",
        "Download": "பதிவிறக்கு",
        "Delete": "நீக்கு",
        "Language updated.": "மொழி புதுப்பிக்கப்பட்டது.",
        "Notification removed.": "அறிவிப்பு நீக்கப்பட்டது.",
        "Opening uploads.": "பதிவேற்றப் பக்கம் திறக்கப்படுகிறது.",
        "School admin not found.": "பள்ளி நிர்வாகி கிடைக்கவில்லை.",
        "Confirm Deletion": "நீக்கலை உறுதிசெய்",
        "Are you sure you want to delete this item?": "இந்த உருப்படியை நிச்சயமாக நீக்க வேண்டுமா?",
        "Yes, Delete": "ஆம், நீக்கு",
        "No": "இல்லை",
        "No documents uploaded yet.": "இன்னும் எந்த ஆவணமும் பதிவேற்றப்படவில்லை.",
        "Document rejected": "ஆவணம் நிராகரிக்கப்பட்டது",
        "Document approved": "ஆவணம் ஏற்கப்பட்டது",
        "Please review the rejection reason and upload a corrected file.": "நிராகரிப்பு காரணத்தை பார்த்து சரியான கோப்பை மீண்டும் பதிவேற்றவும்.",
        "Rejected documents need correction and re-upload.": "நிராகரிக்கப்பட்ட ஆவணங்கள் திருத்தப்பட்டு மீண்டும் பதிவேற்றப்பட வேண்டும்.",
        "View uploads": "பதிவேற்றங்களை பார்",
        "ID Card": "அடையாள அட்டை",
        "Birth Certificate": "பிறப்பு சான்றிதழ்",
        "Aadhaar": "ஆதார்",
        "Transfer Certificate": "மாற்றுச் சான்றிதழ்",
        "Community Certificate": "சமூகச் சான்றிதழ்",
        "Bank Passbook": "வங்கி பாஸ்புக்",
        "Medical Fitness Certificate": "மருத்துவ தகுதிச் சான்றிதழ்",
        "School issued identity card": "பள்ளி வழங்கிய அடையாள அட்டை",
        "Proof of date of birth": "பிறந்த தேதிக்கான சான்று",
        "Government identity reference": "அரசு அடையாளக் குறிப்பு",
        "Previous institution transfer proof": "முந்தைய கல்வி நிறுவனம் மாற்றுச் சான்று",
        "Reserved category supporting record": "ஒதுக்கப்பட்ட பிரிவுக்கான ஆதார பதிவு",
        "Bank account holder details": "வங்கி கணக்கு வைத்திருப்பவரின் விவரங்கள்",
        "Doctor certified medical fitness proof": "மருத்துவர் சான்றளித்த மருத்துவ தகுதி ஆதாரம்",
        "Unknown Document": "அறியப்படாத ஆவணம்",
        "Create Task": "பணி உருவாக்கு",
        "Task Description": "பணி விளக்கம்",
        "Add Task": "பணியை சேர்",
        "Deadline is required.": "காலக்கெடு அவசியம்.",
        "Invalid deadline format.": "காலக்கெடு வடிவம் தவறானது.",
        "Deadline must be in the future.": "காலக்கெடு எதிர்கால நேரமாக இருக்க வேண்டும்.",
        "Due": "கடைசி தேதி",
        "Completed": "முடிந்தது",
        "Overdue": "காலாவதியானது",
        "Deadline ended. Please update this task now.": "காலக்கெடு முடிந்துவிட்டது. இந்த பணியை இப்போது புதுப்பிக்கவும்.",
        "No tasks added yet": "இன்னும் பணிகள் சேர்க்கப்படவில்லை.",
        "Create your first task to start tracking deadlines.": "காலக்கெடுகளை கண்காணிக்க உங்கள் முதல் பணியை உருவாக்கவும்.",
        "Ready to deploy the project": "திட்டத்தை வெளியிட தயாராக உள்ளது",
        "complete the project and deploy": "திட்டத்தை முடித்து வெளியிடவும்",
        "complete the project within today": "திட்டத்தை இன்றே முடிக்கவும்",
        "Complete the project within today": "திட்டத்தை இன்றே முடிக்கவும்",
        "update project": "திட்டத்தை புதுப்பி",
        "Update project": "திட்டத்தை புதுப்பி",
        "Update Project": "திட்டத்தை புதுப்பி",
        "deploy project": "திட்டத்தை வெளியிடு",
        "Deploy project": "திட்டத்தை வெளியிடு",
        "Deploy Project": "திட்டத்தை வெளியிடு",
        "Pending": "நிலுவையில்",
        "Verified": "சரிபார்க்கப்பட்டது",
        "Rejected": "நிராகரிக்கப்பட்டது",
        "Active": "செயலில்",
        "Inactive": "செயலற்றது",
        "Student Identity Card": "மாணவர் அடையாள அட்டை",
        "Download ID Card": "அடையாள அட்டையை பதிவிறக்கு",
        "Refresh QR": "QR-ஐ புதுப்பி",
        "Open QR Details": "QR விவரங்களை திற",
        "Printable ID card styled to match the authenticated design system.": "உள்நுழைந்த வடிவமைப்புடன் பொருந்தும் வகையில் அச்சிடக்கூடிய அடையாள அட்டை.",
        "Scan to Verify": "சரிபார்க்க ஸ்கேன் செய்யவும்",
        "Student Identity": "மாணவர் அடையாளம்",
        "Expires": "காலாவதி",
        "Digitally generated and secured by IDENZA": "IDENZA மூலம் டிஜிட்டலாக உருவாக்கப்பட்டு பாதுகாக்கப்பட்டது",
        "Issued": "வழங்கப்பட்டது",
        "Credentials submitted": "சான்றுகள் சமர்ப்பிக்கப்பட்டன",
        "Forgot Password": "கடவுச்சொல் மறந்துவிட்டதா",
        "New Password": "புதிய கடவுச்சொல்",
        "Confirm Password": "கடவுச்சொல்லை உறுதிப்படுத்து",
        "Reset Password": "கடவுச்சொல்லை மீட்டமை",
        "Back to Login": "உள்நுழைவுக்கு திரும்பு",
        "Student password recovery": "மாணவர் கடவுச்சொல் மீட்பு",
        "School admin password recovery": "பள்ளி நிர்வாகி கடவுச்சொல் மீட்பு",
        "Super admin password recovery": "சூப்பர் அட்மின் கடவுச்சொல் மீட்பு",
        "Student ID / Username": "மாணவர் ஐடி / பயனர்பெயர்",
        "Admin Email": "நிர்வாகி மின்னஞ்சல்",
        "Super Admin Email": "சூப்பர் அட்மின் மின்னஞ்சல்",
        "Enter admin email": "நிர்வாகி மின்னஞ்சலை உள்ளிடவும்",
        "Enter super admin email": "சூப்பர் அட்மின் மின்னஞ்சலை உள்ளிடவும்",
        "No OTP found. Please request a new one.": "OTP கிடைக்கவில்லை. புதிய ஒன்றை கோரவும்.",
        "We sent a 6-digit verification code for your student login.": "உங்கள் மாணவர் உள்நுழைவிற்காக 6 இலக்க சரிபார்ப்பு குறியீடு அனுப்பப்பட்டுள்ளது.",
        "Add a task title and deadline in the two-column planner below.": "கீழே உள்ள இரு நெடுவரிசை திட்டிப்பில் பணி தலைப்பையும் காலக்கெடுவையும் சேர்க்கவும்.",
        "Enter new task": "புதிய பணியை உள்ளிடவும்",
        "Undo task": "பணியை மாற்று",
        "Mark task done": "பணி முடிந்தது என குறி",
        "Use the grid below to create a student profile without leaving this page.": "இந்த பக்கத்திலிருந்து வெளியேறாமல் மாணவர் சுயவிவரத்தை உருவாக்க கீழே உள்ள கட்டத்தை பயன்படுத்தவும்.",
        "Filter by Student Name, Student ID, EMIS, School, or Status.": "மாணவர் பெயர், மாணவர் ஐடி, EMIS, பள்ளி அல்லது நிலை மூலம் வடிகட்டு.",
        "Verified, pending, and rejected student records with edit and delete actions.": "திருத்த மற்றும் நீக்கு செயல்களுடன் சரிபார்க்கப்பட்ட, நிலுவையில் உள்ள மற்றும் நிராகரிக்கப்பட்ட மாணவர் பதிவுகள்.",
        "Pre-filled student profile form.": "முன்பூர்த்தி செய்யப்பட்ட மாணவர் சுயவிவரப் படிவம்.",
        "Update the profile fields while keeping the same verification workflow intact.": "அதே சரிபார்ப்பு செயல்முறையை காக்கும் வகையில் சுயவிவர புலங்களை புதுப்பிக்கவும்.",
        "Save Changes": "மாற்றங்களை சேமிக்கவும்",
        "Delete this student?": "இந்த மாணவரை நீக்கவா?",
        "Add Academic Data": "கல்வி தரவை சேர்க்கவும்",
        "Academic profile details for the selected student, styled with the same authenticated layout.": "தேர்ந்தெடுக்கப்பட்ட மாணவருக்கான கல்வி சுயவிவர விவரங்கள், அதே அங்கீகரிக்கப்பட்ட வடிவமைப்பில்.",
        "Back to Admin": "நிர்வாகிக்கு திரும்பு",
        "Attendance Percentage": "வருகை சதவீதம்",
        "Enter attendance percentage": "வருகை சதவீதத்தை உள்ளிடவும்",
        "Current Semester": "தற்போதைய பருவம்",
        "Enter current semester": "தற்போதைய பருவத்தை உள்ளிடவும்",
        "Year Of Study": "படிப்பு ஆண்டு",
        "Enter year": "ஆண்டை உள்ளிடவும்",
        "Arrear Count": "அரியர் எண்ணிக்கை",
        "Enter arrear count": "அரியர் எண்ணிக்கையை உள்ளிடவும்",
        "Boarding Status": "வசிப்பு நிலை",
        "Hosteller or Day Scholar": "வசதியாளர் அல்லது நாள் மாணவர்",
        "Warden Name": "வார்டன் பெயர்",
        "Enter/select warden name": "வார்டன் பெயரை உள்ளிட/தேர்வு செய்யவும்",
        "Enter SGPA": "SGPA-ஐ உள்ளிடவும்",
        "Enter CGPA": "CGPA-ஐ உள்ளிடவும்",
        "Course (Course ID - Course Name)": "பாடம் (பாட ஐடி - பாட பெயர்)",
        "Enter course id - course name": "பாட ஐடி - பாட பெயரை உள்ளிடவும்",
        "Remove course": "பாடத்தை நீக்கு",
        "Example: CS101 - Database Management Systems": "உதாரணம்: CS101 - தரவுத்தள மேலாண்மை அமைப்புகள்",
        "Save Academic Data": "கல்வி தகவலை சேமி",
        "Super Admin Dashboard": "சூப்பர் அட்மின் டாஷ்போர்டு",
        "Student ID / Email": "மாணவர் ஐடி / மின்னஞ்சல்",
        "Updated profile and set status Pending": "சுயவிவரம் புதுப்பிக்கப்பட்டது மற்றும் நிலை நிலுவையில் என அமைக்கப்பட்டது",
        "Updated profile and set status Verified": "சுயவிவரம் புதுப்பிக்கப்பட்டது மற்றும் நிலை சரிபார்க்கப்பட்டது என அமைக்கப்பட்டது",
        "Updated profile and set status Rejected": "சுயவிவரம் புதுப்பிக்கப்பட்டது மற்றும் நிலை நிராகரிக்கப்பட்டது என அமைக்கப்பட்டது",
        "Marked student as verified": "மாணவர் சரிபார்க்கப்பட்டதாக குறிக்கப்பட்டார்",
        "Marked student as rejected": "மாணவர் நிராகரிக்கப்பட்டதாக குறிக்கப்பட்டார்",
        "Deleted student profile and related records": "மாணவர் சுயவிவரமும் தொடர்புடைய பதிவுகளும் நீக்கப்பட்டன",
        "Created student with status Pending": "நிலுவை நிலையுடன் மாணவர் உருவாக்கப்பட்டார்",
        "Created student with status Verified": "சரிபார்க்கப்பட்ட நிலையுடன் மாணவர் உருவாக்கப்பட்டார்",
        "Created student with status Rejected": "நிராகரிக்கப்பட்ட நிலையுடன் மாணவர் உருவாக்கப்பட்டார்",
        "admin1@gmail.com": "admin1@gmail.com",
        "Ravi Kumar": "ரவி குமார்",
        "Priya Devi": "பிரியா தேவி",
        "Arun Raj": "அருண் ராஜ்",
        "Meena Lakshmi": "மீனா லட்சுமி",
        "Kavipriya": "கவிப்பிரியா",
        "Pradeepa": "பிரதீபா",
        "Pari": "பாரி",
        "1 - GHSS - Madurai East": "1 - அரசு மேல்நிலைப்பள்ளி - மதுரை கிழக்கு",
        "2 - GHSS - Coimbatore Town": "2 - அரசு மேல்நிலைப்பள்ளி - கோயம்புத்தூர் நகரம்",
        "3 - GHSS - Salem North": "3 - அரசு மேல்நிலைப்பள்ளி - சேலம் வடக்கு",
        "4 - GHSS - Trichy Central": "4 - அரசு மேல்நிலைப்பள்ளி - திருச்சி மையம்",
        "GHSS - Madurai East": "அரசு மேல்நிலைப்பள்ளி - மதுரை கிழக்கு",
        "GHSS - Coimbatore Town": "அரசு மேல்நிலைப்பள்ளி - கோயம்புத்தூர் நகரம்",
        "GHSS - Salem North": "அரசு மேல்நிலைப்பள்ளி - சேலம் வடக்கு",
        "GHSS - Trichy Central": "அரசு மேல்நிலைப்பள்ளி - திருச்சி மையம்",
    }
)

TRANSLATIONS.setdefault("hi", {}).update(
    {
        "Session expired due to inactivity.": "निष्क्रियता के कारण सत्र समाप्त हो गया।",
        "OTP resent successfully.": "ओटीपी सफलतापूर्वक फिर से भेजा गया।",
        "No student account found for that ID.": "उस आईडी के लिए कोई छात्र खाता नहीं मिला।",
        "No admin account found for that email.": "उस ईमेल के लिए कोई एडमिन खाता नहीं मिला।",
        "No super admin account found for that email.": "उस ईमेल के लिए कोई सुपर एडमिन खाता नहीं मिला।",
        "Reset OTP generated. Check terminal output.": "रीसेट ओटीपी बनाया गया। टर्मिनल आउटपुट देखें।",
        "Document type is required.": "दस्तावेज़ प्रकार आवश्यक है।",
        "Please choose a file to upload.": "अपलोड करने के लिए फ़ाइल चुनें।",
        "Unsupported file format. Use PNG, JPG, PDF, or DOCX.": "असमर्थित फ़ाइल प्रारूप। PNG, JPG, PDF, या DOCX का उपयोग करें।",
        "File is too large. Maximum size is 100MB.": "फ़ाइल बहुत बड़ी है। अधिकतम आकार 100MB है।",
        "Document uploaded successfully.": "दस्तावेज़ सफलतापूर्वक अपलोड हुआ।",
        "Document file is unavailable.": "दस्तावेज़ फ़ाइल उपलब्ध नहीं है।",
        "Document deleted.": "दस्तावेज़ हटाया गया।",
        "Task description is required.": "कार्य विवरण आवश्यक है।",
        "Task added.": "कार्य जोड़ा गया।",
        "Task updated.": "कार्य अपडेट किया गया।",
        "Task deleted.": "कार्य हटाया गया।",
        "QR code refreshed successfully.": "क्यूआर कोड सफलतापूर्वक रीफ्रेश किया गया।",
        "Student ID or EMIS ID already exists.": "छात्र आईडी या EMIS आईडी पहले से मौजूद है।",
        "All student fields are required.": "सभी छात्र फ़ील्ड आवश्यक हैं।",
        "Student added successfully.": "छात्र सफलतापूर्वक जोड़ा गया।",
        "Student ID or EMIS ID already belongs to another student.": "छात्र आईडी या EMIS आईडी पहले से किसी अन्य छात्र की है।",
        "Student updated successfully.": "छात्र सफलतापूर्वक अपडेट किया गया।",
        "Document approved.": "दस्तावेज़ स्वीकृत किया गया।",
        "Document rejected.": "दस्तावेज़ अस्वीकृत किया गया।",
        "Invalid document action.": "अमान्य दस्तावेज़ क्रिया।",
        "Student deleted.": "छात्र हटाया गया।",
        "All school admin fields are required.": "सभी स्कूल एडमिन फ़ील्ड आवश्यक हैं।",
        "School admin created successfully.": "स्कूल एडमिन सफलतापूर्वक बनाया गया।",
        "An account with that email already exists.": "उस ईमेल के साथ एक खाता पहले से मौजूद है।",
        "School admin status updated.": "स्कूल एडमिन स्थिति अपडेट की गई।",
        "School admin deleted.": "स्कूल एडमिन हटाया गया।",
        "Unknown Admin": "अज्ञात एडमिन",
        "Admin ID": "एडमिन आईडी",
        "You have been logged out.": "आपको लॉग आउट कर दिया गया है।",
        "update the project": "प्रोजेक्ट को अपडेट करें",
        "Update the project": "प्रोजेक्ट को अपडेट करें",
        "UPDATE THE PROJECT": "प्रोजेक्ट को अपडेट करें",
        "deploy the project": "प्रोजेक्ट को डिप्लॉय करें",
        "Deploy the project": "प्रोजेक्ट को डिप्लॉय करें",
        "DEPLOY THE PROJECT": "प्रोजेक्ट को डिप्लॉय करें",
    }
)

TRANSLATIONS.setdefault("ta", {}).update(
    {
        "Session expired due to inactivity.": "செயலற்ற நிலையில் இருந்ததால் அமர்வு முடிந்துவிட்டது.",
        "OTP resent successfully.": "OTP வெற்றிகரமாக மீண்டும் அனுப்பப்பட்டது.",
        "No student account found for that ID.": "அந்த ஐடிக்கான மாணவர் கணக்கு கிடைக்கவில்லை.",
        "No admin account found for that email.": "அந்த மின்னஞ்சலுக்கான நிர்வாகி கணக்கு கிடைக்கவில்லை.",
        "No super admin account found for that email.": "அந்த மின்னஞ்சலுக்கான சூப்பர் நிர்வாகி கணக்கு கிடைக்கவில்லை.",
        "Reset OTP generated. Check terminal output.": "கடவுச்சொல் மீட்டமைப்பு OTP உருவாக்கப்பட்டது. டெர்மினல் வெளியீட்டை பார்க்கவும்.",
        "Document type is required.": "ஆவண வகை அவசியம்.",
        "Please choose a file to upload.": "பதிவேற்ற ஒரு கோப்பைத் தேர்ந்தெடுக்கவும்.",
        "Unsupported file format. Use PNG, JPG, PDF, or DOCX.": "ஆதரிக்கப்படாத கோப்பு வடிவம். PNG, JPG, PDF, அல்லது DOCX பயன்படுத்தவும்.",
        "File is too large. Maximum size is 100MB.": "கோப்பு மிகப் பெரியது. அதிகபட்ச அளவு 100MB.",
        "Document uploaded successfully.": "ஆவணம் வெற்றிகரமாக பதிவேற்றப்பட்டது.",
        "Document file is unavailable.": "ஆவண கோப்பு கிடைக்கவில்லை.",
        "Document deleted.": "ஆவணம் நீக்கப்பட்டது.",
        "Task description is required.": "பணி விளக்கம் அவசியம்.",
        "Task added.": "பணி சேர்க்கப்பட்டது.",
        "Task updated.": "பணி புதுப்பிக்கப்பட்டது.",
        "Task deleted.": "பணி நீக்கப்பட்டது.",
        "QR code refreshed successfully.": "QR குறியீடு வெற்றிகரமாக புதுப்பிக்கப்பட்டது.",
        "Student ID or EMIS ID already exists.": "மாணவர் ஐடி அல்லது EMIS ஐடி ஏற்கனவே உள்ளது.",
        "All student fields are required.": "அனைத்து மாணவர் புலங்களும் அவசியம்.",
        "Student added successfully.": "மாணவர் வெற்றிகரமாக சேர்க்கப்பட்டார்.",
        "Student ID or EMIS ID already belongs to another student.": "மாணவர் ஐடி அல்லது EMIS ஐடி ஏற்கனவே மற்றொரு மாணவருக்குச் சொந்தமானது.",
        "Student updated successfully.": "மாணவர் விவரம் வெற்றிகரமாக புதுப்பிக்கப்பட்டது.",
        "Document approved.": "ஆவணம் ஏற்கப்பட்டது.",
        "Document rejected.": "ஆவணம் நிராகரிக்கப்பட்டது.",
        "Invalid document action.": "தவறான ஆவண செயல்.",
        "Student deleted.": "மாணவர் நீக்கப்பட்டார்.",
        "All school admin fields are required.": "அனைத்து பள்ளி நிர்வாகி புலங்களும் அவசியம்.",
        "School admin created successfully.": "பள்ளி நிர்வாகி வெற்றிகரமாக உருவாக்கப்பட்டார்.",
        "An account with that email already exists.": "இந்த மின்னஞ்சலுடன் ஏற்கனவே ஒரு கணக்கு உள்ளது.",
        "School admin status updated.": "பள்ளி நிர்வாகி நிலை புதுப்பிக்கப்பட்டது.",
        "School admin deleted.": "பள்ளி நிர்வாகி நீக்கப்பட்டார்.",
        "Unknown Admin": "அறியப்படாத நிர்வாகி",
        "Admin ID": "நிர்வாகி ஐடி",
        "You have been logged out.": "நீங்கள் வெளியேற்றப்பட்டுள்ளீர்கள்.",
        "update the project": "திட்டத்தை புதுப்பி",
        "Update the project": "திட்டத்தை புதுப்பி",
        "UPDATE THE PROJECT": "திட்டத்தை புதுப்பி",
        "deploy the project": "திட்டத்தை வெளியிடு",
        "Deploy the project": "திட்டத்தை வெளியிடு",
        "DEPLOY THE PROJECT": "திட்டத்தை வெளியிடு",
    }
)


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def normalize_language_code(value):
    code = (value or DEFAULT_LANGUAGE).strip().lower()
    return code if code in SUPPORTED_LANGUAGE_CODES else DEFAULT_LANGUAGE


def get_current_language():
    code = normalize_language_code(session.get("language"))
    for item in LANGUAGE_OPTIONS:
        if item["code"] == code:
            return item
    return LANGUAGE_OPTIONS[0]


def translate_text(text):
    if not isinstance(text, str):
        return text
    language = get_current_language()["code"]
    if language == DEFAULT_LANGUAGE:
        return text
    language_map = TRANSLATIONS.get(language, {})
    translated = language_map.get(text)
    if translated is None:
        normalized = text.strip()
        translated = language_map.get(normalized)
    if translated is None and text:
        translated = language_map.get(text.title())
    if translated is None:
        translated = text
    return repair_mojibake_text(translated)


def build_popup_manager_config():
    current_path = request.path if has_request_context() else "/"
    popup_routes = {}
    for path, route_config in GLOBAL_POPUP_ROUTE_MESSAGES.items():
        popup_routes[path] = {
            "title": translate_text(route_config.get("title", GLOBAL_POPUP_DEFAULT_TITLE)),
            "message": translate_text(route_config.get("message", GLOBAL_POPUP_DEFAULT_MESSAGE)),
            "mode": route_config.get("mode", GLOBAL_POPUP_DEFAULT_MODE),
            "delay": route_config.get("delay", GLOBAL_POPUP_DEFAULT_DELAY_MS),
        }
    return {
        "currentPath": current_path,
        "mode": GLOBAL_POPUP_DEFAULT_MODE,
        "delay": GLOBAL_POPUP_DEFAULT_DELAY_MS,
        "title": translate_text(GLOBAL_POPUP_DEFAULT_TITLE),
        "message": translate_text(GLOBAL_POPUP_DEFAULT_MESSAGE),
        "routes": popup_routes,
        "storagePrefix": "popupShown",
        "trackEndpoint": url_for("track_popup") if has_request_context() else "/track-popup",
        "enableTracking": True,
    }


def format_class_display(class_name):
    value = (class_name or "").strip()
    if not value or get_current_language()["code"] != "ta":
        return value
    match = re.match(r"^(.*?)-\s*([A-Za-z])$", value)
    if not match:
        return value
    base, section = match.groups()
    return f"{base}-{TAMIL_SECTION_MAP.get(section.upper(), section.upper())}"


def transliterate_name_to_tamil(value):
    token_pattern = re.compile(r"([A-Za-z]+|[^A-Za-z]+)")
    vowel_keys = ("aa", "ai", "au", "ii", "ee", "uu", "oo", "a", "i", "u", "e", "o")
    digraph_keys = ("ng", "ch", "sh", "th", "dh", "ph", "bh", "kh", "gh", "zh", "rr", "ll", "nn")
    ending_map = {
        "n": "ன்",
        "nn": "ன்",
        "m": "ம்",
        "r": "ர்",
        "l": "ல்",
        "k": "க்",
        "t": "ட்",
        "d": "ட்",
        "p": "ப்",
        "y": "ய்",
        "v": "வ்",
        "ng": "ங்",
        "ch": "ச்",
        "sh": "ஷ்",
        "th": "த்",
        "dh": "த்",
    }

    def read_vowel(text, start):
        for key in vowel_keys:
            if text.startswith(key, start):
                return key, len(key)
        return None, 0

    def transliterate_token(token):
        lowered = token.lower()
        token_override = TAMIL_NAME_TOKEN_OVERRIDES.get(lowered)
        if token_override:
            return token_override
        i = 0
        out = []
        length = len(lowered)
        while i < length:
            consonant_key = None
            consonant = None
            for key in digraph_keys:
                if lowered.startswith(key, i):
                    consonant_key = key
                    consonant = TAMIL_DIGRAPHS.get(key) or TAMIL_CONSONANTS.get(key[0])
                    break
            if consonant is None:
                char = lowered[i]
                if char in TAMIL_CONSONANTS:
                    consonant_key = char
                    consonant = TAMIL_CONSONANTS[char]
            if consonant is not None:
                next_index = i + len(consonant_key)
                vowel_key, vowel_len = read_vowel(lowered, next_index)
                if vowel_key:
                    out.append(consonant + TAMIL_VOWEL_SIGNS.get(vowel_key, ""))
                    i = next_index + vowel_len
                    continue
                if next_index >= length:
                    out.append(ending_map.get(consonant_key, consonant + "்"))
                else:
                    out.append(consonant)
                i = next_index
                continue
            vowel_key, vowel_len = read_vowel(lowered, i)
            if vowel_key:
                out.append(TAMIL_INDEPENDENT_VOWELS.get(vowel_key, lowered[i]))
                i += vowel_len
                continue
            out.append(token[i])
            i += 1
        return "".join(out)

    parts = token_pattern.findall(value)
    rendered = []
    for part in parts:
        if re.fullmatch(r"[A-Za-z]+", part or ""):
            rendered.append(transliterate_token(part))
        else:
            rendered.append(part)
    return "".join(rendered)


def transliterate_name_to_hindi(value):
    token_pattern = re.compile(r"([A-Za-z]+|[^A-Za-z]+)")
    vowels = ("aa", "ai", "au", "ii", "ee", "uu", "oo", "a", "i", "u", "e", "o")
    vowel_signs = {
        "a": "",
        "aa": "ा",
        "ai": "ै",
        "au": "ौ",
        "i": "ि",
        "ii": "ी",
        "ee": "ी",
        "u": "ु",
        "uu": "ू",
        "oo": "ू",
        "e": "े",
        "o": "ो",
    }
    independent_vowels = {
        "a": "अ",
        "aa": "आ",
        "ai": "ऐ",
        "au": "औ",
        "i": "इ",
        "ii": "ई",
        "ee": "ई",
        "u": "उ",
        "uu": "ऊ",
        "oo": "ऊ",
        "e": "ए",
        "o": "ओ",
    }
    consonants = {
        "kh": "ख", "gh": "घ", "ch": "च", "jh": "झ", "th": "थ", "dh": "ध",
        "ph": "फ", "bh": "भ", "sh": "श", "ng": "ङ", "ny": "ञ",
        "k": "क", "g": "ग", "j": "ज", "t": "ट", "d": "ड", "n": "न",
        "p": "प", "b": "ब", "m": "म", "y": "य", "r": "र", "l": "ल",
        "v": "व", "w": "व", "s": "स", "h": "ह", "f": "फ", "z": "ज",
        "q": "क", "x": "क्स",
    }
    digraphs = tuple(sorted([key for key in consonants if len(key) > 1], key=len, reverse=True))

    def read_vowel(text, start):
        for key in vowels:
            if text.startswith(key, start):
                return key, len(key)
        return None, 0

    def transliterate_token(token):
        lowered = token.lower()
        token_override = HI_NAME_TOKEN_OVERRIDES.get(lowered)
        if token_override:
            return token_override
        i = 0
        out = []
        length = len(lowered)
        while i < length:
            consonant_key = None
            consonant = None
            for key in digraphs:
                if lowered.startswith(key, i):
                    consonant_key = key
                    consonant = consonants[key]
                    break
            if consonant is None and lowered[i] in consonants:
                consonant_key = lowered[i]
                consonant = consonants[consonant_key]

            if consonant is not None:
                next_index = i + len(consonant_key)
                vowel_key, vowel_len = read_vowel(lowered, next_index)
                if vowel_key:
                    out.append(consonant + vowel_signs.get(vowel_key, ""))
                    i = next_index + vowel_len
                    continue
                if next_index >= length:
                    out.append(consonant)
                else:
                    out.append(consonant + "्")
                i = next_index
                continue

            vowel_key, vowel_len = read_vowel(lowered, i)
            if vowel_key:
                out.append(independent_vowels.get(vowel_key, token[i]))
                i += vowel_len
                continue
            out.append(token[i])
            i += 1
        rendered = "".join(out)
        # Light cleanup for common awkward outputs from simple romanization.
        rendered = rendered.replace("्य", "्य").replace("्र", "्र")
        return rendered

    parts = token_pattern.findall(value)
    rendered = []
    for part in parts:
        if re.fullmatch(r"[A-Za-z]+", part or ""):
            rendered.append(transliterate_token(part))
        else:
            rendered.append(part)
    return "".join(rendered)


def display_student_name(name):
    value = (name or "").strip()
    language = get_current_language()["code"]
    if not value or language not in {"ta", "hi"}:
        return value
    translated_value = translate_text(value)
    if translated_value != value:
        return translated_value
    if value.lower().startswith("admin id "):
        suffix = value[9:].strip()
        prefix = translate_text("Admin ID")
        return f"{prefix} {suffix}".strip()
    normalized_value = re.sub(r"[^\w\s-]", "", value.lower()).strip()
    if language == "hi":
        override = HI_NAME_OVERRIDES.get(normalized_value) or HI_NAME_OVERRIDES.get(value.lower())
        if override:
            return override
        if re.search(r"[A-Za-z]", value):
            return transliterate_name_to_hindi(value)
    if language == "ta":
        override = TAMIL_NAME_OVERRIDES.get(normalized_value) or TAMIL_NAME_OVERRIDES.get(value.lower())
        if override:
            return override
        if re.search(r"[A-Za-z]", value):
            return transliterate_name_to_tamil(value)
    return value


def display_task_title(title):
    value = (title or "").strip()
    if not value:
        return value
    translated = translate_text(value)
    if translated != value:
        return translated
    language = get_current_language()["code"]
    if language not in {"ta", "hi"}:
        return value

    token_pattern = re.compile(r"([A-Za-z]+|[^A-Za-z]+)")
    tokens = token_pattern.findall(value)
    rendered = []
    for token in tokens:
        if not re.fullmatch(r"[A-Za-z]+", token or ""):
            rendered.append(token)
            continue
        lowered = token.lower()
        token_translated = translate_text(token)
        if token_translated == token:
            token_translated = translate_text(lowered)
        if token_translated == lowered:
            token_translated = translate_text(token.title())
        if token_translated not in {token, lowered, token.title()}:
            rendered.append(token_translated)
            continue
        if language == "ta":
            mapped = TA_TASK_TOKEN_OVERRIDES.get(lowered)
            if mapped:
                rendered.append(mapped)
            else:
                rendered.append(transliterate_name_to_tamil(token))
        else:
            mapped = HI_TASK_TOKEN_OVERRIDES.get(lowered)
            rendered.append(mapped or token)
    return "".join(rendered)


def display_ranked_school_name(name):
    value = (name or "").strip()
    if not value:
        return ""
    cleaned = re.sub(r"^\s*\d+\s*-\s*", "", value).strip()
    return translate_text(cleaned)


def display_avatar_initial(name):
    value = display_student_name(name).strip()
    if not value:
        return ""
    initial = value[0]
    index = 1
    while index < len(value) and unicodedata.category(value[index]) in {"Mn", "Mc", "Me"}:
        initial += value[index]
        index += 1
    return initial


def get_record_value(record, *keys):
    if record is None:
        return None
    for key in keys:
        try:
            value = record[key]
        except (KeyError, IndexError, TypeError):
            value = record.get(key) if isinstance(record, dict) else None
        if value is not None:
            return value
    return None


def effective_verification_status(record):
    status = (get_record_value(record, "verification_status", "status") or "Pending").title()
    rejection_reason = (get_record_value(record, "rejection_reason") or "").strip()
    if status == "Rejected" and not rejection_reason:
        return "Pending"
    return status


def get_saved_qr_filename():
    for filename in SAVED_QR_FILENAMES:
        if os.path.exists(os.path.join("static", filename)):
            return filename
    return None


def now_utc():
    return datetime.now(timezone.utc)


def now_local_naive():
    return datetime.now().replace(microsecond=0)


def parse_local_naive_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo:
            # Preserve the user-entered wall-clock time instead of converting it.
            return parsed.replace(tzinfo=None, microsecond=0)
        return parsed.replace(microsecond=0)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo:
            # Keep the original local slot chosen by the user.
            return parsed.replace(tzinfo=None, microsecond=0)
        return parsed.replace(microsecond=0)
    except ValueError:
        pass
    # Fallback support for manually entered/localized date-time strings.
    for fmt in (
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %I:%M %p",
    ):
        try:
            return datetime.strptime(text, fmt).replace(microsecond=0)
        except ValueError:
            continue
    return None


def format_timestamp(value):
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%d %b %Y, %I:%M %p UTC")
    except ValueError:
        return value


app.jinja_env.filters["datetime"] = format_timestamp


def format_task_timestamp(value):
    dt = parse_local_naive_datetime(value)
    if not dt:
        return value or "-"
    return dt.strftime("%d %b %Y, %I:%M %p")


app.jinja_env.filters["task_datetime"] = format_task_timestamp


def parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def format_date_for_input(value):
    if not value:
        return ""
    for date_format in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, date_format).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value


def normalize_date_storage(value):
    if not value:
        return ""
    for date_format in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, date_format).strftime("%d-%m-%Y")
        except ValueError:
            continue
    return value


app.jinja_env.filters["date_input"] = format_date_for_input


def readable_file_size(byte_count):
    size = float(byte_count or 0)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024 or unit == "GB":
            return f"{size:.2f} {unit}"
        size /= 1024
    return "0 B"


app.jinja_env.filters["filesize"] = readable_file_size


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_uploads_dir():
    os.makedirs(UPLOADS_DIR, exist_ok=True)


def ensure_column(cursor, table_name, column_name, definition):
    cursor.execute(f"PRAGMA table_info({table_name})")
    if column_name not in [row[1] for row in cursor.fetchall()]:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def set_permanent_session(role, user_id):
    session.permanent = True
    session["user_id"] = user_id
    session["role"] = role
    session["last_active"] = now_utc().isoformat()


def get_login_redirect(role):
    if role == "admin":
        return url_for("admin_login")
    if role == "superadmin":
        return url_for("superadmin_login")
    return url_for("student_login")


def is_account_locked(locked_until_value):
    locked_until = parse_datetime(locked_until_value)
    return bool(locked_until and now_utc() < locked_until)


def log_login_attempt(user_identifier, role, success):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO login_logs (user_id, role, ip_address, user_agent, success)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            str(user_identifier or ""),
            role,
            request.remote_addr or "",
            request.user_agent.string or "",
            1 if success else 0,
        ),
    )
    conn.commit()
    conn.close()


def mark_failed_login(cursor, table_name, user_id):
    cursor.execute(
        f"SELECT COALESCE(failed_attempts, 0) AS failed_attempts FROM {table_name} WHERE user_id = ?",
        (user_id,),
    )
    row = cursor.fetchone()
    attempts = (row["failed_attempts"] if row else 0) + 1
    locked_until = (now_utc() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat() if attempts >= LOCKOUT_LIMIT else None
    cursor.execute(
        f"UPDATE {table_name} SET failed_attempts = ?, locked_until = ? WHERE user_id = ?",
        (0 if locked_until else attempts, locked_until, user_id),
    )
    return bool(locked_until)


def reset_failed_logins(cursor, table_name, user_id):
    cursor.execute(
        f"UPDATE {table_name} SET failed_attempts = 0, locked_until = NULL WHERE user_id = ?",
        (user_id,),
    )


def log_action(admin_id, action, target_student_id, details, school_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if school_id is None:
        cursor.execute("SELECT school_id FROM admin_profiles WHERE user_id = ?", (admin_id,))
        profile = cursor.fetchone()
        school_id = profile["school_id"] if profile else None
    cursor.execute(
        """
        INSERT INTO audit_log (admin_id, action, target_student_id, details, school_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(admin_id or ""), action, target_student_id, details, school_id),
    )
    conn.commit()
    conn.close()


def set_verification_status(cursor, user_id, status, updated_by_admin_id=None):
    timestamp = now_utc().isoformat()
    cursor.execute("SELECT id FROM verification_status WHERE user_id = ? ORDER BY id DESC", (user_id,))
    existing_rows = cursor.fetchall()
    if existing_rows:
        latest_id = existing_rows[0]["id"]
        cursor.execute(
            """
            UPDATE verification_status
            SET status = ?, updated_at = ?, updated_by_admin_id = ?
            WHERE id = ?
            """,
            (status, timestamp, updated_by_admin_id, latest_id),
        )
        if len(existing_rows) > 1:
            cursor.executemany("DELETE FROM verification_status WHERE id = ?", [(row["id"],) for row in existing_rows[1:]])
    else:
        cursor.execute(
            """
            INSERT INTO verification_status (user_id, status, updated_at, updated_by_admin_id)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, status, timestamp, updated_by_admin_id),
        )
    if status == "Verified":
        cursor.execute("UPDATE student_details SET verified_at = ?, rejection_reason = NULL WHERE user_id = ?", (timestamp, user_id))
    elif status in {"Pending", "Rejected"}:
        cursor.execute("UPDATE student_details SET verified_at = NULL WHERE user_id = ?", (user_id,))


def save_document_file(doc_id, original_name, file_bytes):
    ensure_uploads_dir()
    extension = os.path.splitext(original_name or "")[1].lower()
    safe_extension = extension if extension in ALLOWED_EXTENSIONS else ""
    relative_path = os.path.join("static", "uploads", f"doc_{doc_id}{safe_extension}")
    absolute_path = os.path.join(os.getcwd(), relative_path)
    with open(absolute_path, "wb") as file_handle:
        file_handle.write(file_bytes)
    return relative_path.replace("\\", "/")


def load_uploaded_document(doc_id, school_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT d.id, d.file_name, d.content_type, d.file_data, d.file_path, d.document_type,
               s.user_id, s.student_id
        FROM uploaded_documents d
        JOIN student_details s ON s.user_id = d.user_id
        WHERE d.id = ? AND s.school_id = ?
        """,
        (doc_id, school_id),
    )
    document = cursor.fetchone()
    conn.close()
    return document


def resolve_document_bytes(document):
    file_bytes = None
    file_path = (document["file_path"] or "").strip()
    if file_path:
        absolute_path = os.path.join(os.getcwd(), file_path.replace("/", os.sep))
        if os.path.exists(absolute_path):
            with open(absolute_path, "rb") as file_handle:
                file_bytes = file_handle.read()
    if file_bytes is None:
        file_bytes = document["file_data"]
    return file_bytes


def verify_file_hash(doc_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT file_hash, file_data, file_path
        FROM uploaded_documents
        WHERE id = ?
        """,
        (doc_id,),
    )
    document = cursor.fetchone()
    conn.close()
    if not document or not document["file_hash"]:
        return False
    file_bytes = None
    file_path = (document["file_path"] or "").strip()
    if file_path:
        absolute_path = os.path.join(os.getcwd(), file_path.replace("/", os.sep))
        if os.path.exists(absolute_path):
            with open(absolute_path, "rb") as file_handle:
                file_bytes = file_handle.read()
    if file_bytes is None:
        file_bytes = document["file_data"]
    if file_bytes is None:
        return False
    return hashlib.sha256(file_bytes).hexdigest() == document["file_hash"]


def refresh_student_qr_token(cursor, user_id, force=False):
    cursor.execute("SELECT qr_token, qr_expires_at FROM student_details WHERE user_id = ?", (user_id,))
    student = cursor.fetchone()
    existing_token = student["qr_token"] if student else None
    existing_expiry = parse_datetime(student["qr_expires_at"]) if student else None
    if not force and existing_token and existing_expiry and existing_expiry > now_utc():
        return existing_token, existing_expiry.isoformat()
    token = str(uuid4())
    expires_at = (now_utc() + timedelta(hours=24)).isoformat()
    cursor.execute(
        "UPDATE student_details SET qr_token = ?, qr_expires_at = ? WHERE user_id = ?",
        (token, expires_at, user_id),
    )
    return token, expires_at


def sync_student_verification_from_documents(cursor, user_id, admin_user_id=None):
    # Document actions must never auto-change global verification status.
    # Keep the current global status exactly as it is.
    cursor.execute(
        """
        SELECT status
        FROM verification_status
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    current = cursor.fetchone()
    if current and current["status"]:
        return current["status"]
    return "Pending"


def get_recent_successful_logins(user_id, role, limit=5):
    conn = get_db_connection()
    cursor = conn.cursor()
    cutoff = (now_utc() - timedelta(hours=24)).isoformat(timespec="seconds")
    cursor.execute(
        """
        SELECT ip_address, login_at
        FROM login_logs
        WHERE user_id = ? AND role = ? AND success = 1 AND datetime(login_at) >= datetime(?)
        ORDER BY datetime(login_at) DESC, id DESC
        LIMIT ?
        """,
        (str(user_id), role, cutoff, limit),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def has_new_login_location(user_id, role):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT ip_address, login_at
        FROM login_logs
        WHERE user_id = ? AND role = ? AND success = 1
        ORDER BY id DESC
        LIMIT 1
        """,
        (str(user_id), role),
    )
    latest = cursor.fetchone()
    if not latest:
        conn.close()
        return False
    threshold = (now_utc() - timedelta(days=30)).isoformat()
    cursor.execute(
        """
        SELECT 1
        FROM login_logs
        WHERE user_id = ? AND role = ? AND success = 1 AND ip_address = ? AND login_at < ? AND login_at >= ?
        LIMIT 1
        """,
        (str(user_id), role, latest["ip_address"], latest["login_at"], threshold),
    )
    seen_before = cursor.fetchone() is not None
    cursor.execute(
        """
        SELECT 1
        FROM login_logs
        WHERE user_id = ? AND role = ? AND success = 1 AND login_at < ?
        LIMIT 1
        """,
        (str(user_id), role, latest["login_at"]),
    )
    has_prior_success = cursor.fetchone() is not None
    conn.close()
    return has_prior_success and not seen_before


def generate_otp():
    return str(random.randint(100000, 999999))


def send_otp_email(recipient, otp_code, purpose):
    title_map = {
        "student_login": "Student Login Verification",
        "student_reset": "Student Password Reset",
    }
    message = EmailMessage()
    message["Subject"] = f"IDENZA - {title_map.get(purpose, 'OTP Verification')}"
    message["From"] = os.getenv("SMTP_FROM", "no-reply@idenza.local")
    message["To"] = recipient
    message.set_content(f"Your IDENZA OTP is {otp_code}. It is valid for 5 minutes.")

    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")

    if not smtp_server:
        print(f"[OTP] purpose={purpose} recipient={recipient} code={otp_code}")
        return True

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            if smtp_username and smtp_password:
                server.login(smtp_username, smtp_password)
            server.send_message(message)
        return True
    except Exception as exc:
        print(f"Failed to send OTP: {exc}")
        return False


def create_otp_record(email, purpose, user_id=None):
    otp_code = generate_otp()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO otp_requests (email, user_id, purpose, otp_hash, expires_at, is_used, created_at)
        VALUES (?, ?, ?, ?, ?, 0, ?)
        """,
        (
            email,
            user_id,
            purpose,
            hash_password(otp_code),
            (now_utc() + timedelta(minutes=5)).isoformat(),
            now_utc().isoformat(),
        ),
    )
    conn.commit()
    conn.close()
    print(f"[OTP] purpose={purpose} email={email} code={otp_code}")
    return otp_code


def validate_otp(email, purpose, otp_code):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, expires_at
        FROM otp_requests
        WHERE email = ? AND purpose = ? AND otp_hash = ? AND is_used = 0
        ORDER BY id DESC
        LIMIT 1
        """,
        (email, purpose, hash_password(otp_code)),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if now_utc() > expires_at:
        conn.close()
        return False
    cursor.execute("UPDATE otp_requests SET is_used = 1 WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()
    return True


def parse_year_from_class(class_name):
    match = re.search(r"\d+", class_name or "")
    return int(match.group()) if match else 1


def parse_school_id(school_info):
    match = re.match(r"\s*(\d+)", school_info or "")
    return int(match.group(1)) if match else 1


def build_student_login_email(student_id):
    return f"{student_id.strip().lower()}@{CSV_LOGIN_EMAIL_DOMAIN}"


def normalize_student_identifier(identifier):
    value = (identifier or "").strip().lower()
    if value and "@" not in value:
        return build_student_login_email(value)
    return value


def allowed_file(filename):
    return os.path.splitext(filename.lower())[1] in ALLOWED_EXTENSIONS


def get_public_verify_url(qr_token):
    verify_path = url_for("verify_student", qr_token=qr_token)
    base_url = os.getenv("PUBLIC_BASE_URL")
    if base_url:
        return f"{base_url.rstrip('/')}{verify_path}"
    if has_request_context():
        return f"{request.host_url.rstrip('/')}{verify_path}"
    return f"http://127.0.0.1:5000{verify_path}"


def generate_qr(qr_token):
    qr = qrcode.QRCode(
        version=1,
        box_size=8,
        border=2,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
    )
    qr.add_data(get_public_verify_url(qr_token))
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1a6b3a", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def build_qr_matrix(seed_text, size=21):
    digest = hashlib.sha256(seed_text.encode()).hexdigest()
    bits = bin(int(digest, 16))[2:].zfill(len(digest) * 4)
    matrix = []
    bit_index = 0
    finder_points = {(0, 0), (0, size - 7), (size - 7, 0)}
    for row in range(size):
        line = []
        for col in range(size):
            in_finder = False
            for start_row, start_col in finder_points:
                if start_row <= row < start_row + 7 and start_col <= col < start_col + 7:
                    local_r = row - start_row
                    local_c = col - start_col
                    in_finder = (
                        local_r in {0, 6}
                        or local_c in {0, 6}
                        or (2 <= local_r <= 4 and 2 <= local_c <= 4)
                    )
                    break
            if in_finder:
                line.append(True)
            else:
                line.append(bits[bit_index % len(bits)] == "1")
                bit_index += 1
        matrix.append(line)
    return matrix


def get_student_notifications(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    current_time = now_local_naive()
    cursor.execute(
        """
        SELECT id, title, deadline_at
        FROM student_tasks
        WHERE user_id = ? AND is_done = 0 AND deadline_at IS NOT NULL
        ORDER BY deadline_at ASC, id DESC
        """,
        (user_id,),
    )
    overdue_tasks = []
    for task in cursor.fetchall():
        deadline_dt = parse_local_naive_datetime(task["deadline_at"])
        if deadline_dt and deadline_dt < current_time:
            overdue_tasks.append(task)
    cursor.execute(
        """
        SELECT id, document_type, doc_rejection_reason, uploaded_at
        FROM uploaded_documents
        WHERE user_id = ?
          AND COALESCE(doc_status, 'Pending') = 'Rejected'
          AND COALESCE(student_notification_hidden, 0) = 0
        ORDER BY id DESC
        """,
        (user_id,),
    )
    rejected_documents = cursor.fetchall()
    cursor.execute(
        """
        SELECT id, document_type, verified_at
        FROM uploaded_documents
        WHERE user_id = ?
          AND COALESCE(doc_status, 'Pending') = 'Verified'
          AND COALESCE(student_notification_hidden, 0) = 0
          AND verified_at IS NOT NULL
          AND datetime(verified_at) >= datetime('now', '-1 day')
        ORDER BY id DESC
        """,
        (user_id,),
    )
    verified_documents = cursor.fetchall()
    conn.close()
    def safe_document_title(raw_value, fallback):
        text = str(raw_value or "").strip()
        if not text or text.lower() in {"none", "null", "nil", "n/a", "na"}:
            return fallback
        return text

    notifications = []
    for task in overdue_tasks:
        notifications.append(
            {
                "kind": "overdue",
                "title": task["title"],
                "message": "Task overdue",
                "time": task["deadline_at"],
            }
        )
    for document in rejected_documents:
        notifications.append(
            {
                "kind": "document_rejected",
                "doc_id": document["id"],
                "title": safe_document_title(document["document_type"], "Unknown Document"),
                "message": document["doc_rejection_reason"] or "Please review the rejection reason and upload a corrected file.",
                "time": document["uploaded_at"],
            }
        )
    for document in verified_documents:
        notifications.append(
            {
                "kind": "document_verified",
                "doc_id": document["id"],
                "title": safe_document_title(document["document_type"], "Unknown Document"),
                "message": "Reviewed and approved by admin.",
                "time": document["verified_at"],
            }
        )
    notifications.sort(key=lambda item: item.get("time") or "", reverse=True)
    return len(notifications), notifications


def get_admin_notifications(school_id, limit=10):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM uploaded_documents d
        JOIN student_details s ON s.user_id = d.user_id
        WHERE s.school_id = ?
          AND COALESCE(d.doc_status, 'Pending') = 'Pending'
          AND datetime(d.uploaded_at) >= datetime('now', '-1 day')
        """,
        (school_id,),
    )
    total = cursor.fetchone()["total"]
    cursor.execute(
        """
        SELECT s.id AS student_row_id, s.name AS student_name, s.student_id, d.document_type, d.uploaded_at
        FROM uploaded_documents d
        JOIN student_details s ON s.user_id = d.user_id
        WHERE s.school_id = ?
          AND COALESCE(d.doc_status, 'Pending') = 'Pending'
          AND datetime(d.uploaded_at) >= datetime('now', '-1 day')
        ORDER BY d.id DESC
        LIMIT ?
        """,
        (school_id, limit),
    )
    rows = cursor.fetchall()
    conn.close()
    def safe_document_title(raw_value):
        text = str(raw_value or "").strip()
        if not text or text.lower() in {"none", "null", "nil", "n/a", "na"}:
            return "Unknown Document"
        return text

    notifications = []
    for row in rows:
        notifications.append(
            {
                "kind": "new_upload",
                "student_row_id": row["student_row_id"],
                "student_name": row["student_name"],
                "student_id": row["student_id"],
                "document_type": safe_document_title(row["document_type"]),
                "time": row["uploaded_at"],
            }
        )
    return total, notifications


def format_audit_details(action, details):
    value = (details or "").strip()
    if not value:
        return value

    translated_value = translate_text(value)
    if translated_value != value:
        return translated_value

    def safe_document_label(raw_value, fallback):
        text = str(raw_value or "").strip()
        if not text or text.lower() in {"none", "null", "nil", "n/a", "na"}:
            return fallback
        return text

    lowered = value.lower()
    if lowered.startswith("rejected document:"):
        remainder = value.split(":", 1)[1].strip()
        document_type = remainder
        rejection_reason = ""
        if "|" in remainder:
            document_type, rejection_reason = [part.strip() for part in remainder.split("|", 1)]
        prefix = translate_text("Document rejected")
        document_label = translate_text(safe_document_label(document_type, "Document rejected"))
        if prefix and document_label and document_label == prefix:
            rendered = prefix
        else:
            rendered = f"{prefix}: {document_label}" if prefix else document_label
        if rejection_reason:
            rendered = f"{rendered} | {rejection_reason}"
        return rendered

    if lowered.startswith("approved document:"):
        document_type = value.split(":", 1)[1].strip()
        prefix = translate_text("Document approved")
        document_label = translate_text(safe_document_label(document_type, "Document approved"))
        if prefix and document_label and document_label == prefix:
            return prefix
        return f"{prefix}: {document_label}" if prefix else document_label

    return value


def get_student_identifier(student):
    if not student:
        return ""
    return student["student_id"] or student["register_number"] or ""


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schools (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            location TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            name TEXT NOT NULL,
            school_id INTEGER,
            status TEXT DEFAULT 'active',
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (school_id) REFERENCES schools (id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS student_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            course TEXT,
            register_number TEXT,
            year_of_study INTEGER DEFAULT 1,
            current_semester TEXT DEFAULT 'S1',
            arrear_count INTEGER DEFAULT 0,
            boarding_status TEXT DEFAULT 'Day Scholar',
            warden_name TEXT,
            mentor_name TEXT,
            room_no TEXT,
            attendance_percentage INTEGER DEFAULT 0,
            sgpa_history TEXT,
            sgpa REAL DEFAULT 0,
            cgpa REAL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    ensure_column(cursor, "student_details", "student_id", "TEXT")
    ensure_column(cursor, "student_details", "dob", "TEXT")
    ensure_column(cursor, "student_details", "emis_id", "TEXT")
    ensure_column(cursor, "student_details", "parent_mobile", "TEXT")
    ensure_column(cursor, "student_details", "school_info", "TEXT")
    ensure_column(cursor, "student_details", "class_name", "TEXT")
    ensure_column(cursor, "student_details", "school_id", "INTEGER DEFAULT 1")
    ensure_column(cursor, "student_details", "login_password", "TEXT")
    ensure_column(cursor, "student_details", "rejection_reason", "TEXT")
    ensure_column(cursor, "student_details", "failed_attempts", "INTEGER DEFAULT 0")
    ensure_column(cursor, "student_details", "locked_until", "TEXT")
    ensure_column(cursor, "student_details", "qr_token", "TEXT")
    ensure_column(cursor, "student_details", "qr_expires_at", "TEXT")
    ensure_column(cursor, "student_details", "verified_at", "TEXT")
    ensure_column(cursor, "admin_profiles", "failed_attempts", "INTEGER DEFAULT 0")
    ensure_column(cursor, "admin_profiles", "locked_until", "TEXT")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS verification_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            status TEXT DEFAULT 'Pending',
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    ensure_column(cursor, "verification_status", "updated_at", "TEXT")
    ensure_column(cursor, "verification_status", "updated_by_admin_id", "INTEGER")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS uploaded_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            document_type TEXT,
            file_name TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            content_type TEXT,
            file_data BLOB NOT NULL,
            uploaded_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    ensure_column(cursor, "uploaded_documents", "document_type", "TEXT")
    ensure_column(cursor, "uploaded_documents", "file_size", "INTEGER DEFAULT 0")
    ensure_column(cursor, "uploaded_documents", "file_hash", "TEXT")
    ensure_column(cursor, "uploaded_documents", "file_path", "TEXT")
    ensure_column(cursor, "uploaded_documents", "doc_status", "TEXT DEFAULT 'Pending'")
    ensure_column(cursor, "uploaded_documents", "doc_rejection_reason", "TEXT")
    ensure_column(cursor, "uploaded_documents", "verified_at", "TEXT")
    ensure_column(cursor, "uploaded_documents", "verified_by_admin_id", "INTEGER")
    ensure_column(cursor, "uploaded_documents", "student_notification_hidden", "INTEGER DEFAULT 0")
    cursor.execute(
        """
        UPDATE uploaded_documents
        SET document_type = NULL
        WHERE LOWER(TRIM(COALESCE(document_type, ''))) IN ('none', 'null', 'nil', 'n/a', 'na')
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS student_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            deadline_at TEXT,
            is_done INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    ensure_column(cursor, "student_tasks", "deadline_at", "TEXT")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS otp_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            user_id INTEGER,
            purpose TEXT NOT NULL,
            otp_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            is_used INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id TEXT,
            action TEXT,
            target_student_id TEXT,
            details TEXT,
            school_id INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    ensure_column(cursor, "audit_log", "school_id", "INTEGER")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS verification_scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ip_address TEXT,
            user_agent TEXT
        )
        """
    )
    ensure_column(cursor, "verification_scans", "viewed_by", "TEXT DEFAULT 'unknown'")
    ensure_column(cursor, "verification_scans", "viewer_role", "TEXT DEFAULT 'unknown'")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS login_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT,
            ip_address TEXT,
            user_agent TEXT,
            login_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            success INTEGER
        )
        """
    )

    for school in SCHOOLS:
        cursor.execute(
            """
            INSERT INTO schools (id, name, location)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                location = excluded.location
            """,
            (school["id"], school["name"], school["location"]),
        )

    cursor.execute(
        """
        INSERT INTO users (email, password, role)
        VALUES (?, ?, 'superadmin')
        ON CONFLICT(email) DO UPDATE SET
            password = excluded.password,
            role = 'superadmin'
        """,
        ("superadmin@gmail.com", hash_password("admin@123")),
    )

    for name, email, raw_password, school_id, status in SEEDED_SCHOOL_ADMINS:
        cursor.execute(
            """
            INSERT INTO users (email, password, role)
            VALUES (?, ?, 'admin')
            ON CONFLICT(email) DO UPDATE SET
                password = excluded.password,
                role = 'admin'
            """,
            (email, hash_password(raw_password)),
        )
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        user_id = cursor.fetchone()["id"]
        cursor.execute(
            """
            INSERT INTO admin_profiles (user_id, name, school_id, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name = excluded.name,
                school_id = excluded.school_id,
                status = excluded.status
            """,
            (user_id, name, school_id, status),
        )

    if os.path.exists(CSV_STUDENT_DATA_FILE):
        with open(CSV_STUDENT_DATA_FILE, newline="", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                student_id = (row.get("student_id") or "").strip()
                name = (row.get("student_name") or "").strip()
                emis_id = (row.get("emis_id") or "").strip()
                school_info = (row.get("school_info") or "").strip()
                class_name = (row.get("class") or "").strip()
                parent_mobile = (row.get("parent_mobile") or "").strip()
                dob = (row.get("dob") or "").strip()
                raw_password = (row.get("password") or "").strip()
                status = (row.get("verification_status") or "Pending").strip().title() or "Pending"
                if not student_id or not name or not raw_password:
                    continue

                email = build_student_login_email(student_id)
                school_id = parse_school_id(school_info)
                cursor.execute(
                    """
                    INSERT INTO users (email, password, role)
                    VALUES (?, ?, 'student')
                    ON CONFLICT(email) DO UPDATE SET
                        password = excluded.password,
                        role = 'student'
                    """,
                    (email, hash_password(raw_password)),
                )
                cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
                user_id = cursor.fetchone()["id"]
                cursor.execute("SELECT id FROM student_details WHERE user_id = ?", (user_id,))
                existing = cursor.fetchone()
                payload = (
                    user_id,
                    name,
                    school_info,
                    student_id,
                    parse_year_from_class(class_name),
                    class_name,
                    0,
                    "Day Scholar",
                    None,
                    "School Mentor",
                    None,
                    0,
                    "",
                    0,
                    0,
                    student_id,
                    dob,
                    emis_id,
                    parent_mobile,
                    school_info,
                    class_name,
                    school_id,
                    raw_password,
                )
                if existing:
                    cursor.execute(
                        """
                        UPDATE student_details
                        SET user_id = ?, name = ?, course = ?, register_number = ?, year_of_study = ?,
                            current_semester = ?, arrear_count = ?, boarding_status = ?, warden_name = ?,
                            mentor_name = ?, room_no = ?, attendance_percentage = ?, sgpa_history = ?,
                            sgpa = ?, cgpa = ?, student_id = ?, dob = ?, emis_id = ?, parent_mobile = ?,
                            school_info = ?, class_name = ?, school_id = ?, login_password = ?
                        WHERE id = ?
                        """,
                        payload + (existing["id"],),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO student_details
                        (user_id, name, course, register_number, year_of_study, current_semester, arrear_count,
                         boarding_status, warden_name, mentor_name, room_no, attendance_percentage, sgpa_history,
                         sgpa, cgpa, student_id, dob, emis_id, parent_mobile, school_info, class_name,
                         school_id, login_password)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        payload,
                    )
                cursor.execute("SELECT id FROM verification_status WHERE user_id = ? LIMIT 1", (user_id,))
                if not cursor.fetchone():
                    set_verification_status(cursor, user_id, status)

    ensure_uploads_dir()
    cursor.execute(
        """
        SELECT id, file_name, file_data, file_hash, file_path, doc_status
        FROM uploaded_documents
        ORDER BY id ASC
        """
    )
    for document in cursor.fetchall():
        updates = []
        params = []
        if not document["file_hash"] and document["file_data"] is not None:
            updates.append("file_hash = ?")
            params.append(hashlib.sha256(document["file_data"]).hexdigest())
        if not document["file_path"] and document["file_data"] is not None:
            updates.append("file_path = ?")
            params.append(save_document_file(document["id"], document["file_name"], document["file_data"]))
        if not document["doc_status"]:
            updates.append("doc_status = 'Pending'")
        if updates:
            params.append(document["id"])
            cursor.execute(f"UPDATE uploaded_documents SET {', '.join(updates)} WHERE id = ?", params)

    # Repair legacy audit rows where admin_id no longer matches admin_profiles.user_id.
    # If a school has exactly one admin profile, remap orphaned admin_id values to that admin.
    cursor.execute(
        """
        UPDATE audit_log
        SET admin_id = (
            SELECT CAST(ap.user_id AS TEXT)
            FROM admin_profiles ap
            WHERE ap.school_id = audit_log.school_id
            GROUP BY ap.school_id
            HAVING COUNT(*) = 1
        )
        WHERE school_id IS NOT NULL
          AND COALESCE(TRIM(admin_id), '') <> ''
          AND NOT EXISTS (
              SELECT 1
              FROM admin_profiles apx
              WHERE apx.user_id = CAST(audit_log.admin_id AS INTEGER)
          )
          AND EXISTS (
              SELECT 1
              FROM admin_profiles ap2
              WHERE ap2.school_id = audit_log.school_id
              GROUP BY ap2.school_id
              HAVING COUNT(*) = 1
          )
        """
    )

    conn.commit()
    conn.close()


init_db()


@app.before_request
def enforce_session_timeout():
    endpoint = request.endpoint or ""
    if endpoint == "static":
        return None
    if session.get("role") and session.get("user_id"):
        last_active = parse_datetime(session.get("last_active"))
        if last_active and now_utc() - last_active > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
            role = session.get("role")
            session.clear()
            flash("Session expired due to inactivity.", "error")
            return redirect(get_login_redirect(role))
        session["last_active"] = now_utc().isoformat()
    return None


def require_role(role):
    if session.get("role") != role:
        return redirect(get_login_redirect(role))
    return None


def get_current_student():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT s.*, v.status AS verification_status, v.updated_at AS verification_updated_at,
               a.name AS verified_by_admin_name
        FROM student_details s
        LEFT JOIN (
            SELECT vs.user_id, vs.status, vs.updated_at, vs.updated_by_admin_id
            FROM verification_status vs
            INNER JOIN (
                SELECT user_id, MAX(id) AS latest_id
                FROM verification_status
                GROUP BY user_id
            ) latest ON latest.latest_id = vs.id
        ) v ON v.user_id = s.user_id
        LEFT JOIN admin_profiles a ON a.user_id = v.updated_by_admin_id
        WHERE s.user_id = ?
        """,
        (session["user_id"],),
    )
    student = cursor.fetchone()
    conn.close()
    return student


def get_current_admin_profile():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT a.*, s.name AS school_name, u.email
        FROM admin_profiles a
        LEFT JOIN schools s ON s.id = a.school_id
        LEFT JOIN users u ON u.id = a.user_id
        WHERE a.user_id = ?
        """,
        (session["user_id"],),
    )
    profile = cursor.fetchone()
    conn.close()
    return profile


def missing_profile_redirect(message):
    session.clear()
    flash(message, "error")
    return redirect(url_for("student_login"))


def student_sidebar():
    return [
        {"label": translate_text("Dashboard"), "endpoint": "student_dashboard"},
        {"label": translate_text("Upload Documents"), "endpoint": "student_upload"},
        {"label": translate_text("My Tasks"), "endpoint": "student_tasks"},
        {"label": translate_text("Portals"), "endpoint": "student_portals"},
    ]


def admin_sidebar():
    return [
        {"label": translate_text("Dashboard"), "endpoint": "school_admin_dashboard"},
        {"label": translate_text("Manage Students"), "endpoint": "manage_students"},
        {"label": translate_text("Audit Log"), "endpoint": "admin_audit_log"},
    ]


def superadmin_sidebar():
    return [
        {"label": translate_text("Dashboard"), "endpoint": "superadmin_dashboard"},
        {"label": translate_text("Audit Log"), "endpoint": "admin_audit_log"},
    ]


@app.context_processor
def inject_global_template_state():
    current_language = get_current_language()
    context = {
        "academic_year": ACADEMIC_YEAR,
        "language_options": LANGUAGE_OPTIONS,
        "current_language": current_language,
        "_": translate_text,
        "format_class_display": format_class_display,
        "display_student_name": display_student_name,
        "display_task_title": display_task_title,
        "display_ranked_school_name": display_ranked_school_name,
        "display_avatar_initial": display_avatar_initial,
        "effective_verification_status": effective_verification_status,
        "format_audit_details": format_audit_details,
        "popup_manager_config": build_popup_manager_config(),
        "session_warning_seconds": SESSION_WARNING_MINUTES * 60,
        "session_timeout_seconds": SESSION_TIMEOUT_MINUTES * 60,
    }
    if session.get("role") == "student" and session.get("user_id"):
        notification_count, student_notifications = get_student_notifications(session["user_id"])
        context.update(
            overdue_count=notification_count,
            overdue_tasks=student_notifications,
            notification_count=notification_count,
            student_notifications=student_notifications,
        )
    elif session.get("role") == "admin":
        admin = get_current_admin_profile()
        if admin:
            notification_count, admin_notifications = get_admin_notifications(admin["school_id"])
            context.update(
                notification_count=notification_count,
                admin_notifications=admin_notifications,
            )
    return context


@app.route("/language", methods=["POST"])
def set_language():
    session["language"] = normalize_language_code(request.form.get("language"))
    flash("Language updated.", "success")
    next_url = request.form.get("next_url", "").strip()
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect(request.referrer or url_for("student_login"))


@app.route("/track-popup", methods=["POST"])
def track_popup():
    payload = request.get_json(silent=True) or {}
    event_type = str(payload.get("event", "")).strip() or "unknown"
    timestamp = str(payload.get("timestamp", "")).strip() or datetime.now(timezone.utc).isoformat()
    path = str(payload.get("path", "")).strip() or request.path
    route_key = str(payload.get("route_key", "")).strip()
    mode = str(payload.get("mode", "")).strip() or "once"
    app.logger.info(
        "popup_event=%s timestamp=%s path=%s route_key=%s mode=%s",
        event_type,
        timestamp,
        path,
        route_key,
        mode,
    )
    return jsonify({"ok": True})


@app.route("/", methods=["GET", "POST"])
@app.route("/student/login", methods=["GET", "POST"])
def student_login():
    error = None
    otp_step = False
    login_value = ""
    resend_available_at = ""

    if request.method == "POST":
        action = request.form.get("action")
        login_value = request.form.get("identifier", "").strip()
        normalized_email = normalize_student_identifier(login_value)

        if action == "send_login_otp":
            raw_password = request.form.get("password", "")
            password = hash_password(raw_password)
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT u.id, u.password, s.student_id, s.failed_attempts, s.locked_until
                FROM users u
                JOIN student_details s ON s.user_id = u.id
                WHERE u.email = ? AND u.role = 'student'
                """,
                (normalized_email,),
            )
            user = cursor.fetchone()
            if user and is_account_locked(user["locked_until"]):
                conn.close()
                log_login_attempt(user["student_id"] or normalized_email, "student", False)
                error = "Account locked. Try again after 15 minutes."
            elif not user or user["password"] != password:
                locked_now = False
                if user:
                    locked_now = mark_failed_login(cursor, "student_details", user["id"])
                    conn.commit()
                conn.close()
                log_login_attempt(user["student_id"] if user else normalized_email, "student", False)
                error = "Account locked. Try again after 15 minutes." if locked_now else "Invalid student ID or password."
            else:
                conn.close()
                otp_code = create_otp_record(normalized_email, "student_login", user["id"])
                if send_otp_email(normalized_email, otp_code, "student_login"):
                    session["student_pre_auth_user_id"] = user["id"]
                    session["student_pre_auth_email"] = normalized_email
                    session["student_pre_auth_identifier"] = user["student_id"]
                    otp_step = True
                    resend_available_at = (now_utc() + timedelta(seconds=45)).isoformat()
                else:
                    error = "Could not send OTP. Please try again."

        elif action == "resend_login_otp":
            normalized_email = session.get("student_pre_auth_email")
            user_id = session.get("student_pre_auth_user_id")
            login_value = session.get("student_pre_auth_identifier", login_value)
            if not normalized_email or not user_id:
                error = "Session expired. Please login again."
            else:
                otp_code = create_otp_record(normalized_email, "student_login", user_id)
                send_otp_email(normalized_email, otp_code, "student_login")
                otp_step = True
                resend_available_at = (now_utc() + timedelta(seconds=45)).isoformat()
                flash("OTP resent successfully.", "success")

        elif action == "verify_login_otp":
            otp_step = True
            normalized_email = session.get("student_pre_auth_email")
            user_id = session.get("student_pre_auth_user_id")
            login_value = session.get("student_pre_auth_identifier", login_value)
            otp_code = request.form.get("otp", "").strip()
            resend_available_at = request.form.get("resend_available_at", "")
            if not normalized_email or not user_id:
                error = "Session expired. Please login again."
            elif not validate_otp(normalized_email, "student_login", otp_code):
                error = "Invalid or expired OTP."
            else:
                conn = get_db_connection()
                cursor = conn.cursor()
                reset_failed_logins(cursor, "student_details", user_id)
                conn.commit()
                conn.close()
                session.pop("student_pre_auth_email", None)
                session.pop("student_pre_auth_user_id", None)
                session.pop("student_pre_auth_identifier", None)
                set_permanent_session("student", user_id)
                log_login_attempt(session["user_id"], "student", True)
                session["new_login_location"] = has_new_login_location(user_id, "student")
                return redirect(url_for("student_dashboard"))

    if session.get("role") == "student":
        return redirect(url_for("student_dashboard"))

    return render_template(
        "login_student.html",
        error=error,
        otp_step=otp_step,
        login_value=login_value,
        resend_available_at=resend_available_at,
        otp_target=session.get("student_pre_auth_identifier", login_value),
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = hash_password(request.form.get("password", ""))
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT u.id, u.password, a.status, a.locked_until
            FROM users u
            JOIN admin_profiles a ON a.user_id = u.id
            WHERE u.email = ? AND u.role = 'admin'
            """,
            (email,),
        )
        admin = cursor.fetchone()
        if admin and is_account_locked(admin["locked_until"]):
            conn.close()
            log_login_attempt(email, "admin", False)
            error = "Account locked. Try again after 15 minutes."
        elif not admin or admin["password"] != password:
            locked_now = False
            if admin:
                locked_now = mark_failed_login(cursor, "admin_profiles", admin["id"])
                conn.commit()
            conn.close()
            log_login_attempt(email, "admin", False)
            error = "Account locked. Try again after 15 minutes." if locked_now else "Invalid admin credentials."
        elif (admin["status"] or "active").lower() != "active":
            conn.close()
            log_login_attempt(email, "admin", False)
            error = "This admin account is inactive."
        else:
            reset_failed_logins(cursor, "admin_profiles", admin["id"])
            conn.commit()
            conn.close()
            set_permanent_session("admin", admin["id"])
            log_login_attempt(session["user_id"], "admin", True)
            return redirect(url_for("school_admin_dashboard"))
    return render_template("login_admin.html", mode="admin", error=error)


@app.route("/superadmin/login", methods=["GET", "POST"])
def superadmin_login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = hash_password(request.form.get("password", ""))
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM users WHERE email = ? AND password = ? AND role = 'superadmin'",
            (email, password),
        )
        user = cursor.fetchone()
        conn.close()
        if not user:
            log_login_attempt(email, "superadmin", False)
            error = "Invalid super admin credentials."
        else:
            set_permanent_session("superadmin", user["id"])
            log_login_attempt(session["user_id"], "superadmin", True)
            return redirect(url_for("superadmin_dashboard"))
    return render_template("login_admin.html", mode="superadmin", error=error)


@app.route("/student/forgot-password", methods=["GET", "POST"])
def student_forgot_password():
    otp_step = False
    identifier = ""
    if request.method == "POST":
        action = request.form.get("action")
        identifier = request.form.get("identifier", "").strip()
        normalized_email = normalize_student_identifier(identifier)
        if action == "send_reset_otp":
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT u.id, s.student_id
                FROM users u
                JOIN student_details s ON s.user_id = u.id
                WHERE u.email = ? AND u.role = 'student'
                """,
                (normalized_email,),
            )
            user = cursor.fetchone()
            conn.close()
            if not user:
                flash("No student account found for that ID.", "error")
            else:
                otp_code = create_otp_record(normalized_email, "student_reset", user["id"])
                send_otp_email(normalized_email, otp_code, "student_reset")
                session["student_reset_email"] = normalized_email
                session["student_reset_identifier"] = user["student_id"]
                otp_step = True
                flash("Reset OTP generated. Check terminal output.", "success")
        elif action == "reset_password":
            otp_step = True
            normalized_email = session.get("student_reset_email")
            identifier = session.get("student_reset_identifier", identifier)
            otp_code = request.form.get("otp", "").strip()
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            if new_password != confirm_password:
                flash("Passwords do not match.", "error")
            elif not validate_otp(normalized_email, "student_reset", otp_code):
                flash("Invalid or expired OTP.", "error")
            else:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET password = ? WHERE email = ?",
                    (hash_password(new_password), normalized_email),
                )
                cursor.execute(
                    """
                    UPDATE student_details
                    SET login_password = ?
                    WHERE user_id = (SELECT id FROM users WHERE email = ?)
                    """,
                    (new_password, normalized_email),
                )
                conn.commit()
                conn.close()
                session.pop("student_reset_email", None)
                session.pop("student_reset_identifier", None)
                flash("Password reset successful. Please login again.", "success")
                return redirect(url_for("student_login"))
    return render_template(
        "forgot_password.html",
        otp_step=otp_step,
        identifier=identifier,
        panel_subtitle="Student password recovery",
        step_one_label="Enter student ID",
        identifier_label="Student ID / Username",
        identifier_placeholder="Enter student ID",
        back_url=url_for("student_login"),
    )


@app.route("/admin/forgot-password", methods=["GET", "POST"])
def admin_forgot_password():
    otp_step = False
    identifier = ""
    if request.method == "POST":
        action = request.form.get("action")
        identifier = request.form.get("identifier", "").strip().lower()
        if action == "send_reset_otp":
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT u.id, u.email
                FROM users u
                LEFT JOIN admin_profiles a ON a.user_id = u.id
                WHERE u.email = ? AND u.role = 'admin'
                """,
                (identifier,),
            )
            user = cursor.fetchone()
            conn.close()
            if not user:
                flash("No admin account found for that email.", "error")
            else:
                otp_code = create_otp_record(identifier, "admin_reset", user["id"])
                send_otp_email(identifier, otp_code, "admin_reset")
                session["admin_reset_email"] = identifier
                otp_step = True
                flash("Reset OTP generated. Check terminal output.", "success")
        elif action == "reset_password":
            otp_step = True
            identifier = session.get("admin_reset_email", identifier)
            otp_code = request.form.get("otp", "").strip()
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            if new_password != confirm_password:
                flash("Passwords do not match.", "error")
            elif not validate_otp(identifier, "admin_reset", otp_code):
                flash("Invalid or expired OTP.", "error")
            else:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET password = ? WHERE email = ? AND role = 'admin'",
                    (hash_password(new_password), identifier),
                )
                conn.commit()
                conn.close()
                session.pop("admin_reset_email", None)
                flash("Password reset successful. Please login again.", "success")
                return redirect(url_for("admin_login"))
    return render_template(
        "forgot_password.html",
        otp_step=otp_step,
        identifier=identifier,
        panel_subtitle="School admin password recovery",
        step_one_label="Enter admin email",
        identifier_label="Admin Email",
        identifier_placeholder="Enter admin email",
        back_url=url_for("admin_login"),
    )


@app.route("/superadmin/forgot-password", methods=["GET", "POST"])
def superadmin_forgot_password():
    otp_step = False
    identifier = ""
    if request.method == "POST":
        action = request.form.get("action")
        identifier = request.form.get("identifier", "").strip().lower()
        if action == "send_reset_otp":
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, email FROM users WHERE email = ? AND role = 'superadmin'",
                (identifier,),
            )
            user = cursor.fetchone()
            conn.close()
            if not user:
                flash("No super admin account found for that email.", "error")
            else:
                otp_code = create_otp_record(identifier, "superadmin_reset", user["id"])
                send_otp_email(identifier, otp_code, "superadmin_reset")
                session["superadmin_reset_email"] = identifier
                otp_step = True
                flash("Reset OTP generated. Check terminal output.", "success")
        elif action == "reset_password":
            otp_step = True
            identifier = session.get("superadmin_reset_email", identifier)
            otp_code = request.form.get("otp", "").strip()
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            if new_password != confirm_password:
                flash("Passwords do not match.", "error")
            elif not validate_otp(identifier, "superadmin_reset", otp_code):
                flash("Invalid or expired OTP.", "error")
            else:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET password = ? WHERE email = ? AND role = 'superadmin'",
                    (hash_password(new_password), identifier),
                )
                conn.commit()
                conn.close()
                session.pop("superadmin_reset_email", None)
                flash("Password reset successful. Please login again.", "success")
                return redirect(url_for("superadmin_login"))
    return render_template(
        "forgot_password.html",
        otp_step=otp_step,
        identifier=identifier,
        panel_subtitle="Super admin password recovery",
        step_one_label="Enter super admin email",
        identifier_label="Super Admin Email",
        identifier_placeholder="Enter super admin email",
        back_url=url_for("superadmin_login"),
    )


@app.route("/student/dashboard")
def student_dashboard():
    guard = require_role("student")
    if guard:
        return guard
    student = get_current_student()
    if not student:
        return missing_profile_redirect("Student profile was not found.")
    conn = get_db_connection()
    cursor = conn.cursor()
    qr_token, qr_expires_at = refresh_student_qr_token(cursor, session["user_id"], force=True)
    cursor.execute(
        """
        SELECT id, document_type, file_name, file_size, uploaded_at, doc_status
        FROM uploaded_documents
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 5
        """,
        (session["user_id"],),
    )
    recent_documents = cursor.fetchall()
    cursor.execute(
        "SELECT COUNT(*) AS count FROM student_tasks WHERE user_id = ? AND is_done = 0",
        (session["user_id"],),
    )
    task_count = cursor.fetchone()["count"]
    conn.commit()
    conn.close()
    return render_template(
        "student_dashboard.html",
        student=student,
        recent_documents=recent_documents,
        task_count=task_count,
        qr_b64=generate_qr(qr_token),
        public_verify_url=get_public_verify_url(qr_token),
        qr_expires_at=qr_expires_at,
        recent_logins=get_recent_successful_logins(session["user_id"], "student"),
        new_login_location=session.pop("new_login_location", False),
        sidebar_links=student_sidebar(),
        active_endpoint="student_dashboard",
    )


@app.route("/student/upload", methods=["GET", "POST"])
def student_upload():
    guard = require_role("student")
    if guard:
        return guard
    student = get_current_student()
    if not student:
        return missing_profile_redirect("Student profile was not found.")
    if request.method == "POST":
        document_type = request.form.get("document_type", "").strip()
        upload_file = request.files.get("document")
        if not document_type:
            flash("Document type is required.", "error")
        elif not upload_file or not upload_file.filename:
            flash("Please choose a file to upload.", "error")
        elif not allowed_file(upload_file.filename):
            flash("Unsupported file format. Use PNG, JPG, PDF, or DOCX.", "error")
        else:
            file_bytes = upload_file.read()
            if len(file_bytes) > app.config["MAX_CONTENT_LENGTH"]:
                flash("File is too large. Maximum size is 100MB.", "error")
            else:
                file_hash = hashlib.sha256(file_bytes).hexdigest()
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO uploaded_documents
                    (user_id, document_type, file_name, file_size, content_type, file_data, uploaded_at, file_hash, doc_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending')
                    """,
                    (
                        session["user_id"],
                        document_type,
                        upload_file.filename,
                        len(file_bytes),
                        upload_file.mimetype,
                        file_bytes,
                        now_utc().isoformat(),
                        file_hash,
                    ),
                )
                doc_id = cursor.lastrowid
                saved_path = save_document_file(doc_id, upload_file.filename, file_bytes)
                cursor.execute("UPDATE uploaded_documents SET file_path = ? WHERE id = ?", (saved_path, doc_id))
                sync_student_verification_from_documents(cursor, session["user_id"])
                conn.commit()
                conn.close()
                flash("Document uploaded successfully.", "success")
                return redirect(url_for("student_upload"))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, document_type, file_name, file_size, uploaded_at, doc_status, doc_rejection_reason
        FROM uploaded_documents
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (session["user_id"],),
    )
    documents = []
    for row in cursor.fetchall():
        item = dict(row)
        item["integrity_ok"] = verify_file_hash(row["id"])
        documents.append(item)
    rejected_documents = [item for item in documents if (item.get("doc_status") or "Pending").lower() == "rejected"]
    conn.close()
    return render_template(
        "student_upload.html",
        student=student,
        documents=documents,
        rejected_documents=rejected_documents,
        sidebar_links=student_sidebar(),
        active_endpoint="student_upload",
    )


@app.route("/student/documents/<int:doc_id>/download")
def download_document(doc_id):
    guard = require_role("student")
    if guard:
        return guard
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT file_name, content_type, file_data
        FROM uploaded_documents
        WHERE id = ? AND user_id = ?
        """,
        (doc_id, session["user_id"]),
    )
    doc = cursor.fetchone()
    conn.close()
    if not doc:
        flash("Document not found.", "error")
        return redirect(url_for("student_upload"))
    return send_file(
        io.BytesIO(doc["file_data"]),
        mimetype=doc["content_type"] or "application/octet-stream",
        as_attachment=True,
        download_name=doc["file_name"],
    )


@app.route("/admin/documents/<int:doc_id>/preview")
def preview_document(doc_id):
    guard = require_role("admin")
    if guard:
        return guard
    admin = get_current_admin_profile()
    if not admin:
        return missing_profile_redirect("Admin profile was not found.")
    document = load_uploaded_document(doc_id, admin["school_id"])
    if not document:
        flash("Document not found.", "error")
        return redirect(url_for("manage_students"))
    file_bytes = resolve_document_bytes(document)
    if file_bytes is None:
        flash("Document file is unavailable.", "error")
        return redirect(url_for("manage_students"))
    content_type = document["content_type"] or mimetypes.guess_type(document["file_name"] or "")[0] or "application/octet-stream"
    return send_file(
        io.BytesIO(file_bytes),
        mimetype=content_type,
        as_attachment=False,
        download_name=document["file_name"],
    )


@app.route("/student/documents/<int:doc_id>/delete", methods=["POST"])
def delete_document(doc_id):
    guard = require_role("student")
    if guard:
        return guard
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM uploaded_documents WHERE id = ? AND user_id = ?", (doc_id, session["user_id"]))
    document = cursor.fetchone()
    cursor.execute(
        "DELETE FROM uploaded_documents WHERE id = ? AND user_id = ?",
        (doc_id, session["user_id"]),
    )
    sync_student_verification_from_documents(cursor, session["user_id"])
    conn.commit()
    conn.close()
    if document and document["file_path"]:
        absolute_path = os.path.join(os.getcwd(), document["file_path"].replace("/", os.sep))
        if os.path.exists(absolute_path):
            os.remove(absolute_path)
    flash("Document deleted.", "success")
    return redirect(url_for("student_upload"))


@app.route("/student/notifications/<int:doc_id>/dismiss", methods=["POST"])
def dismiss_student_notification(doc_id):
    guard = require_role("student")
    if guard:
        return guard
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE uploaded_documents
        SET student_notification_hidden = 1
        WHERE id = ? AND user_id = ?
        """,
        (doc_id, session["user_id"]),
    )
    conn.commit()
    conn.close()
    flash("Notification removed.", "success")
    return redirect(request.referrer or url_for("student_dashboard"))


@app.route("/student/notifications/<int:doc_id>/view")
def view_student_notification(doc_id):
    guard = require_role("student")
    if guard:
        return guard
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE uploaded_documents
        SET student_notification_hidden = 1
        WHERE id = ? AND user_id = ?
        """,
        (doc_id, session["user_id"]),
    )
    conn.commit()
    conn.close()
    flash("Opening uploads.", "success")
    return redirect(url_for("student_upload"))


@app.route("/student/tasks", methods=["GET", "POST"])
def student_tasks():
    guard = require_role("student")
    if guard:
        return guard
    student = get_current_student()
    if not student:
        return missing_profile_redirect("Student profile was not found.")
    if request.method == "POST":
        action = request.form.get("action")
        conn = get_db_connection()
        cursor = conn.cursor()
        if action == "add":
            title = request.form.get("title", "").strip()
            deadline_at = request.form.get("deadline_at", "").strip() or None
            if not title:
                flash("Task description is required.", "error")
            elif not deadline_at:
                flash("Deadline is required.", "error")
            else:
                deadline_dt = parse_local_naive_datetime(deadline_at)
                if not deadline_dt:
                    flash("Invalid deadline format.", "error")
                elif deadline_dt <= now_local_naive():
                    flash("Deadline must be in the future.", "error")
                else:
                    deadline_storage = deadline_dt.strftime("%Y-%m-%dT%H:%M:%S")
                    cursor.execute(
                        """
                        INSERT INTO student_tasks (user_id, title, deadline_at, is_done, created_at)
                        VALUES (?, ?, ?, 0, ?)
                        """,
                        (session["user_id"], title, deadline_storage, now_utc().isoformat()),
                    )
                    conn.commit()
                    flash("Task added.", "success")
        elif action == "toggle":
            task_id = request.form.get("task_id", "").strip()
            if not task_id.isdigit():
                flash("Invalid task selection.", "error")
                conn.close()
                return redirect(url_for("student_tasks"))
            cursor.execute(
                """
                UPDATE student_tasks
                SET is_done = CASE WHEN is_done = 1 THEN 0 ELSE 1 END
                WHERE id = ? AND user_id = ?
                """,
                (task_id, session["user_id"]),
            )
            conn.commit()
            if cursor.rowcount:
                flash("Task updated.", "success")
            else:
                flash("Task not found.", "error")
        elif action == "delete":
            task_id = request.form.get("task_id", "").strip()
            if not task_id.isdigit():
                flash("Invalid task selection.", "error")
                conn.close()
                return redirect(url_for("student_tasks"))
            cursor.execute(
                "DELETE FROM student_tasks WHERE id = ? AND user_id = ?",
                (task_id, session["user_id"]),
            )
            conn.commit()
            if cursor.rowcount:
                flash("Task deleted.", "success")
            else:
                flash("Task not found.", "error")
        conn.close()
        return redirect(url_for("student_tasks"))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, title, deadline_at, is_done, created_at
        FROM student_tasks
        WHERE user_id = ?
        ORDER BY is_done ASC, COALESCE(deadline_at, created_at) ASC, id DESC
        """,
        (session["user_id"],),
    )
    now_local = now_local_naive()
    tasks = []
    for row in cursor.fetchall():
        task = dict(row)
        deadline_dt = parse_local_naive_datetime(task.get("deadline_at"))
        task["is_overdue"] = bool(deadline_dt and deadline_dt < now_local and not task.get("is_done"))
        tasks.append(task)
    conn.close()
    return render_template(
        "student_tasks.html",
        student=student,
        tasks=tasks,
        now_iso=now_local.isoformat(),
        min_deadline_at=datetime.now().strftime("%Y-%m-%dT%H:%M"),
        sidebar_links=student_sidebar(),
        active_endpoint="student_tasks",
    )


@app.route("/student/portals")
def student_portals():
    guard = require_role("student")
    if guard:
        return guard
    student = get_current_student()
    if not student:
        return missing_profile_redirect("Student profile was not found.")
    portals = [
        {"title": "DIKSHA", "tag": "Learning", "description": "National digital infrastructure for school education", "url": "https://diksha.gov.in/"},
        {"title": "SWAYAM", "tag": "Courses", "description": "Government online courses and certification platform", "url": "https://swayam.gov.in/"},
        {"title": "National Scholarship Portal", "tag": "Scholarships", "description": "Centralized scholarship applications and status tracking", "url": "https://www.scholarships.gov.in/"},
        {"title": "National Career Service", "tag": "Career", "description": "Career guidance, skill opportunities, and job search resources", "url": "https://www.ncs.gov.in/"},
    ]
    return render_template(
        "student_portals.html",
        student=student,
        portals=portals,
        sidebar_links=student_sidebar(),
        active_endpoint="student_portals",
    )


@app.route("/student/id-card")
def student_id_card():
    guard = require_role("student")
    if guard:
        return guard
    student = get_current_student()
    if not student:
        return missing_profile_redirect("Student profile was not found.")
    conn = get_db_connection()
    cursor = conn.cursor()
    qr_token, qr_expires_at = refresh_student_qr_token(cursor, session["user_id"], force=True)
    conn.commit()
    conn.close()
    return render_template(
        "student_id_card.html",
        student=student,
        qr_b64=generate_qr(qr_token),
        public_verify_url=get_public_verify_url(qr_token),
        qr_expires_at=qr_expires_at,
        sidebar_links=student_sidebar(),
        active_endpoint="student_id_card",
    )


@app.route("/student/id-card/refresh-qr", methods=["POST"])
def refresh_student_id_qr():
    guard = require_role("student")
    if guard:
        return guard
    conn = get_db_connection()
    cursor = conn.cursor()
    refresh_student_qr_token(cursor, session["user_id"], force=True)
    conn.commit()
    conn.close()
    flash("QR code refreshed successfully.", "success")
    return redirect(url_for("student_id_card"))


@app.route("/student/qr-detail")
def student_qr_detail():
    guard = require_role("student")
    if guard:
        return guard
    student = get_current_student()
    if not student:
        return missing_profile_redirect("Student profile was not found.")
    conn = get_db_connection()
    cursor = conn.cursor()
    qr_token, qr_expires_at = refresh_student_qr_token(cursor, session["user_id"], force=False)
    cursor.execute(
        """
        SELECT document_type
        FROM uploaded_documents
        WHERE user_id = ? AND COALESCE(doc_status, 'Pending') = 'Verified'
        ORDER BY id ASC
        """,
        (session["user_id"],),
    )
    verified_documents = cursor.fetchall()
    conn.commit()
    conn.close()
    return render_template(
        "public_verify.html",
        student=student,
        verification_timestamp=format_timestamp(student["verification_updated_at"]),
        public_verify_url=get_public_verify_url(qr_token),
        verified_documents=verified_documents,
        verification_scan_count=0,
        qr_expired=False,
        qr_expires_at=qr_expires_at,
        verified_by_admin_name=student["verified_by_admin_name"],
        title="Identity Verification",
    )


@app.route("/verify/<qr_token>")
def verify_student(qr_token):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT s.*, v.status AS verification_status, v.updated_at AS verification_updated_at,
               a.name AS verified_by_admin_name
        FROM student_details s
        LEFT JOIN (
            SELECT vs.user_id, vs.status, vs.updated_at, vs.updated_by_admin_id
            FROM verification_status vs
            INNER JOIN (
                SELECT user_id, MAX(id) AS latest_id
                FROM verification_status
                GROUP BY user_id
            ) latest ON latest.latest_id = vs.id
        ) v ON v.user_id = s.user_id
        LEFT JOIN admin_profiles a ON a.user_id = v.updated_by_admin_id
        WHERE s.qr_token = ?
        """,
        (qr_token,),
    )
    student = cursor.fetchone()
    if not student:
        conn.close()
        abort(404)
    cursor.execute(
        """
        INSERT INTO verification_scans (student_id, viewed_by, viewer_role, ip_address, user_agent)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            student["student_id"],
            str(session.get("user_id") or session.get("student_id") or session.get("admin_id") or "unknown"),
            session.get("role", "unknown"),
            request.remote_addr or "",
            request.user_agent.string or "",
        ),
    )
    cursor.execute("SELECT COUNT(*) AS count FROM verification_scans WHERE student_id = ?", (student["student_id"],))
    verification_scan_count = cursor.fetchone()["count"]
    qr_expired = bool(parse_datetime(student["qr_expires_at"]) and parse_datetime(student["qr_expires_at"]) <= now_utc())
    verified_documents = []
    if not qr_expired:
        cursor.execute(
            """
            SELECT document_type
            FROM uploaded_documents
            WHERE user_id = ? AND COALESCE(doc_status, 'Pending') = 'Verified'
            ORDER BY id ASC
            """,
            (student["user_id"],),
        )
        verified_documents = cursor.fetchall()
    conn.commit()
    conn.close()
    return render_template(
        "public_verify.html",
        student=None if qr_expired else student,
        verification_timestamp=format_timestamp(student["verification_updated_at"]),
        public_verify_url=get_public_verify_url(qr_token),
        verified_documents=verified_documents,
        verification_scan_count=verification_scan_count,
        qr_expired=qr_expired,
        qr_expires_at=student["qr_expires_at"],
        verified_by_admin_name=student["verified_by_admin_name"],
        title="Identity Verification",
    )


@app.route("/admin/dashboard")
def school_admin_dashboard():
    guard = require_role("admin")
    if guard:
        return guard
    admin = get_current_admin_profile()
    if not admin:
        return missing_profile_redirect("Admin profile was not found.")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS total FROM student_details WHERE school_id = ?", (admin["school_id"],))
    total_students = cursor.fetchone()["total"]
    distribution = {}
    cursor.execute(
        """
        SELECT class_name, COUNT(*) AS total
        FROM student_details
        WHERE school_id = ?
        GROUP BY class_name
        """,
        (admin["school_id"],),
    )
    for row in cursor.fetchall():
        distribution[row["class_name"]] = row["total"]
    cursor.execute(
        """
        SELECT s.name AS student_name, s.student_id, vs.viewed_by, vs.viewer_role, vs.scanned_at, vs.ip_address
        FROM verification_scans vs
        JOIN student_details s ON s.student_id = vs.student_id
        WHERE s.school_id = ?
          AND datetime(vs.scanned_at) >= datetime('now', '-1 day')
        ORDER BY vs.id DESC
        LIMIT 10
        """,
        (admin["school_id"],),
    )
    recent_scans = cursor.fetchall()
    conn.close()
    classes = []
    for standard in range(1, 13):
        for section in ["A", "B"]:
            label = f"{standard}-{section}"
            classes.append({"label": label, "count": distribution.get(label, 0)})
    return render_template(
        "admin_dashboard.html",
        admin=admin,
        total_students=total_students,
        classes=classes,
        recent_scans=recent_scans,
        sidebar_links=admin_sidebar(),
        active_endpoint="school_admin_dashboard",
    )


@app.route("/admin/students", methods=["GET", "POST"])
def manage_students():
    guard = require_role("admin")
    if guard:
        return guard
    admin = get_current_admin_profile()
    if not admin:
        return missing_profile_redirect("Admin profile was not found.")
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        student_id = request.form.get("student_id", "").strip().upper()
        emis_id = request.form.get("emis_id", "").strip()
        school_info = request.form.get("school_info", "").strip() or admin["school_name"]
        class_name = request.form.get("class_name", "").strip()
        parent_mobile = request.form.get("parent_mobile", "").strip()
        dob = normalize_date_storage(request.form.get("dob", "").strip())
        raw_password = request.form.get("login_password", "").strip()
        status = request.form.get("status", "Pending").strip().title()
        rejection_reason = request.form.get("rejection_reason", "").strip() or None
        cursor.execute(
            "SELECT id FROM student_details WHERE student_id = ? OR emis_id = ?",
            (student_id, emis_id),
        )
        if cursor.fetchone():
            flash("Student ID or EMIS ID already exists.", "error")
        elif not all([name, student_id, emis_id, class_name, parent_mobile, dob, raw_password]):
            flash("All student fields are required.", "error")
        else:
            email = build_student_login_email(student_id)
            cursor.execute(
                "INSERT INTO users (email, password, role) VALUES (?, ?, 'student')",
                (email, hash_password(raw_password)),
            )
            user_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO student_details
                (user_id, name, course, register_number, year_of_study, current_semester, arrear_count,
                 boarding_status, mentor_name, attendance_percentage, sgpa_history, sgpa, cgpa, student_id,
                 dob, emis_id, parent_mobile, school_info, class_name, school_id, login_password)
                VALUES (?, ?, ?, ?, ?, ?, 0, 'Day Scholar', 'School Mentor', 0, '', 0, 0, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    name,
                    admin["school_name"],
                    student_id,
                    parse_year_from_class(class_name),
                    class_name,
                    student_id,
                    dob,
                    emis_id,
                    parent_mobile,
                    admin["school_name"],
                    class_name,
                    admin["school_id"],
                    raw_password,
                ),
            )
            cursor.execute(
                "UPDATE student_details SET rejection_reason = ?, qr_token = ?, qr_expires_at = ? WHERE user_id = ?",
                (
                    rejection_reason if status == "Rejected" else None,
                    str(uuid4()),
                    (now_utc() + timedelta(hours=24)).isoformat(),
                    user_id,
                ),
            )
            set_verification_status(cursor, user_id, status, updated_by_admin_id=session["user_id"])
            conn.commit()
            log_action(session["user_id"], "add student", student_id, f"Created student with status {status}", admin["school_id"])
            flash("Student added successfully.", "success")
            conn.close()
            return redirect(url_for("manage_students"))
    query = request.args.get("q", "").strip()
    sql = """
        SELECT
            s.id,
            s.student_id,
            s.name,
            s.emis_id,
            s.school_info,
            s.class_name,
            s.parent_mobile,
            s.dob,
            s.login_password,
            s.rejection_reason,
            v.status
        FROM student_details s
        LEFT JOIN (
            SELECT vs.user_id, vs.status
            FROM verification_status vs
            INNER JOIN (
                SELECT user_id, MAX(id) AS latest_id
                FROM verification_status
                GROUP BY user_id
            ) latest ON latest.latest_id = vs.id
        ) v ON v.user_id = s.user_id
        WHERE s.school_id = ?
    """
    params = [admin["school_id"]]
    if query:
        sql += " AND (s.student_id LIKE ? OR s.name LIKE ? OR s.emis_id LIKE ? OR s.school_info LIKE ? OR v.status LIKE ?)"
        like_query = f"%{query}%"
        params.extend([like_query, like_query, like_query, like_query, like_query])
    sql += " ORDER BY s.student_id ASC"
    cursor.execute(sql, params)
    students = cursor.fetchall()
    conn.close()
    return render_template(
        "manage_students.html",
        admin=admin,
        students=students,
        search_query=query,
        sidebar_links=admin_sidebar(),
        active_endpoint="manage_students",
    )


@app.route("/admin/students/<int:student_row_id>/edit", methods=["GET", "POST"])
def edit_student(student_row_id):
    guard = require_role("admin")
    if guard:
        return guard
    admin = get_current_admin_profile()
    if not admin:
        return missing_profile_redirect("Admin profile was not found.")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT s.*, v.status
        FROM student_details s
        LEFT JOIN (
            SELECT vs.user_id, vs.status
            FROM verification_status vs
            INNER JOIN (
                SELECT user_id, MAX(id) AS latest_id
                FROM verification_status
                GROUP BY user_id
            ) latest ON latest.latest_id = vs.id
        ) v ON v.user_id = s.user_id
        WHERE s.id = ? AND s.school_id = ?
        """,
        (student_row_id, admin["school_id"]),
    )
    student = cursor.fetchone()
    if not student:
        conn.close()
        flash("Student not found.", "error")
        return redirect(url_for("manage_students"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        student_id = request.form.get("student_id", "").strip().upper()
        emis_id = request.form.get("emis_id", "").strip()
        school_info = request.form.get("school_info", "").strip() or admin["school_name"]
        class_name = request.form.get("class_name", "").strip()
        parent_mobile = request.form.get("parent_mobile", "").strip()
        dob = normalize_date_storage(request.form.get("dob", "").strip())
        raw_password = request.form.get("login_password", "").strip()
        status = request.form.get("status", "Pending").strip().title()
        rejection_reason = request.form.get("rejection_reason", "").strip() or None
        cursor.execute(
            "SELECT id FROM student_details WHERE id != ? AND (student_id = ? OR emis_id = ?)",
            (student_row_id, student_id, emis_id),
        )
        if cursor.fetchone():
            flash("Student ID or EMIS ID already belongs to another student.", "error")
        else:
            email = build_student_login_email(student_id)
            cursor.execute(
                "UPDATE users SET email = ?, password = ? WHERE id = ?",
                (email, hash_password(raw_password), student["user_id"]),
            )
            cursor.execute(
                """
                UPDATE student_details
                SET name = ?, course = ?, register_number = ?, year_of_study = ?, current_semester = ?,
                    student_id = ?, emis_id = ?, parent_mobile = ?, dob = ?, school_info = ?, class_name = ?,
                    school_id = ?, login_password = ?
                WHERE id = ?
                """,
                (
                    name,
                    admin["school_name"],
                    student_id,
                    parse_year_from_class(class_name),
                    class_name,
                    student_id,
                    emis_id,
                    parent_mobile,
                    dob,
                    school_info,
                    class_name,
                    admin["school_id"],
                    raw_password,
                    student_row_id,
                ),
            )
            cursor.execute(
                "UPDATE student_details SET rejection_reason = ? WHERE id = ?",
                (rejection_reason if status == "Rejected" else None, student_row_id),
            )
            set_verification_status(cursor, student["user_id"], status, updated_by_admin_id=session["user_id"])
            conn.commit()
            log_action(session["user_id"], "update student", student_id, f"Updated profile and set status {status}", admin["school_id"])
            if status == "Verified":
                log_action(session["user_id"], "verify", student_id, "Marked student as verified", admin["school_id"])
            elif status == "Rejected":
                log_action(session["user_id"], "reject", student_id, rejection_reason or "Marked student as rejected", admin["school_id"])
            flash("Student updated successfully.", "success")
            return_q = request.form.get("return_q", "").strip()
            conn.close()
            if return_q:
                return redirect(url_for("manage_students", q=return_q))
            return redirect(url_for("manage_students"))
    cursor.execute(
        """
        SELECT id, document_type, file_name, uploaded_at, doc_status, doc_rejection_reason
        FROM uploaded_documents
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (student["user_id"],),
    )
    documents = cursor.fetchall()
    conn.close()
    return render_template(
        "edit_student.html",
        admin=admin,
        student=student,
        documents=documents,
        sidebar_links=admin_sidebar(),
        active_endpoint="manage_students",
    )


@app.route("/admin/documents/<int:doc_id>/review", methods=["POST"])
def review_student_document(doc_id):
    guard = require_role("admin")
    if guard:
        return guard
    admin = get_current_admin_profile()
    if not admin:
        return missing_profile_redirect("Admin profile was not found.")
    action = request.form.get("doc_action", "").strip().lower()
    rejection_reason = request.form.get("doc_rejection_reason", "").strip() or None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT d.id, d.document_type, s.user_id, s.student_id
        FROM uploaded_documents d
        JOIN student_details s ON s.user_id = d.user_id
        WHERE d.id = ? AND s.school_id = ?
        """,
        (doc_id, admin["school_id"]),
    )
    document = cursor.fetchone()
    if not document:
        conn.close()
        flash("Document not found.", "error")
        return redirect(url_for("manage_students"))

    # Project rule: document review should only affect document status.
    # Keep dashboard/global verification as Verified.
    def enforce_verified_global_status():
        set_verification_status(cursor, document["user_id"], "Verified", updated_by_admin_id=session["user_id"])

    if action == "approve":
        cursor.execute(
            """
            UPDATE uploaded_documents
            SET doc_status = 'Verified', doc_rejection_reason = NULL, verified_at = ?, verified_by_admin_id = ?,
                student_notification_hidden = 0
            WHERE id = ?
            """,
            (now_utc().isoformat(), session["user_id"], doc_id),
        )
        enforce_verified_global_status()
        conn.commit()
        conn.close()
        approved_doc_type = (document["document_type"] or "").strip() if document["document_type"] is not None else ""
        if not approved_doc_type or approved_doc_type.lower() in {"none", "null", "nil", "n/a", "na"}:
            approved_doc_type = "Unknown Document"
        log_action(session["user_id"], "verify", document["student_id"], f"Approved document: {approved_doc_type}", admin["school_id"])
        flash("Document approved.", "success")
    elif action == "reject":
        cursor.execute(
            """
            UPDATE uploaded_documents
            SET doc_status = 'Rejected', doc_rejection_reason = ?, verified_at = NULL, verified_by_admin_id = ?,
                student_notification_hidden = 0
            WHERE id = ?
            """,
            (rejection_reason, session["user_id"], doc_id),
        )
        enforce_verified_global_status()
        conn.commit()
        conn.close()
        rejected_doc_type = (document["document_type"] or "").strip() if document["document_type"] is not None else ""
        if not rejected_doc_type or rejected_doc_type.lower() in {"none", "null", "nil", "n/a", "na"}:
            rejected_doc_type = "Unknown Document"
        log_action(
            session["user_id"],
            "reject",
            document["student_id"],
            f"Rejected document: {rejected_doc_type} | {rejection_reason or 'No reason provided'}",
            admin["school_id"],
        )
        flash("Document rejected.", "success")
    else:
        conn.close()
        flash("Invalid document action.", "error")
    return redirect(url_for("edit_student", student_row_id=request.form.get("student_row_id")))


@app.route("/admin/students/<int:student_row_id>/delete", methods=["POST"])
def delete_student(student_row_id):
    guard = require_role("admin")
    if guard:
        return guard
    admin = get_current_admin_profile()
    if not admin:
        return missing_profile_redirect("Admin profile was not found.")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, student_id FROM student_details WHERE id = ? AND school_id = ?",
        (student_row_id, admin["school_id"]),
    )
    row = cursor.fetchone()
    if row:
        user_id = row["user_id"]
        cursor.execute("SELECT file_path FROM uploaded_documents WHERE user_id = ?", (user_id,))
        file_rows = cursor.fetchall()
        cursor.execute("DELETE FROM uploaded_documents WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM student_tasks WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM verification_status WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM student_details WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        log_action(session["user_id"], "delete", row["student_id"], "Deleted student profile and related records", admin["school_id"])
        for file_row in file_rows:
            if file_row["file_path"]:
                absolute_path = os.path.join(os.getcwd(), file_row["file_path"].replace("/", os.sep))
                if os.path.exists(absolute_path):
                    os.remove(absolute_path)
        flash("Student deleted.", "success")
    else:
        flash("Student not found.", "error")
    conn.close()
    return redirect(url_for("manage_students"))


@app.route("/audit-log")
def admin_audit_log():
    role = session.get("role")
    if role not in {"admin", "superadmin"}:
        return redirect(url_for("student_login"))
    conn = get_db_connection()
    cursor = conn.cursor()
    if role == "admin":
        admin = get_current_admin_profile()
        if not admin:
            conn.close()
            return missing_profile_redirect("Admin profile was not found.")
        cursor.execute(
            """
            SELECT al.timestamp,
                   COALESCE(ap.name, 'Admin ID ' || al.admin_id, 'Unknown Admin') AS admin_name,
                   al.action,
                   al.target_student_id,
                   al.details
            FROM audit_log al
            LEFT JOIN admin_profiles ap ON CAST(al.admin_id AS INTEGER) = ap.user_id
            WHERE al.school_id = ?
              AND datetime(al.timestamp) >= datetime('now', '-24 hours')
            ORDER BY al.id DESC
            """,
            (admin["school_id"],),
        )
        logs = cursor.fetchall()
        conn.close()
        return render_template(
            "admin_audit_log.html",
            admin=admin,
            logs=logs,
            sidebar_links=admin_sidebar(),
            active_endpoint="admin_audit_log",
        )
    cursor.execute(
        """
        SELECT al.timestamp,
               COALESCE(ap.name, 'Admin ID ' || al.admin_id, 'Unknown Admin') AS admin_name,
               al.action,
               al.target_student_id,
               al.details,
               sc.name AS school_name
        FROM audit_log al
        LEFT JOIN admin_profiles ap ON CAST(al.admin_id AS INTEGER) = ap.user_id
        LEFT JOIN schools sc ON sc.id = al.school_id
        WHERE datetime(al.timestamp) >= datetime('now', '-24 hours')
        ORDER BY al.id DESC
        """,
    )
    logs = cursor.fetchall()
    conn.close()
    return render_template(
        "admin_audit_log.html",
        logs=logs,
        sidebar_links=superadmin_sidebar(),
        active_endpoint="admin_audit_log",
    )


@app.route("/superadmin/dashboard", methods=["GET", "POST"])
def superadmin_dashboard():
    guard = require_role("superadmin")
    if guard:
        return guard
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        school_id = request.form.get("school_id", "").strip()
        if not all([name, email, password, school_id]):
            flash("All school admin fields are required.", "error")
        else:
            try:
                cursor.execute(
                    "INSERT INTO users (email, password, role) VALUES (?, ?, 'admin')",
                    (email, hash_password(password)),
                )
                user_id = cursor.lastrowid
                cursor.execute(
                    """
                    INSERT INTO admin_profiles (user_id, name, school_id, status)
                    VALUES (?, ?, ?, 'active')
                    """,
                    (user_id, name, int(school_id)),
                )
                conn.commit()
                flash("School admin created successfully.", "success")
            except sqlite3.IntegrityError:
                flash("An account with that email already exists.", "error")
    cursor.execute("SELECT COUNT(*) AS total FROM student_details")
    total_students = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) AS total FROM schools")
    total_schools = cursor.fetchone()["total"]
    cursor.execute(
        """
        SELECT school_info AS school_name, COUNT(*) AS total
        FROM student_details
        GROUP BY school_info
        ORDER BY total DESC, school_info ASC
        """
    )
    top_schools = cursor.fetchall()
    cursor.execute(
        """
        SELECT a.id, a.name, u.email, s.name AS school_name, a.status
        FROM admin_profiles a
        JOIN users u ON u.id = a.user_id
        LEFT JOIN schools s ON s.id = a.school_id
        ORDER BY a.id ASC
        """
    )
    admins = cursor.fetchall()
    cursor.execute("SELECT id, name FROM schools ORDER BY id ASC")
    schools = cursor.fetchall()
    conn.close()
    return render_template(
        "superadmin_dashboard.html",
        total_students=total_students,
        total_schools=total_schools,
        top_schools=top_schools,
        admins=admins,
        schools=schools,
        sidebar_links=superadmin_sidebar(),
        active_endpoint="superadmin_dashboard",
    )


@app.route("/superadmin/admins/<int:admin_profile_id>/toggle", methods=["POST"])
def toggle_admin_status(admin_profile_id):
    guard = require_role("superadmin")
    if guard:
        return guard
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE admin_profiles
        SET status = CASE WHEN LOWER(status) = 'active' THEN 'inactive' ELSE 'active' END
        WHERE id = ?
        """,
        (admin_profile_id,),
    )
    conn.commit()
    conn.close()
    flash("School admin status updated.", "success")
    return redirect(url_for("superadmin_dashboard"))


@app.route("/superadmin/admins/<int:admin_profile_id>/delete", methods=["POST"])
def delete_admin(admin_profile_id):
    guard = require_role("superadmin")
    if guard:
        return guard
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admin_profiles WHERE id = ?", (admin_profile_id,))
    row = cursor.fetchone()
    if row:
        cursor.execute("DELETE FROM admin_profiles WHERE id = ?", (admin_profile_id,))
        cursor.execute("DELETE FROM users WHERE id = ?", (row["user_id"],))
        conn.commit()
        flash("School admin deleted.", "success")
    else:
        flash("School admin not found.", "error")
    conn.close()
    return redirect(url_for("superadmin_dashboard"))


@app.route("/login")
def legacy_login():
    return redirect(url_for("student_login"))


@app.route("/dashboard")
def legacy_dashboard():
    if session.get("role") == "student":
        return redirect(url_for("student_dashboard"))
    if session.get("role") == "admin":
        return redirect(url_for("school_admin_dashboard"))
    if session.get("role") == "superadmin":
        return redirect(url_for("superadmin_dashboard"))
    return redirect(url_for("student_login"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("student_login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)




