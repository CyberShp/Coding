"""
Data Lifecycle Manager.

Handles:
- History alert import from remote arrays
- Incremental sync tracking
- Data archiving and cleanup
"""

import gzip
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.alert import AlertModel, AlertCreate, AlertLevel
from ..models.lifecycle import (
    SyncStateModel, AlertsArchiveModel, ArchiveConfigModel,
    SyncState, ImportResult, ArchiveConfig, ArchiveStats, LogFileInfo
)
from .system_alert import sys_info, sys_warning, sys_error

logger = logging.getLogger(__name__)


class DataLifecycleManager:
    """
    Manages data lifecycle for alerts:
    - Import history from remote arrays
    - Track sync position for incremental updates
    - Archive old data with compression
    - Cleanup expired archives
    """
    
    def __init__(self, ssh_conn=None):
        self.ssh_conn = ssh_conn
    
    def set_connection(self, ssh_conn):
        """Set SSH connection for remote operations"""
        self.ssh_conn = ssh_conn
    
    async def get_remote_log_files(self, log_dir: str = "/var/log/observation-points") -> List[LogFileInfo]:
        """
        Get list of alert log files from remote array.
        Returns file info sorted by modification time (newest first).
        """
        if not self.ssh_conn or not self.ssh_conn.is_connected():
            return []
        
        try:
            # List files matching alerts.log*
            cmd = f"ls -la {log_dir}/alerts.log* 2>/dev/null || true"
            output = self.ssh_conn.exec_command(cmd)
            
            files = []
            for line in output.strip().split('\n'):
                if not line or 'total' in line.lower():
                    continue
                
                parts = line.split()
                if len(parts) >= 9:
                    size = int(parts[4]) if parts[4].isdigit() else 0
                    name = parts[-1].split('/')[-1]
                    
                    # Human readable size
                    if size < 1024:
                        size_human = f"{size} B"
                    elif size < 1024 * 1024:
                        size_human = f"{size / 1024:.1f} KB"
                    else:
                        size_human = f"{size / (1024 * 1024):.1f} MB"
                    
                    files.append(LogFileInfo(
                        name=name,
                        size=size,
                        size_human=size_human,
                        modified=f"{parts[5]} {parts[6]} {parts[7]}" if len(parts) >= 8 else None
                    ))
            
            return files
        except Exception as e:
            sys_error("lifecycle", f"Failed to list remote log files: {e}", exception=e)
            return []
    
    async def get_sync_state(self, db: AsyncSession, array_id: str) -> Optional[SyncState]:
        """Get current sync state for an array"""
        result = await db.execute(
            select(SyncStateModel).where(SyncStateModel.array_id == array_id)
        )
        state = result.scalar()
        if state:
            return SyncState.from_orm(state)
        return None
    
    async def _update_sync_state(
        self,
        db: AsyncSession,
        array_id: str,
        log_file: str,
        position: int,
        timestamp: Optional[datetime],
        imported_count: int
    ):
        """Update or create sync state"""
        result = await db.execute(
            select(SyncStateModel).where(SyncStateModel.array_id == array_id)
        )
        state = result.scalar()
        
        if state:
            state.log_file = log_file
            state.last_position = position
            state.last_timestamp = timestamp
            state.last_sync_at = datetime.now()
            state.total_imported += imported_count
        else:
            state = SyncStateModel(
                array_id=array_id,
                log_file=log_file,
                last_position=position,
                last_timestamp=timestamp,
                last_sync_at=datetime.now(),
                total_imported=imported_count
            )
            db.add(state)
        
        await db.commit()
    
    def _compute_message_hash(self, timestamp: str, observer: str, message: str) -> str:
        """Compute hash for deduplication"""
        content = f"{timestamp}|{observer}|{message}"
        return hashlib.md5(content.encode()).hexdigest()[:16]
    
    async def _get_existing_hashes(
        self,
        db: AsyncSession,
        array_id: str,
        start_time: datetime
    ) -> set:
        """Get existing alert hashes for deduplication"""
        result = await db.execute(
            select(AlertModel.timestamp, AlertModel.observer_name, AlertModel.message)
            .where(AlertModel.array_id == array_id)
            .where(AlertModel.timestamp >= start_time)
        )
        
        hashes = set()
        for row in result.all():
            ts_str = row[0].isoformat() if row[0] else ""
            h = self._compute_message_hash(ts_str, row[1], row[2])
            hashes.add(h)
        
        return hashes
    
    async def import_history(
        self,
        db: AsyncSession,
        array_id: str,
        mode: str = "incremental",
        days: int = 7,
        log_files: Optional[List[str]] = None,
        log_path: str = "/var/log/observation-points/alerts.log"
    ) -> ImportResult:
        """
        Import historical alerts from remote array.
        
        Modes:
        - incremental: Import last N days from current log file
        - full: Import all available log files
        - selective: Import specified log files
        """
        if not self.ssh_conn or not self.ssh_conn.is_connected():
            return ImportResult(
                success=False,
                imported_count=0,
                skipped_count=0,
                message="Not connected to array"
            )
        
        log_dir = "/".join(log_path.rsplit("/", 1)[:-1]) or "/var/log/observation-points"
        
        # Determine which files to import
        if mode == "selective" and log_files:
            files_to_import = log_files
        elif mode == "full":
            remote_files = await self.get_remote_log_files(log_dir)
            files_to_import = [f.name for f in remote_files]
        else:  # incremental
            files_to_import = ["alerts.log"]
        
        # Get existing hashes for deduplication
        cutoff_time = datetime.now() - timedelta(days=max(days, 30))
        existing_hashes = await self._get_existing_hashes(db, array_id, cutoff_time)
        
        total_imported = 0
        total_skipped = 0
        
        for filename in files_to_import:
            file_path = f"{log_dir}/{filename}"
            
            # Read file content
            try:
                if filename.endswith('.gz'):
                    # Compressed file
                    cmd = f"zcat {file_path} 2>/dev/null || true"
                else:
                    cmd = f"cat {file_path} 2>/dev/null || true"
                
                content = self.ssh_conn.exec_command(cmd)
                if not content:
                    continue
                
                # Parse and filter alerts
                alerts_to_create = []
                for line in content.strip().split('\n'):
                    if not line.strip():
                        continue
                    
                    try:
                        alert_data = json.loads(line)
                        
                        timestamp_str = alert_data.get('timestamp', '')
                        observer = alert_data.get('observer_name', 'unknown')
                        message = alert_data.get('message', '')
                        
                        # Skip if too old (incremental mode)
                        if mode == "incremental" and timestamp_str:
                            try:
                                ts = datetime.fromisoformat(timestamp_str.replace('Z', ''))
                                if ts < datetime.now() - timedelta(days=days):
                                    continue
                            except:
                                pass
                        
                        # Check for duplicates
                        msg_hash = self._compute_message_hash(timestamp_str, observer, message)
                        if msg_hash in existing_hashes:
                            total_skipped += 1
                            continue
                        
                        existing_hashes.add(msg_hash)
                        
                        # Parse timestamp
                        try:
                            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', ''))
                        except:
                            timestamp = datetime.now()
                        
                        # Parse level
                        level_str = alert_data.get('level', 'info').lower()
                        level = level_str if level_str in ['info', 'warning', 'error', 'critical'] else 'info'
                        
                        alerts_to_create.append(AlertModel(
                            array_id=array_id,
                            observer_name=observer,
                            level=level,
                            message=message,
                            details=json.dumps(alert_data.get('details', {}), ensure_ascii=False),
                            timestamp=timestamp,
                        ))
                        
                    except json.JSONDecodeError:
                        continue
                
                # Batch insert
                if alerts_to_create:
                    db.add_all(alerts_to_create)
                    await db.commit()
                    total_imported += len(alerts_to_create)
                    
            except Exception as e:
                sys_error("lifecycle", f"Failed to import {filename}: {e}", exception=e)
                continue
        
        # Update sync state
        await self._update_sync_state(
            db, array_id, "alerts.log", 0,
            datetime.now(), total_imported
        )
        
        sys_info("lifecycle", f"Import completed for {array_id}", {
            "imported": total_imported,
            "skipped": total_skipped,
            "mode": mode
        })
        
        return ImportResult(
            success=True,
            imported_count=total_imported,
            skipped_count=total_skipped,
            message=f"导入完成: {total_imported} 条新告警, {total_skipped} 条重复跳过"
        )
    
    async def sync_incremental(
        self,
        db: AsyncSession,
        array_id: str,
        content: str
    ) -> Tuple[int, int]:
        """
        Incremental sync from provided log content.
        Returns (imported_count, skipped_count)
        """
        if not content:
            return 0, 0
        
        # Get existing hashes
        cutoff_time = datetime.now() - timedelta(days=30)
        existing_hashes = await self._get_existing_hashes(db, array_id, cutoff_time)
        
        imported = 0
        skipped = 0
        alerts_to_create = []
        last_timestamp = None
        
        for line in content.strip().split('\n'):
            if not line.strip():
                continue
            
            try:
                alert_data = json.loads(line)
                
                timestamp_str = alert_data.get('timestamp', '')
                observer = alert_data.get('observer_name', 'unknown')
                message = alert_data.get('message', '')
                
                # Check for duplicates
                msg_hash = self._compute_message_hash(timestamp_str, observer, message)
                if msg_hash in existing_hashes:
                    skipped += 1
                    continue
                
                existing_hashes.add(msg_hash)
                
                # Parse timestamp
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', ''))
                    last_timestamp = timestamp
                except:
                    timestamp = datetime.now()
                
                # Parse level
                level_str = alert_data.get('level', 'info').lower()
                level = level_str if level_str in ['info', 'warning', 'error', 'critical'] else 'info'
                
                alerts_to_create.append(AlertModel(
                    array_id=array_id,
                    observer_name=observer,
                    level=level,
                    message=message,
                    details=json.dumps(alert_data.get('details', {}), ensure_ascii=False),
                    timestamp=timestamp,
                ))
                
            except json.JSONDecodeError:
                continue
        
        if alerts_to_create:
            db.add_all(alerts_to_create)
            await db.commit()
            imported = len(alerts_to_create)
        
        # Update sync state
        if imported > 0:
            await self._update_sync_state(
                db, array_id, "alerts.log", 0, last_timestamp, imported
            )
        
        return imported, skipped
    
    async def get_archive_config(self, db: AsyncSession) -> ArchiveConfig:
        """Get archive configuration"""
        result = await db.execute(select(ArchiveConfigModel).limit(1))
        config = result.scalar()
        
        if config:
            return ArchiveConfig.from_orm(config)
        
        # Return default config
        return ArchiveConfig()
    
    async def update_archive_config(self, db: AsyncSession, config: ArchiveConfig) -> ArchiveConfig:
        """Update archive configuration"""
        result = await db.execute(select(ArchiveConfigModel).limit(1))
        db_config = result.scalar()
        
        if db_config:
            db_config.active_retention_days = config.active_retention_days
            db_config.archive_retention_days = config.archive_retention_days
            db_config.archive_enabled = config.archive_enabled
            db_config.auto_cleanup = config.auto_cleanup
        else:
            db_config = ArchiveConfigModel(
                active_retention_days=config.active_retention_days,
                archive_retention_days=config.archive_retention_days,
                archive_enabled=config.archive_enabled,
                auto_cleanup=config.auto_cleanup
            )
            db.add(db_config)
        
        await db.commit()
        return config
    
    async def archive_old_data(self, db: AsyncSession) -> Dict[str, int]:
        """
        Archive old data based on configuration.
        
        1. Move alerts older than active_retention_days to archive
        2. Delete archives older than archive_retention_days
        """
        config = await self.get_archive_config(db)
        
        if not config.archive_enabled:
            return {"archived": 0, "deleted": 0}
        
        active_cutoff = datetime.now() - timedelta(days=config.active_retention_days)
        archive_cutoff = datetime.now() - timedelta(days=config.archive_retention_days)
        
        # Get alerts to archive (older than active_retention but newer than archive_retention)
        result = await db.execute(
            select(AlertModel)
            .where(AlertModel.timestamp < active_cutoff)
            .where(AlertModel.timestamp >= archive_cutoff)
        )
        alerts_to_archive = result.scalars().all()
        
        archived_count = 0
        
        if alerts_to_archive:
            # Group by array_id and year_month
            groups: Dict[str, Dict[str, List]] = {}
            for alert in alerts_to_archive:
                year_month = alert.timestamp.strftime('%Y-%m')
                key = f"{alert.array_id}|{year_month}"
                
                if key not in groups:
                    groups[key] = {
                        'array_id': alert.array_id,
                        'year_month': year_month,
                        'alerts': []
                    }
                
                groups[key]['alerts'].append({
                    'timestamp': alert.timestamp.isoformat(),
                    'level': alert.level,
                    'observer_name': alert.observer_name,
                    'message': alert.message,
                    'details': alert.details,
                })
            
            # Create archive entries
            for key, group in groups.items():
                # Check if archive already exists
                result = await db.execute(
                    select(AlertsArchiveModel)
                    .where(AlertsArchiveModel.array_id == group['array_id'])
                    .where(AlertsArchiveModel.year_month == group['year_month'])
                )
                existing = result.scalar()
                
                alerts_data = group['alerts']
                
                if existing:
                    # Merge with existing
                    try:
                        existing_data = json.loads(gzip.decompress(existing.data_compressed).decode())
                        existing_data.extend(alerts_data)
                        alerts_data = existing_data
                    except:
                        pass
                    
                    existing.data_compressed = gzip.compress(
                        json.dumps(alerts_data, ensure_ascii=False).encode()
                    )
                    existing.record_count = len(alerts_data)
                else:
                    archive = AlertsArchiveModel(
                        array_id=group['array_id'],
                        year_month=group['year_month'],
                        data_compressed=gzip.compress(
                            json.dumps(alerts_data, ensure_ascii=False).encode()
                        ),
                        record_count=len(alerts_data)
                    )
                    db.add(archive)
                
                archived_count += len(group['alerts'])
            
            # Delete archived alerts from main table
            alert_ids = [a.id for a in alerts_to_archive]
            await db.execute(
                delete(AlertModel).where(AlertModel.id.in_(alert_ids))
            )
            await db.commit()
        
        # Delete old archives (older than archive_retention_days)
        deleted_count = 0
        if config.auto_cleanup:
            # Find archives older than retention
            old_year_month = archive_cutoff.strftime('%Y-%m')
            result = await db.execute(
                select(AlertsArchiveModel)
                .where(AlertsArchiveModel.year_month < old_year_month)
            )
            old_archives = result.scalars().all()
            
            for archive in old_archives:
                deleted_count += archive.record_count
                await db.delete(archive)
            
            await db.commit()
        
        if archived_count > 0 or deleted_count > 0:
            sys_info("lifecycle", "Archive completed", {
                "archived": archived_count,
                "deleted": deleted_count
            })
        
        return {"archived": archived_count, "deleted": deleted_count}
    
    async def get_archive_stats(self, db: AsyncSession) -> ArchiveStats:
        """Get archive statistics"""
        # Active count
        result = await db.execute(select(func.count(AlertModel.id)))
        active_count = result.scalar() or 0
        
        # Archive count and size
        result = await db.execute(
            select(
                func.sum(AlertsArchiveModel.record_count),
                func.sum(func.length(AlertsArchiveModel.data_compressed))
            )
        )
        row = result.one()
        archive_count = row[0] or 0
        archive_size = row[1] or 0
        
        # Oldest active
        result = await db.execute(
            select(func.min(AlertModel.timestamp))
        )
        oldest_active = result.scalar()
        
        # Oldest archive
        result = await db.execute(
            select(func.min(AlertsArchiveModel.year_month))
        )
        oldest_archive = result.scalar()
        
        return ArchiveStats(
            active_count=active_count,
            archive_count=archive_count,
            archive_size_bytes=archive_size,
            oldest_active=oldest_active,
            oldest_archive=oldest_archive
        )
    
    async def query_archive(
        self,
        db: AsyncSession,
        array_id: Optional[str] = None,
        year_month: Optional[str] = None
    ) -> List[Dict]:
        """Query archived alerts"""
        query = select(AlertsArchiveModel)
        
        if array_id:
            query = query.where(AlertsArchiveModel.array_id == array_id)
        if year_month:
            query = query.where(AlertsArchiveModel.year_month == year_month)
        
        result = await db.execute(query)
        archives = result.scalars().all()
        
        alerts = []
        for archive in archives:
            try:
                data = json.loads(gzip.decompress(archive.data_compressed).decode())
                for alert in data:
                    alert['array_id'] = archive.array_id
                    alerts.append(alert)
            except Exception as e:
                sys_error("lifecycle", f"Failed to decompress archive: {e}")
                continue
        
        # Sort by timestamp descending
        alerts.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        return alerts


# Global instance
_lifecycle_manager: Optional[DataLifecycleManager] = None


def get_lifecycle_manager() -> DataLifecycleManager:
    """Get global lifecycle manager instance"""
    global _lifecycle_manager
    if _lifecycle_manager is None:
        _lifecycle_manager = DataLifecycleManager()
    return _lifecycle_manager
