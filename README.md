# 🛡️ IDENZA – Secure Student Identity Verification System

IDENZA is a Flask-based web application developed to digitize student identity verification in schools and educational institutions.

It replaces slow manual verification with a secure, trackable, and multilingual workflow.

## 🚀 Live Demo

[https://secure-student-identity-verification.onrender.com](https://secure-student-identity-verification.onrender.com)

## ✨ Key Features

### 👨‍🎓 Student Module

* Secure login with password and OTP verification
* Upload student verification documents
* Track document status: Pending / Verified / Rejected
* View dashboard with profile and recent activity
* Manage tasks and deadlines
* Receive notifications for approvals, rejections, and overdue tasks
* Access digital student ID card and QR verification
* Access DIKSHA, SWAYAM, Scholarship, and Career portals

### 🏫 School Admin Module

* Manage students within school scope
* Add, edit, and delete student profiles
* Review uploaded student documents
* Approve or reject documents with rejection reasons
* View recent verification scans
* Access audit logs and pending verification requests

### 👑 Super Admin Module

* Create and manage school admin accounts
* Activate or deactivate admins
* Delete admin accounts
* Access global data and audit visibility

## 🧩 Core Modules

* Authentication Module
* Student Dashboard Module
* Document Upload & Review Module
* Verification & QR Module
* Task Management Module
* Notification Module
* Audit Logging Module
* Multilingual Translation Module
* Admin & Super Admin Management Module

## 🛠️ Tech Stack

* Backend: Python + Flask
* Database: SQLite
* Frontend: HTML, CSS, JavaScript, Jinja Templates
* Authentication: OTP + Password Hashing
* QR Verification: Public Verification Endpoint
* Deployment: Render
* Version Control: Git + GitHub

## 🔐 Security Features

* Role-based access control
* OTP-based login flow
* Password hashing
* Session timeout support
* File type and size validation
* Audit logs for critical actions
* QR-based public verification

## 🌐 Multilingual Support

The system supports:

* English
* Tamil
* Hindi

## 📂 Main Database Tables

* users
* student_details
* admin_profiles
* uploaded_documents
* verification_status
* student_tasks
* audit_log
* verification_scans

## ⚙️ Installation

```bash
git clone https://github.com/Divi-R0706/Secure-Student-Identity-Verification-System.git
cd Secure-Student-Identity-Verification-System
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## 🌍 Deployment

Deployed on Render using:

```bash
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app
```

## 🔮 Future Enhancements

* Cloud file storage
* Real SMS OTP integration
* OCR-based document verification
* Real-time notifications
* Mobile application support
