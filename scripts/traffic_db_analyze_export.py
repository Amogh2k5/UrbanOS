#!/usr/bin/env python
"""
Traffic Database Analysis & Export Utility (Read-Only)

Performs read-only inspection of the traffic_observations.db SQLite database
and optional streaming export to gzip-compressed CSV.

Safety:
- Never modifies the source database
- Uses read-only connections (mode=ro)
- Streams exports in bounded batches
- Refuses to overwrite existing output files
- Validates before publishing final file

Usage:
    python scripts/traffic_db_analyze_export.py --analyze
    python scripts/traffic_db_analyze_export.py --estimate-export
    python scripts/traffic_db_analyze_export.py --export-csv-gz --output PATH [--start-time ISO] [--end-time ISO] [--batch-size N]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

# ─── Constants ──────────────────────────────────────────────────────────────
SG_OFFSET = timezone(timedelta(hours=8))

# Traffic observation columns (matches TrafficPredictor feature requirements)
OBS_COLUMNS = [
    "observed_at", "link_id", "road_name", "road_category", "speed_band",
    "minimum_speed", "maximum_speed", "speed_midpoint",
    "start_latitude", "start_longitude", "end_latitude", "end_longitude",
    "zone_id", "zone_name", "created_at"
]

# Columns used by predictor (excludes created_at)
PREDICTOR_COLUMNS = [c for c in OBS_COLUMNS if c != "created_at"]

DEFAULT_DB_PATH = Path("data/traffic_observations.db")
DEFAULT_TRAIN_DB_PATH = Path("data/traffic_observations_train.db")

# Default batch size for streaming (rows per transaction)
DEFAULT_BATCH_SIZE = 50000

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("traffic_db_analyze_export")


# ─── Data Classes ───────────────────────────────────────────────────────────
@dataclass
class DatabaseInfo:
    """Read-only database metadata."""
    file_path: str
    file_size_bytes: int
    file_size_gb: float
    page_size: int
    page_count: int
    freelist_count: int
    freelist_bytes: int
    journal_mode: str
    auto_vacuum: int
    synchronous: int
    tables: List[str]
    schema: Dict[str, str]
    indexes: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TableStats:
    """Statistics for the traffic_observations table."""
    table_name: str
    row_count: int
    earliest_observed_at: Optional[str]
    latest_observed_at: Optional[str]
    unique_timestamps: int
    unique_link_ids: Optional[int]
    unique_zones: Optional[int]
    duplicate_pk_count: int
    observations_per_day: Optional[float]
    daily_storage_growth_mb: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExportEstimate:
    """Estimated export sizes."""
    selected_row_count: int
    estimated_csv_bytes: int
    estimated_csv_mb: float
    estimated_gz_bytes: int
    estimated_gz_mb: float
    compression_ratio: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Manifest:
    """Export manifest for verification."""
    source_database: str
    table: str
    time_range_start: Optional[str]
    time_range_end: Optional[str]
    columns: List[str]
    row_count: int
    export_timestamp: str
    output_path: str
    output_sha256: str
    output_size_bytes: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── Utility Functions ──────────────────────────────────────────────────────

def open_ro_db(db_path: Path) -> sqlite3.Connection:
    """Open SQLite database in read-only mode."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    # Use URI mode for read-only access
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def get_disk_space(path: Path) -> Tuple[int, int, int]:
    """Return (total, used, free) bytes for the filesystem containing path."""
    usage = shutil.disk_usage(path)
    return usage.total, usage.used, usage.free


def parse_iso_timestamp(ts: str) -> Optional[datetime]:
    """Parse ISO timestamp with timezone, return timezone-aware datetime."""
    if not ts:
        return None
    try:
        # Handle both with and without timezone
        if ts.endswith('Z'):
            ts = ts[:-1] + '+00:00'
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def format_duration(seconds: float) -> str:
    """Format duration in human-readable form."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


def format_bytes(bytes_val: int) -> str:
    """Format bytes in human-readable form."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f}{unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f}PB"


# ─── Analysis Functions ──────────────────────────────────────────────────────

