"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from pymongo import MongoClient
from decimal import Decimal, ROUND_HALF_UP

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]
# Create indexes for better query performance
db.employees.create_index("emp_code", unique=True)

db.attendance_logs.create_index(
    [("emp_code", 1), ("date", 1)],
    unique=True
)

db.attendance_logs.create_index("date")

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    h, m = map(int, shift_start.split(":"))

    # Convert punch-in time to IST
    if punch_in.tzinfo is not None:
        punch_in = punch_in.astimezone(IST)
    else:
        punch_in = punch_in.replace(tzinfo=IST)

    # Build shift start time in IST
    start = punch_in.replace(
        hour=h,
        minute=m,
        second=0,
        microsecond=0
    )

    elapsed_seconds = (punch_in - start).total_seconds()

    # Apply the 10-minute grace period
    if elapsed_seconds <= 600:
        return 0

    # Return whole minutes late
    return int(elapsed_seconds // 60)


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    seconds = (punch_out - punch_in).total_seconds()
    hours = Decimal(str(seconds / 3600))
    return float(hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_overtime(punch_out: datetime, shift_end: str, date_str: str) -> int:
    h, m = map(int, shift_end.split(":"))
    shift_date = datetime.fromisoformat(date_str).date()

    # Convert punch-out to IST
    if punch_out.tzinfo is not None:
        punch_out = punch_out.astimezone(IST)
    else:
        punch_out = punch_out.replace(tzinfo=IST)

    # Create shift-end time in IST
    end = datetime(
        shift_date.year,
        shift_date.month,
        shift_date.day,
        h,
        m,
        tzinfo=IST
    )

    # Overnight shift: end time is on the following day
    if h < 12:
        end += timedelta(days=1)

    # Calculate overtime in whole minutes
    overtime_minutes = int((punch_out - end).total_seconds() // 60)

    # Count overtime only when it reaches 30 minutes
    return overtime_minutes if overtime_minutes >= 30 else 0


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"


# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")
    doc = body.model_dump()
    doc["created_at"] = datetime.now()
    db.employees.insert_one(doc)
    doc.pop("_id", None)
    return doc


@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    q = {}
    if department:
        q["department"] = department
    skip = (page - 1) * page_size
    total = db.employees.count_documents(q)
    items = list(db.employees.find(q, {"_id": 0}).skip(skip).limit(page_size))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    ts = (
    datetime.fromtimestamp(body.punched_at / 1000, tz=timezone.utc)
    if body.punched_at is not None
    else datetime.now(timezone.utc)
).replace(microsecond=0)
    d = ts.astimezone(IST).date().isoformat()
    if db.attendance_logs.find_one({"emp_code": body.emp_code, "date": d}):
        raise HTTPException(409, "already punched in for this date")
    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, emp["shift_start"]),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    res = db.attendance_logs.insert_one(doc)
    doc["id"] = str(res.inserted_id)
    doc.pop("_id", None)
    return doc


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        allowed_statuses = {"PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"}
        if status not in allowed_statuses:
            raise HTTPException(
                status_code=400,
                detail="Invalid status"
        )
        q["status"] = status
    total = db.attendance_logs.count_documents(q)
    page_docs = list(
    db.attendance_logs.find(q)
    .sort([("date", -1), ("emp_code", 1)])
    .skip((page - 1) * page_size)
    .limit(page_size)
)
    for d in page_docs:
        d["id"] = str(d.pop("_id"))
    return {"items": page_docs, "total": total, "page": page, "page_size": page_size}

#   POST  /attendance/punch-out
@app.post("/attendance/punch-out")
def punch_out(body: PunchInIn):
    emp_code = body.emp_code

    # Find today's attendance record
    today = datetime.now(IST).date().isoformat()

    record = db.attendance_logs.find_one({
        "emp_code": emp_code,
        "date": today
    })

    if not record:
        raise HTTPException(
            status_code=404,
            detail="Punch-in record not found"
        )

    if record.get("punch_out") is not None:
        raise HTTPException(
            status_code=409,
            detail="Already punched out"
        )

    # Get punch-out timestamp
    ts = (
        datetime.fromtimestamp(
            body.punched_at / 1000,
            tz=timezone.utc
        )
        if body.punched_at is not None
        else datetime.now(timezone.utc)
    ).replace(microsecond=0)

    # Convert to IST for attendance calculations
    punch_in = record["punch_in"]
    if punch_in.tzinfo is None:
        punch_in = punch_in.replace(tzinfo=timezone.utc)

    shift_end = db.employees.find_one(
        {"emp_code": emp_code},
        {"shift_end": 1}
    )["shift_end"]

    work_hours = compute_work_hours(punch_in, ts)
    overtime_minutes = compute_overtime(
        ts,
        shift_end,
        record["date"]
    )

    result = db.attendance_logs.update_one(
        {"_id": record["_id"], "punch_out": None},
        {
            "$set": {
                "punch_out": ts,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": work_hours < 4.50
            }
        }
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Attendance record was already updated"
        )

    updated = db.attendance_logs.find_one(
        {"_id": record["_id"]}
    )
    updated["id"] = str(updated.pop("_id"))

    return updated

#   PATCH /attendance/{emp_code}/{date}
@app.patch("/attendance/{emp_code}/{date}")
def update_attendance(
    emp_code: str,
    date: str,
    status: Optional[str] = None,
    punch_in: Optional[int] = None,
    punch_out: Optional[int] = None,
):
    # Validate attendance status
    allowed_statuses = {
        "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
    }

    if status is not None and status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail="Invalid status"
        )

    # Find the attendance record
    record = db.attendance_logs.find_one({
        "emp_code": emp_code,
        "date": date
    })

    if not record:
        raise HTTPException(
            status_code=404,
            detail="Attendance record not found"
        )

    # Prepare the fields to update
    updates = {}

    if status is not None:
        updates["status"] = status

    if punch_in is not None:
        updates["punch_in"] = datetime.fromtimestamp(
            punch_in / 1000,
            tz=timezone.utc
        ).replace(microsecond=0)

    if punch_out is not None:
        updates["punch_out"] = datetime.fromtimestamp(
            punch_out / 1000,
            tz=timezone.utc
        ).replace(microsecond=0)

    if not updates:
        raise HTTPException(
            status_code=400,
            detail="No fields provided to update"
        )

    db.attendance_logs.update_one(
        {"_id": record["_id"]},
        {"$set": updates}
    )

    updated = db.attendance_logs.find_one({
        "_id": record["_id"]
    })

    updated["id"] = str(updated.pop("_id"))

    return updated

#   GET   /analytics/employees/{emp_code}/monthly
@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(
    emp_code: str,
    month: Optional[str] = None,
):
    import re
    from calendar import monthrange
    from decimal import Decimal, ROUND_HALF_UP

    # Check employee exists
    employee = db.employees.find_one({"emp_code": emp_code})

    if not employee:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    # Default to the current month in IST
    if month is None:
        month = datetime.now(IST).strftime("%Y-%m")

    # Validate YYYY-MM format
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(
            status_code=400,
            detail="Invalid month format. Use YYYY-MM"
        )

    year, month_number = map(int, month.split("-"))
    start_date = f"{year:04d}-{month_number:02d}-01"
    last_day = monthrange(year, month_number)[1]
    end_date = f"{year:04d}-{month_number:02d}-{last_day:02d}"

    # Count weekdays, starting from the employee's join date
    joined_on = employee.get("joined_on", start_date)
    effective_start = max(start_date, joined_on)

    working_days = 0
    current = datetime.fromisoformat(effective_start).date()
    final_date = datetime.fromisoformat(end_date).date()

    while current <= final_date:
        if current.weekday() < 5:
            working_days += 1
        current += timedelta(days=1)

    # Aggregate attendance records in MongoDB
    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {"$gte": start_date, "$lte": end_date}
            }
        },
        {
            "$group": {
                "_id": None,
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$in": [
                                        "$status",
                                        ["PRESENT", "WFH", "ON_DUTY"]
                                    ]},
                                    {
    "$in": [
        {
            "$dayOfWeek": {
                "$dateFromString": {
                    "dateString": "$date"
                }
            }
        },
        [2, 3, 4, 5, 6]
    ]
}
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$half_day", True]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },
                "leave_days": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "LEAVE"]},
                            1,
                            0
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$late_minutes", 0]},
                            1,
                            0
                        ]
                    }
                },
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },
                "total_overtime_minutes": {
                    "$sum": {"$ifNull": ["$overtime_minutes", 0]}
                }
            }
        }
    ]

    results = list(db.attendance_logs.aggregate(pipeline))
    stats = results[0] if results else {}

    present_days = stats.get("present_days", 0)
    attendance_pct = None

    if working_days > 0:
        percentage = (
            Decimal(str(present_days))
            / Decimal(working_days)
            * Decimal("100")
        )
        attendance_pct = float(
            percentage.quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP
            )
        )

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": stats.get("leave_days", 0),
        "late_count": stats.get("late_count", 0),
        "total_late_minutes": stats.get("total_late_minutes", 0),
        "total_overtime_minutes": stats.get("total_overtime_minutes", 0),
        "attendance_pct": attendance_pct
    }
# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):


#   GET   /analytics/departments/summary
@app.get("/analytics/departments/summary")
def department_summary(month: Optional[str] = None):
    import re
    from calendar import monthrange
    from decimal import Decimal, ROUND_HALF_UP

    # Default to the current month
    if month is None:
        month = datetime.now(IST).strftime("%Y-%m")

    # Validate month format
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(
            status_code=400,
            detail="Invalid month format. Use YYYY-MM"
        )

    year, month_number = map(int, month.split("-"))
    start_date = f"{year:04d}-{month_number:02d}-01"
    last_day = monthrange(year, month_number)[1]
    end_date = f"{year:04d}-{month_number:02d}-{last_day:02d}"

    # Get employees who joined by the end of the month
    employees = list(
        db.employees.find(
            {"joined_on": {"$lte": end_date}},
            {"emp_code": 1, "department": 1}
        )
    )

    departments = {}

    for employee in employees:
        department = employee.get("department", "Unknown")
        if department not in departments:
            departments[department] = {
                "department": department,
                "headcount": 0,
                "present_days": 0,
                "avg_work_hours": None,
                "late_count": 0,
                "total_late_minutes": 0,
                "leave_count": 0,
                "on_duty_count": 0,
                "_work_hours_sum": 0,
                "_work_hours_count": 0,
            }

        departments[department]["headcount"] += 1

    # Aggregate attendance data in MongoDB
    pipeline = [
        {
            "$match": {
                "date": {"$gte": start_date, "$lte": end_date}
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "present_days": {
    "$sum": {
        "$cond": [
            {
                "$and": [
                    {
                        "$in": [
                            "$status",
                            ["PRESENT", "WFH", "ON_DUTY"]
                        ]
                    },
                    {
                        "$in": [
                            {
                                "$dayOfWeek": {
                                    "$dateFromString": {
                                        "dateString": "$date"
                                    }
                                }
                            },
                            [2, 3, 4, 5, 6]
                        ]
                    }
                ]
            },
            {
                "$cond": [
                    {"$eq": ["$half_day", True]},
                    0.5,
                    1
                ]
            },
            0
        ]
    }
},
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$late_minutes", 0]},
                            1,
                            0
                        ]
                    }
                },
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },
                "leave_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "LEAVE"]},
                            1,
                            0
                        ]
                    }
                },
                "on_duty_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "ON_DUTY"]},
                            1,
                            0
                        ]
                    }
                },
                "work_hours_sum": {
                    "$sum": {
                        "$ifNull": ["$work_hours", 0]
                    }
                },
                "work_hours_count": {
                    "$sum": {
                        "$cond": [
                            {"$ne": ["$work_hours", None]},
                            1,
                            0
                        ]
                    }
                }
            }
        }
    ]

    attendance_stats = list(
        db.attendance_logs.aggregate(pipeline)
    )

    # Map employee codes to their departments
    employee_departments = {
        employee["emp_code"]: employee.get("department", "Unknown")
        for employee in employees
    }

    for stats in attendance_stats:
        department = employee_departments.get(stats["_id"])

        if department is None:
            continue

        item = departments[department]
        item["present_days"] += stats["present_days"]
        item["late_count"] += stats["late_count"]
        item["total_late_minutes"] += stats["total_late_minutes"]
        item["leave_count"] += stats["leave_count"]
        item["on_duty_count"] += stats["on_duty_count"]
        item["_work_hours_sum"] += stats["work_hours_sum"]
        item["_work_hours_count"] += stats["work_hours_count"]

    # Calculate average work hours and round to two decimals
    for item in departments.values():
        if item["_work_hours_count"] > 0:
            average = (
                Decimal(str(item["_work_hours_sum"]))
                / Decimal(item["_work_hours_count"])
            )
            item["avg_work_hours"] = float(
                average.quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP
                )
            )

        del item["_work_hours_sum"]
        del item["_work_hours_count"]

    return {
        "month": month,
        "items": sorted(
            departments.values(),
            key=lambda item: item["department"]
        )
    }
    
    
