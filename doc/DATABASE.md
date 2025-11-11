# SQLite Database for Job Tracking

## Overview

The LAVA job tracking system now uses a SQLite database to store test suite and job information, replacing the previous text file format.

## Database Location

Default: `~/.cache/srt-build/jobs.db`

Configurable via `config.yml`:
```yaml
system_config:
  database-path: ~/.cache/srt-build/jobs.db
```

## Database Schema

### test_suites table
Stores information about each test suite run:
- `id` - Primary key
- `suite_id` - The primary job ID (e.g., 167, 181)
- `machine` - Target machine name (e.g., c2d, rpi3)
- `created_at` - Timestamp when the suite was submitted
- `metadata` - Optional metadata field

### jobs table
Stores individual job IDs associated with each test suite:
- `id` - Primary key
- `test_suite_id` - Foreign key to test_suites.id
- `job_id` - Individual job ID

## Example

For the following job submissions:
```
167: 167
168: 168
181: 181 182 183 184 185 186 187 188 189 190 191 192 193 194 195
```

The database stores:
- 3 test suites (167, 168, 181)
- 17 individual job IDs
- Timestamps for each suite
- Machine association

## API

### Saving Jobs
```python
save_job_ids_to_db(machine, jobs, system_config)
```
Saves a test suite where `jobs[0]` is the suite ID and the rest are individual job IDs.

### Retrieving Jobs
```python
# Get single job
jobs = get_jobs_from_db(machine, job_id, system_config, batch=False)

# Get all jobs in a test suite
jobs = get_jobs_from_db(machine, job_id, system_config, batch=True)
```

### Listing Test Suites
```python
suite_ids = get_job_list_from_db(machine, system_config)
```

## Benefits

1. **Structured Data** - Proper relational schema with foreign key constraints
2. **Timestamps** - Track when test suites were submitted
3. **Query Power** - Use SQL for filtering, sorting, and analysis
4. **Scalability** - Indexed for fast lookups
5. **Extensibility** - Easy to add new fields and metadata

## Testing

Run the test suite:
```bash
python tests/test_database.py
```

## Future Enhancements

The database schema supports future extensions such as:
- Job status tracking (queued, running, completed, failed)
- Kernel version and configuration information
- Performance metrics
- Test results and duration
- Advanced reporting and analytics