def analyze_database(db_path: Path) -> DatabaseInfo:
    """Perform read-only database inspection."""
    log.info(f"Analyzing database: {db_path}")
    conn = open_ro_db(db_path)
    
    try:
        # File info
        file_size = db_path.stat().st_size
        
        # PRAGMA info
        pragma_info = {}
        for pragma in ['page_size', 'page_count', 'freelist_count', 
                       'journal_mode', 'auto_vacuum', 'synchronous']:
            r = conn.execute(f"PRAGMA {pragma}").fetchone()
            pragma_info[pragma] = r[0] if r else None
        
        # Tables
        tables = [row[0] for row in conn.execute(
            'SELECT name FROM sqlite_master WHERE type="table" ORDER BY name'
        ).fetchall()]
        
        # Schemas
        schemas = {}
        for table in tables:
            r = conn.execute(
                'SELECT sql FROM sqlite_master WHERE type="table" AND name=?', 
                (table,)
            ).fetchone()
            schemas[table] = r[0] if r else None
        
        # Indexes
        indexes = {}
        for table in tables:
            idx_rows = conn.execute(
                'SELECT name, sql FROM sqlite_master WHERE type="index" AND tbl_name=?',
                (table,)
            ).fetchall()
            for idx in idx_rows:
                indexes[f"{table}.{idx[0]}"] = idx[1]
        
        return DatabaseInfo(
            file_path=str(db_path),
            file_size_bytes=file_size,
            file_size_gb=file_size / (1024**3),
            page_size=pragma_info.get('page_size', 0),
            page_count=pragma_info.get('page_count', 0),
            freelist_count=pragma_info.get('freelist_count', 0),
            freelist_bytes=pragma_info.get('freelist_count', 0) * pragma_info.get('page_size', 0),
            journal_mode=pragma_info.get('journal_mode', ''),
            auto_vacuum=pragma_info.get('auto_vacuum', 0),
            synchronous=pragma_info.get('synchronous', 0),
            tables=tables,
            schema=schemas,
            indexes=indexes,
        )
    finally:
        conn.close()


def analyze_traffic_table(db_path: Path, fast: bool = False) -> TableStats:
    """Analyze the traffic_observations table using efficient queries.
    
    If fast=True, skips expensive COUNT(DISTINCT) queries that can take
    minutes on large databases.
    """
    log.info(f"Analyzing traffic_observations table... (fast={fast})")
    conn = open_ro_db(db_path)
    
    try:
        table_name = "traffic_observations"
        
        # Row count via MAX(rowid) - O(1) for append-only table
        row_count = conn.execute(
            "SELECT MAX(rowid) FROM traffic_observations"
        ).fetchone()[0] or 0
        
        # Date range - separate queries to use idx_traffic_obs_timestamp
        earliest = conn.execute(
            "SELECT MIN(observed_at) FROM traffic_observations"
        ).fetchone()[0]
        latest = conn.execute(
            "SELECT MAX(observed_at) FROM traffic_observations"
        ).fetchone()[0]
        
        # Unique timestamps - uses idx_traffic_obs_timestamp
        if fast:
            unique_timestamps = None
            log.info("Skipping COUNT(DISTINCT observed_at) in fast mode")
        else:
            unique_timestamps = conn.execute(
                "SELECT COUNT(DISTINCT observed_at) FROM traffic_observations"
            ).fetchone()[0]
        
        # Try to get cached stats first
        unique_link_ids = None
        unique_zones = None
        cache_path = Path(str(db_path) + ".stats_cache.json")
        if cache_path.exists():
            try:
                with open(cache_path, 'r') as f:
                    cache = json.load(f)
                if cache.get("total_observations") == row_count:
                    unique_link_ids = cache.get("unique_link_ids")
                    unique_zones = cache.get("unique_zones_mapped")
                    log.info(f"Using cached distinct counts: links={unique_link_ids}, zones={unique_zones}")
            except Exception as e:
                log.warning(f"Could not read stats cache: {e}")
        
        # Duplicate PK check - sample from latest timestamp only (fast)
        latest_ts = latest
        duplicate_pk_count = 0
        if latest_ts:
            dupes = conn.execute("""
                SELECT COUNT(*) FROM (
                    SELECT observed_at, link_id, COUNT(*) as cnt
                    FROM traffic_observations
                    WHERE observed_at = ?
                    GROUP BY observed_at, link_id
                    HAVING COUNT(*) > 1
                )
            """, (latest_ts,)).fetchone()[0]
            duplicate_pk_count = dupes or 0
        
        # Estimates
        observations_per_day = None
        daily_storage_growth_mb = None
        if earliest and latest and row_count > 0:
            try:
                earl = parse_iso_timestamp(earliest)
                lat = parse_iso_timestamp(latest)
                if earl and lat:
                    days = (lat - earl).total_seconds() / 86400
                    if days > 0:
                        observations_per_day = row_count / days
                        # Estimate daily growth from file size
                        file_size_mb = db_path.stat().st_size / (1024**2)
                        daily_storage_growth_mb = file_size_mb / max(days, 1)
            except Exception as e:
                log.warning(f"Could not compute daily rate: {e}")
        
        return TableStats(
            table_name=table_name,
            row_count=row_count,
            earliest_observed_at=earliest,
            latest_observed_at=latest,
            unique_timestamps=unique_timestamps,
            unique_link_ids=unique_link_ids,
            unique_zones=unique_zones,
            duplicate_pk_count=duplicate_pk_count,
            observations_per_day=observations_per_day,
            daily_storage_growth_mb=daily_storage_growth_mb,
        )
    finally:
        conn.close()