#   GET   /analytics/leaderboard/late
@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str,
    limit: int = Query(default=10, ge=1, le=50),
    department: Optional[str] = None,
):
    import re
    from calendar import monthrange

    # Validate month format
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(
            status_code=422,
            detail="Invalid month format. Use YYYY-MM"
        )

    year, month_number = map(int, month.split("-"))
    start_date = f"{year:04d}-{month_number:02d}-01"
    last_day = monthrange(year, month_number)[1]
    end_date = f"{year:04d}-{month_number:02d}-{last_day:02d}"

    # Find employees, optionally filtering by department
    employee_query = {}
    if department:
        employee_query["department"] = department

    employees = list(
        db.employees.find(
            employee_query,
            {"emp_code": 1, "name": 1, "department": 1}
        )
    )

    employee_map = {
        employee["emp_code"]: {
            "name": employee["name"],
            "department": employee["department"],
        }
        for employee in employees
    }

    if not employee_map:
        return {"month": month, "items": []}

    # Aggregate late attendance records in MongoDB
    pipeline = [
        {
            "$match": {
                "emp_code": {"$in": list(employee_map.keys())},
                "date": {"$gte": start_date, "$lte": end_date},
                "late_minutes": {"$gt": 0},
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_count": {"$sum": 1},
            }
        },
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
    ]

    results = list(db.attendance_logs.aggregate(pipeline))

    # Build the leaderboard
    items = []
    previous_total = None
    current_rank = 0

    for index, result in enumerate(results, start=1):
        emp_code = result["_id"]
        total_late = result["total_late_minutes"]

        if total_late != previous_total:
            current_rank = index

        employee = employee_map[emp_code]

        items.append({
            "rank": current_rank,
            "emp_code": emp_code,
            "name": employee["name"],
            "department": employee["department"],
            "total_late_minutes": total_late,
            "late_count": result["late_count"],
        })

        previous_total = total_late

    # Apply limit after ranking so ties are included
    items = [
        item for item in items
        if item["rank"] <= limit
    ]

    return {
        "month": month,
        "items": items,
    }

