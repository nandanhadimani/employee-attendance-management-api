# Employee Attendance Management API

A FastAPI application for employee management, attendance tracking, and attendance analytics using MongoDB.

## Features

- Create and list employees with pagination.
- Record employee punch-in and punch-out.
- Filter attendance records.
- Calculate late minutes, overtime, work hours, and half-day attendance.
- Generate monthly employee analytics.
- Generate department summaries and attendance trends.
- Rank employees by late attendance.

## Requirements

- Python 3.10+
- MongoDB 6.0 or newer

MongoDB Atlas or a local MongoDB instance can be used.

## Setup

### 1. Create and Activate a Virtual Environment

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install Dependencies

```powershell
pip install -r requirements.txt
```

### 3. Environment Configuration

Create a `.env` file in the project root directory with the following variables:

```env
MONGO_URI=your_mongodb_connection_string
MONGO_DB=attendance_db
```

Replace the placeholder with your MongoDB connection string.

**Security:** Keep your database credentials private. Do not commit `.env` to GitHub.

### 4. Run the Application

```powershell
python -m uvicorn app.main:app --port 8000
```

### 5. Open Swagger UI

Open the following URL in your browser:

http://127.0.0.1:8000/docs