def estimate_export_size(
    db_path: Path, 
    start_time: Optional[str], 
    end_time: Optional[str],
    columns: List[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
    fast: bool = False,
) -> ExportEstimate:
    """Estimate export size by sampling."""
    log.info("Estimating export size...")
    conn = open_ro_db(db_path)
    
    try:
        # Build WHERE clause for time filter
        where_clauses = []
        params = []
        if start_time:
            where_clauses.append("observed_at >= ?")
            params.append(start_time)
        if end_time:
            where_clauses.append("observed_at <= ?")
            params.append(end_time)
        
        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)
        
        # In fast mode without time filters, use MAX(rowid) instead of COUNT(*)
        if fast and not where_clauses:
            row_count = conn.execute(
                "SELECT MAX(rowid) FROM traffic_observations"
            ).fetchone()[0] or 0
            log.info(f"Fast mode: using MAX(rowid) for row count: {row_count:,}")
        else:
            # Count matching rows (use MAX(rowid) if no filter, else COUNT)
            if where_clauses:
                count_sql = f"SELECT COUNT(*) FROM traffic_observations {where_sql}"
                row_count = conn.execute(count_sql, params).fetchone()[0] or 0
            else:
                row_count = conn.execute(
                    "SELECT MAX(rowid) FROM traffic_observations"
                ).fetchone()[0] or 0
        
        if row_count == 0:
            return ExportEstimate(
                selected_row_count=0,
                estimated_csv_bytes=0,
                estimated_csv_mb=0.0,
                estimated_gz_bytes=0,
                estimated_gz_mb=0.0,
                compression_ratio=0.0,
            )
        
        # Sample rows to estimate average row size in CSV
        sample_limit = min(batch_size, row_count)
        sample_sql = f"SELECT {', '.join(columns)} FROM traffic_observations {where_sql} LIMIT ?"
        sample_params = params + [sample_limit]
        
        cursor = conn.execute(sample_sql, sample_params)
        rows = cursor.fetchall()
        sample_count = len(rows)
        
        if sample_count == 0:
            # Fallback: estimate based on column count and typical sizes
            avg_row_bytes = len(columns) * 20  # rough estimate
        else:
            # Write sample to CSV in memory to measure
            import io
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(columns)
            for row in rows:
                writer.writerow([row[c] if row[c] is not None else '' for c in columns])
            csv_size = len(buf.getvalue().encode('utf-8'))
            # Subtract header, divide by sample count
            header_size = len(','.join(columns)) + 1  # + newline
            avg_row_bytes = (csv_size - header_size) / sample_count
        
        # Estimate total CSV size
        estimated_csv_bytes = int(row_count * avg_row_bytes) + len(','.join(columns)) + 1
        
        # Estimate gzip size (typical compression 15-25% for CSV)
        # Use 20% as conservative estimate
        estimated_gz_bytes = int(estimated_csv_bytes * 0.20)
        compression_ratio = estimated_csv_bytes / estimated_gz_bytes if estimated_gz_bytes > 0 else 0.0
        
        return ExportEstimate(
            selected_row_count=row_count,
            estimated_csv_bytes=estimated_csv_bytes,
            estimated_csv_mb=estimated_csv_bytes / (1024**2),
            estimated_gz_bytes=estimated_gz_bytes,
            estimated_gz_mb=estimated_gz_bytes / (1024**2),
            compression_ratio=compression_ratio,
        )
    finally:
        conn.close()


