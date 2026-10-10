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

Create and activate a virtual environment, then install dependencies.

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt