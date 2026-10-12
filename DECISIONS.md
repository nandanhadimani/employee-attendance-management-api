# DECISIONS.md

## Technical Decisions

### 1. MongoDB Indexes
I use indexes to improve query performance when searching employees and attendance records. The employee code should be unique, and attendance records should be unique for an employee and attendance date. Indexes on employee code, date, and frequently filtered fields help MongoDB retrieve records efficiently.

### 2. Punch-In Race Conditions
Two punch-in requests can arrive at almost the same time. Checking for an existing record before inserting is not sufficient by itself. A unique compound index on employee code and attendance date prevents duplicate records. If a request conflicts with an existing record, the API should return HTTP 409.

### 3. Leaderboard Ties
Employees are ranked by total late minutes. Employees with the same total receive the same rank. A secondary sort by employee code provides deterministic ordering when totals are equal.

### 4. Department Headcount
Department headcount is calculated from employee records rather than attendance logs. This ensures employees who have not yet recorded attendance are still included.

### 5. Scaling to 100 Times More Data

For larger datasets, I would use MongoDB aggregation pipelines to perform filtering and calculations in the database rather than loading records into Python. I would review query execution plans using `explain("executionStats")`, add indexes based on actual query patterns, and verify that frequently used queries use indexes where appropriate. I would also test performance with a larger dataset, monitor query execution times, and review pagination and database capacity.