# ─── Export Functions ────────────────────────────────────────────────────────

def export_to_csv_gz(
    db_path: Path,
    output_path: Path,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    columns: List[str] = OBS_COLUMNS,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Manifest:
    """Stream export to gzip-compressed CSV with validation."""
    log.info(f"Starting export to {output_path}")
    
    if output_path.exists():
        raise FileExistsError(f"Output file already exists: {output_path}. Refusing to overwrite.")
    
    # Check disk space
    total, used, free = get_disk_space(output_path.parent)
    log.info(f"Disk space: free={format_bytes(free)}, total={format_bytes(total)}")
    
    conn = open_ro_db(db_path)
    
    try:
        # Build WHERE clause
        where_clauses = []
        params = []
        if start_time:
            where_clauses.append("observed_at >= ?")
            params.append(start_time)
        if end_time:
            where_clauses.append("observed_at <= ?")
            params.append(end_time)
        
        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)
        
        # Count total rows for progress
        if where_clauses:
            count_sql = f"SELECT COUNT(*) FROM traffic_observations {where_sql}"
            total_rows = conn.execute(count_sql, params).fetchone()[0] or 0
        else:
            total_rows = conn.execute(
                "SELECT MAX(rowid) FROM traffic_observations"
            ).fetchone()[0] or 0
        
        if total_rows == 0:
            log.warning("No rows match the filter; creating empty export")
            total_rows = 0
        
        # Prepare export
        tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        
        export_timestamp = datetime.now(timezone.utc).isoformat()
        exported_count = 0
        sha256_hash = hashlib.sha256()
        
        # Stream export
        select_sql = f"SELECT {', '.join(columns)} FROM traffic_observations {where_sql} ORDER BY observed_at, link_id"
        
        with gzip.open(tmp_path, 'wt', encoding='utf-8', newline='') as gz_file:
            writer = csv.writer(gz_file)
            writer.writerow(columns)
            
            # Stream in batches using cursor
            cursor = conn.execute(select_sql, params)
            
            batch = []
            start_time_export = time.time()
            
            for row in cursor:
                batch.append([row[c] if row[c] is not None else '' for c in columns])
                
                if len(batch) >= batch_size:
                    writer.writerows(batch)
                    for row_data in batch:
                        line = ','.join(str(v) for v in row_data) + '\n'
                        sha256_hash.update(line.encode('utf-8'))
                    exported_count += len(batch)
                    batch = []
                    
                    # Progress logging
                    if exported_count % 100000 == 0:
                        elapsed = time.time() - start_time_export
                        rate = exported_count / elapsed if elapsed > 0 else 0
                        pct = (exported_count / total_rows * 100) if total_rows > 0 else 0
                        log.info(f"Progress: {exported_count:,}/{total_rows:,} ({pct:.1f}%) - {rate:,.0f} rows/s")
            
            # Write remaining batch
            if batch:
                writer.writerows(batch)
                for row_data in batch:
                    line = ','.join(str(v) for v in row_data) + '\n'
                    sha256_hash.update(line.encode('utf-8'))
                exported_count += len(batch)
        
        elapsed = time.time() - start_time_export
        rate = exported_count / elapsed if elapsed > 0 and exported_count > 0 else 0
        log.info(f"Export complete: {exported_count:,} rows in {format_duration(elapsed)} ({rate:,.0f} rows/s)")
        
        # Validate export
        log.info("Validating export...")
        validate_export(tmp_path, columns, exported_count)
        
        # Get file info
        file_size = tmp_path.stat().st_size
        output_sha256 = sha256_hash.hexdigest()
        
        # Atomic move to final location
        shutil.move(str(tmp_path), str(output_path))
        log.info(f"Published export to {output_path} ({format_bytes(file_size)})")
        
        return Manifest(
            source_database=str(db_path),
            table="traffic_observations",
            time_range_start=start_time,
            time_range_end=end_time,
            columns=columns,
            row_count=exported_count,
            export_timestamp=export_timestamp,
            output_path=str(output_path),
            output_sha256=output_sha256,
            output_size_bytes=file_size,
        )
    finally:
        conn.close()


def validate_export(gz_path: Path, expected_columns: List[str], expected_rows: int) -> None:
    """Validate exported gzip CSV."""
    log.info(f"Validating {gz_path}...")
    
    row_count = 0
    with gzip.open(gz_path, 'rt', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            raise ValueError("Export file is empty (no header)")
        if header != expected_columns:
            raise ValueError(f"Header mismatch: expected {expected_columns}, got {header}")
        
        for row in reader:
            row_count += 1
            if len(row) != len(expected_columns):
                raise ValueError(f"Row {row_count} has {len(row)} columns, expected {len(expected_columns)}")
    
    if row_count != expected_rows:
        raise ValueError(f"Row count mismatch: expected {expected_rows}, got {row_count}")
    
    log.info(f"Validation passed: {row_count:,} rows, {len(expected_columns)} columns")


# ─── Main CLI ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Traffic Database Analysis & Export Utility (Read-Only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analysis only (default)
  python scripts/traffic_db_analyze_export.py --analyze
  
  # Estimate export size for full database
  python scripts/traffic_db_analyze_export.py --estimate-export
  
  # Estimate export for last 7 days
  python scripts/traffic_db_analyze_export.py --estimate-export --start-time 2026-09-17T00:00:00+08:00
  
  # Export full database to gzip CSV
  python scripts/traffic_db_analyze_export.py --export-csv-gz --output /tmp/traffic_export.csv.gz
  
  # Export last 14 days with custom batch size
  python scripts/traffic_db_analyze_export.py --export-csv-gz --output /tmp/traffic_14d.csv.gz \\
    --start-time 2026-09-10T00:00:00+08:00 --batch-size 100000

Notes:
  - All operations are read-only; source database is never modified
  - Export requires explicit --output path and refuses to overwrite
  - Default mode is --analyze; export requires --export-csv-gz flag
  - Timestamp filters use observed_at column (ISO format with timezone)
        """,
    )
    
    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        '--analyze', 
        action='store_true', 
        help='Perform read-only database inspection (default mode)'
    )
    mode_group.add_argument(
        '--estimate-export', 
        action='store_true', 
        help='Estimate export size without creating files'
    )
    mode_group.add_argument(
        '--export-csv-gz', 
        action='store_true', 
        help='Export selected data to gzip-compressed CSV (requires --output)'
    )
    
    # Database options
    parser.add_argument(
        '--db-path', 
        type=Path, 
        default=DEFAULT_DB_PATH,
        help=f'Path to traffic_observations.db (default: {DEFAULT_DB_PATH})'
    )
    parser.add_argument(
        '--train-db-path', 
        type=Path, 
        default=DEFAULT_TRAIN_DB_PATH,
        help=f'Path to traffic_observations_train.db (default: {DEFAULT_TRAIN_DB_PATH})'
    )
    
    # Export options
    parser.add_argument(
        '--output', 
        type=Path, 
        help='Output file path for export (required with --export-csv-gz)'
    )
    parser.add_argument(
        '--start-time', 
        type=str, 
        help='Start timestamp filter (ISO format, e.g., 2026-09-01T00:00:00+08:00)'
    )
    parser.add_argument(
        '--end-time', 
        type=str, 
        help='End timestamp filter (ISO format, e.g., 2026-09-30T23:59:59+08:00)'
    )
    parser.add_argument(
        '--batch-size', 
        type=int, 
        default=DEFAULT_BATCH_SIZE,
        help=f'Batch size for streaming export (default: {DEFAULT_BATCH_SIZE})'
    )
    parser.add_argument(
        '--columns', 
        type=str, 
        choices=['all', 'predictor'],
        default='all',
        help='Column set to export: all (with created_at) or predictor (without created_at)'
    )
    
    # Output options
    parser.add_argument(
        '--json', 
        action='store_true', 
        help='Output analysis/estimation results as JSON'
    )
    parser.add_argument(
        '-v', '--verbose', 
        action='store_true', 
        help='Verbose logging'
    )
    parser.add_argument(
        '--fast', 
        action='store_true', 
        help='Skip expensive queries (COUNT DISTINCT) for faster analysis on large databases'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        log.setLevel(logging.DEBUG)
    
    # Validate timestamp format if provided
    for ts_arg in ['start_time', 'end_time']:
        ts = getattr(args, ts_arg)
        if ts:
            try:
                parse_iso_timestamp(ts)
            except Exception:
                parser.error(f"Invalid timestamp format for --{ts_arg.replace('_', '-')}: {ts}. Use ISO format with timezone.")
    
    # Validate export requirements
    if args.export_csv_gz:
        if not args.output:
            parser.error("--export-csv-gz requires --output PATH")
        if args.output.exists():
            parser.error(f"Output file already exists: {args.output}")
    
    # Select column set
    columns = OBS_COLUMNS if args.columns == 'all' else PREDICTOR_COLUMNS
    
    # Run analysis (always needed for estimation/export)
    db_info = analyze_database(args.db_path)
    table_stats = analyze_traffic_table(args.db_path, fast=args.fast)
    
    # Also analyze train DB if it exists
    train_db_info = None
    train_table_stats = None
    if args.train_db_path.exists():
        try:
            train_db_info = analyze_database(args.train_db_path)
            train_table_stats = analyze_traffic_table(args.train_db_path, fast=args.fast)
        except Exception as e:
            log.warning(f"Could not analyze training database: {e}")
    
    if args.analyze:
        # Print analysis report
        result = {
            "database": db_info.to_dict(),
            "table_stats": table_stats.to_dict(),
        }
        if train_db_info:
            result["train_database"] = train_db_info.to_dict()
            result["train_table_stats"] = train_table_stats.to_dict()
        
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print_analysis_report(db_info, table_stats, train_db_info, train_table_stats)
        return 0
    
    if args.estimate_export:
        estimate = estimate_export_size(
            args.db_path, 
            args.start_time, 
            args.end_time, 
            columns,
            args.batch_size,
            fast=args.fast
        )
        
        # Also estimate for 7, 14, 35 days if no explicit filter and not in fast mode
        estimates = {"full": estimate.to_dict()}
        if not args.fast and not args.start_time and not args.end_time and table_stats.latest_observed_at:
            latest = parse_iso_timestamp(table_stats.latest_observed_at)
            if latest:
                for days in [7, 14, 35]:
                    start = (latest - timedelta(days=days)).isoformat()
                    est = estimate_export_size(
                        args.db_path, start, None, columns, args.batch_size, fast=args.fast
                    )
                    estimates[f"last_{days}_days"] = est.to_dict()
        
        result = {
            "database": db_info.to_dict(),
            "table_stats": table_stats.to_dict(),
            "estimates": estimates,
        }
        
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print_estimation_report(estimate, estimates)
        return 0
    
    if args.export_csv_gz:
        log.info(f"Exporting to {args.output} (gzip CSV)...")
        manifest = export_to_csv_gz(
            args.db_path,
            args.output,
            args.start_time,
            args.end_time,
            columns,
            args.batch_size,
        )
        
        if args.json:
            print(json.dumps(manifest.to_dict(), indent=2, default=str))
        else:
            print_manifest_report(manifest)
        return 0
    
    return 0


def print_analysis_report(
    db_info: DatabaseInfo, 
    table_stats: TableStats,
    train_db_info: Optional[DatabaseInfo] = None,
    train_table_stats: Optional[TableStats] = None,
) -> None:
    """Print human-readable analysis report."""
    print("\n" + "=" * 70)
    print("TRAFFIC DATABASE ANALYSIS REPORT")
    print("=" * 70)
    
    print(f"\n[DB] Database: {db_info.file_path}")
    print(f"   Size: {format_bytes(db_info.file_size_bytes)} ({db_info.file_size_gb:.2f} GB)")
    print(f"   Page size: {db_info.page_size} bytes")
    print(f"   Page count: {db_info.page_count:,}")
    print(f"   Freelist: {db_info.freelist_count:,} pages ({format_bytes(db_info.freelist_bytes)})")
    print(f"   Journal mode: {db_info.journal_mode}")
    print(f"   Auto-vacuum: {db_info.auto_vacuum}")
    print(f"   Synchronous: {db_info.synchronous}")
    
    print(f"\n[TABLE] Table: traffic_observations")
    print(f"   Row count: {table_stats.row_count:,}")
    print(f"   Date range: {table_stats.earliest_observed_at} -> {table_stats.latest_observed_at}")
    if table_stats.unique_timestamps is not None:
        print(f"   Unique timestamps (snapshots): {table_stats.unique_timestamps:,}")
    else:
        print(f"   Unique timestamps (snapshots): N/A (skipped in fast mode)")
    if table_stats.unique_link_ids:
        print(f"   Unique link_ids (cached): {table_stats.unique_link_ids:,}")
    if table_stats.unique_zones:
        print(f"   Unique zones (cached): {table_stats.unique_zones:,}")
    print(f"   Duplicate PKs (latest snapshot): {table_stats.duplicate_pk_count}")
    if table_stats.observations_per_day:
        print(f"   Observations/day (est.): {table_stats.observations_per_day:,.0f}")
    if table_stats.daily_storage_growth_mb:
        print(f"   Daily storage growth (est.): {table_stats.daily_storage_growth_mb:.1f} MB/day")
    
    print(f"\n[SCHEMA] Schema:")
    for table, schema in db_info.schema.items():
        if schema:
            print(f"   {table}:")
            for line in schema.strip().split('\n'):
                print(f"     {line.strip()}")
    
    print(f"\n[INDEXES] Indexes:")
    for idx_name, idx_sql in db_info.indexes.items():
        if idx_sql:
            print(f"   {idx_name}: {idx_sql.strip()}")
        else:
            print(f"   {idx_name}: (auto-index)")
    
    if train_db_info and train_table_stats:
        print(f"\n[DB] Training Database: {train_db_info.file_path}")
        print(f"   Size: {format_bytes(train_db_info.file_size_bytes)} ({train_db_info.file_size_gb:.2f} GB)")
        print(f"   Row count: {train_table_stats.row_count:,}")
        print(f"   Date range: {train_table_stats.earliest_observed_at} -> {train_table_stats.latest_observed_at}")


def print_estimation_report(estimate: ExportEstimate, estimates: Dict[str, Dict]) -> None:
    """Print human-readable estimation report."""
    print("\n" + "=" * 70)
    print("EXPORT SIZE ESTIMATION")
    print("=" * 70)
    
    def print_est(label: str, est: ExportEstimate) -> None:
        print(f"\n[EST] {label}:")
        print(f"   Selected rows: {est.selected_row_count:,}")
        print(f"   Uncompressed CSV: {format_bytes(est.estimated_csv_bytes)} ({est.estimated_csv_mb:.1f} MB)")
        print(f"   Gzip compressed:  {format_bytes(est.estimated_gz_bytes)} ({est.estimated_gz_mb:.1f} MB)")
        print(f"   Compression ratio: {est.compression_ratio:.1f}x")
    
    print_est("Full Database", estimate)
    
    for label, est_dict in estimates.items():
        if label != "full":
            est = ExportEstimate(**est_dict)
            print_est(label.replace('_', ' ').title(), est)
    
    # Disk space check
    if estimate.estimated_gz_bytes > 0:
        # Check output directory space (assume current dir)
        total, used, free = get_disk_space(Path.cwd())
        print(f"\n[DISK] Disk space: free={format_bytes(free)}")
        if estimate.estimated_gz_bytes > free * 0.8:
            print(f"   [WARN] WARNING: Export may exceed 80% of free space!")
        else:
            print(f"   [OK] Sufficient space for export")


def print_manifest_report(manifest: Manifest) -> None:
    """Print export manifest."""
    print("\n" + "=" * 70)
    print("EXPORT MANIFEST")
    print("=" * 70)
    print(f"Source database: {manifest.source_database}")
    print(f"Table: {manifest.table}")
    print(f"Time range: {manifest.time_range_start} -> {manifest.time_range_end}")
    print(f"Columns: {len(manifest.columns)} ({', '.join(manifest.columns)})")
    print(f"Rows exported: {manifest.row_count:,}")
    print(f"Export timestamp: {manifest.export_timestamp}")
    print(f"Output: {manifest.output_path}")
    print(f"Output size: {format_bytes(manifest.output_size_bytes)}")
    print(f"SHA256: {manifest.output_sha256}")


if __name__ == "__main__":
    sys.exit(main())