#   GET   /analytics/departments/{department}/trend
@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
):
    import re
    from datetime import date
    from decimal import Decimal, ROUND_HALF_UP

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", from_date):
        raise HTTPException(status_code=422, detail="Invalid from date")

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", to_date):
        raise HTTPException(status_code=422, detail="Invalid to date")

    try:
        start = date.fromisoformat(from_date)
        end = date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid calendar date")

    if end < start:
        raise HTTPException(
            status_code=422,
            detail="End date must not be before start date",
        )

    if (end - start).days + 1 > 92:
        raise HTTPException(
            status_code=422,
            detail="Date range cannot exceed 92 days",
        )

    if not db.employees.find_one({"department": department}):
        raise HTTPException(status_code=404, detail="Department not found")

    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.min.time())

    pipeline = [
        {"$documents": [{"_id": 1}]},
        {
            "$project": {
                "dates": {
                    "$map": {
                        "input": {
                            "$range": [
                                0,
                                {
                                    "$add": [
                                        {
                                            "$dateDiff": {
                                                "startDate": start_dt,
                                                "endDate": end_dt,
                                                "unit": "day",
                                            }
                                        },
                                        1,
                                    ]
                                },
                            ]
                        },
                        "as": "offset",
                        "in": {
                            "$dateAdd": {
                                "startDate": start_dt,
                                "unit": "day",
                                "amount": "$$offset",
                            }
                        },
                    }
                }
            }
        },
        {"$unwind": "$dates"},
        {
            "$set": {
                "date_string": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$dates",
                    }
                },
                "is_working_day": {
                    "$in": [{"$dayOfWeek": "$dates"}, [2, 3, 4, 5, 6]]
                },
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "let": {"day": "$date_string"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$department", department]},
                                    {"$lte": ["$joined_on", "$$day"]},
                                ]
                            }
                        }
                    },
                    {"$count": "count"},
                ],
                "as": "headcount_result",
            }
        },
        {
            "$set": {
                "headcount": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$headcount_result.count", 0]},
                        0,
                    ]
                }
            }
        },
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"day": "$date_string"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {"$eq": ["$date", "$$day"]}
                        }
                    },
                    {
                        "$lookup": {
                            "from": "employees",
                            "localField": "emp_code",
                            "foreignField": "emp_code",
                            "as": "employee",
                        }
                    },
                    {"$unwind": "$employee"},
                    {
                        "$match": {
                            "$expr": {
                                "$eq": ["$employee.department", department]
                            }
                        }
                    },
                    {
                        "$group": {
                            "_id": None,
                            "present_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$in": [
                                                "$status",
                                                ["PRESENT", "WFH", "ON_DUTY"],
                                            ]
                                        },
                                        {
                                            "$cond": [
                                                {
                                                    "$eq": [
                                                        {
                                                            "$ifNull": [
                                                                "$half_day",
                                                                False,
                                                            ]
                                                        },
                                                        True,
                                                    ]
                                                },
                                                0.5,
                                                1,
                                            ]
                                        },
                                        0,
                                    ]
                                }
                            },
                            "late_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$gt": [
                                                {"$ifNull": ["$late_minutes", 0]},
                                                0,
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                        }
                    },
                ],
                "as": "daily_stats",
            }
        },
        {
            "$set": {
                "present_count": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$daily_stats.present_count", 0]},
                        0,
                    ]
                },
                "late_count": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$daily_stats.late_count", 0]},
                        0,
                    ]
                },
            }
        },
        {
            "$set": {
                "attendance_rate": {
                    "$cond": [
                        {
                            "$and": [
                                "$is_working_day",
                                {"$gt": ["$headcount", 0]},
                            ]
                        },
                        {
                            "$divide": [
                                {
                                    "$floor": {
                                        "$add": [
                                            {
                                                "$multiply": [
                                                    {
                                                        "$divide": [
                                                            "$present_count",
                                                            "$headcount",
                                                        ]
                                                    },
                                                    10000,
                                                ]
                                            },
                                            0.5,
                                        ]
                                    }
                                },
                                10000,
                            ]
                        },
                        None,
                    ]
                }
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"dates": 1},
                "output": {
                    "moving_avg_raw": {
                        "$avg": "$attendance_rate",
                        "window": {"documents": [-6, 0]},
                    }
                },
            }
        },
        {
            "$set": {
                "moving_avg_7d": {
                    "$cond": [
                        {"$ne": ["$moving_avg_raw", None]},
                        {
                            "$divide": [
                                {
                                    "$floor": {
                                        "$add": [
                                            {
                                                "$multiply": [
                                                    "$moving_avg_raw",
                                                    10000,
                                                ]
                                            },
                                            0.5,
                                        ]
                                    }
                                },
                                10000,
                            ]
                        },
                        None,
                    ]
                }
            }
        },
        {"$sort": {"dates": 1}},
        {
            "$project": {
                "_id": 0,
                "date": "$date_string",
                "is_working_day": 1,
                "headcount": 1,
                "present_count": 1,
                "late_count": 1,
                "attendance_rate": 1,
                "moving_avg_7d": 1,
            }
        },
    ]

    rows = list(db.aggregate(pipeline))

    return {
        "department": department,
        "from": from_date,
        "to": to_date,
        "items": rows,
    }

#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #
