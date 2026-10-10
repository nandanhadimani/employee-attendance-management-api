# REVIEW.md

## Defects Found in the Starter Code

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | Employee listing endpoint | Pagination may use an incorrect skip calculation or return an incorrect total. | Request page 1 with page_size 1 and verify the returned items and total. | Corrected skip to `(page - 1) * page_size` and used `count_documents()` with the active filters. |
| 2 | Employee listing endpoint | Pagination parameters may accept invalid values or exceed the permitted page size. | Try page 0 or page_size greater than 100. | Added parameter validation: page must be at least 1 and page_size must be between 1 and 100. |
| 3 | Attendance listing endpoint | Attendance filters and pagination may not be applied consistently. | Filter by employee code, date range, or status and inspect the response. | Applied filters to the MongoDB query and used the filtered query for counting and pagination. |
| 4 | Late-minutes helper | Late minutes may be calculated incorrectly around the grace-period boundary. | Test 09:40:00 and 09:40:01 for a 09:30 shift start. | Applied the strictly-greater-than-10-minute grace rule and calculated whole elapsed minutes. |
| 5 | Work-hours helper | Work hours may be rounded incorrectly or calculated using an incorrect time difference. | Test a work duration of 4 hours 30 minutes. | Calculated duration in seconds and rounded hours to two decimal places using half-up rounding. |
| 6 | Overtime helper | Overtime may be counted before the required threshold or may mishandle shifts crossing midnight. | Test a punch-out before, at, and after the 30-minute overtime threshold. | Calculated whole overtime minutes and returned overtime only when it was at least 30 minutes. |
| 7 | Punch-in endpoint | A punch-in may be accepted for an employee who does not exist or when a record already exists for the same attendance date. | Try an unknown employee code and repeat a punch-in for the same date. | Added employee existence and duplicate-record checks with appropriate HTTP errors. |
| 8 | Punch-in endpoint | The attendance date may be calculated using UTC rather than the required IST date. | Submit a timestamp near midnight UTC and check the resulting attendance date. | Converted timestamps to IST before deriving the attendance date. |
| 9 | Punch-out endpoint | A second punch-out may overwrite an existing punch-out or an invalid employee/date may not be handled properly. | Repeat punch-out or try an employee without a matching attendance record. | Added checks for employee and attendance records and prevented repeated punch-out. |
| 10 | Monthly employee analytics | Present days may incorrectly include weekend attendance. | Give an employee an attendance record on Saturday and request monthly analytics. | Updated the aggregation to count present days only for Monday through Friday. |
| 11 | Monthly employee analytics | Invalid month values may be accepted or produce an unexpected error. | Request month `2026-13`. | Added month-format and month-range validation. |
| 12 | Department summary analytics | Department headcount may exclude employees without attendance records. | Add an employee in a department without attendance logs and request the summary. | Calculate department headcount from employees independently of attendance records. |
| 13 | Department trend analytics | Dates without attendance records may be omitted, or weekend attendance rates may be misleading. | Request a seven-day range that includes days without logs and weekends. | Generate a daily date series and return each requested date, with weekend attendance rates handled separately. |
| 14 | Employee and attendance endpoints | MongoDB records may expose internal `_id` values inconsistently in API responses. | Inspect the JSON returned by create, list, and attendance endpoints. | Removed MongoDB `_id` from responses and exposed a string identifier where appropriate. |

## Items Checked and Not Considered Defects

1. `GET /health` returning HTTP 200 with `{"status":"ok"}` is expected behavior.
2. `GET /` returning HTTP 404 is not a defect because the application does not define a root route.
3. An empty late-attendance leaderboard is valid when no employees have late attendance records for the requested month.
4. A monthly present-day count of zero can be correct when the employee has attendance records only on weekends, because weekends do not count as working days.
5. An HTTP 409 response for a duplicate punch-in or repeated punch-out is expected conflict handling.
6. An HTTP 404 response for an unknown employee or department is appropriate when the requested resource does not exist.
7. A MongoDB connection failure caused by an IP address that is not allowed in Atlas Network Access is an environment configuration issue, not necessarily an application-code defect.