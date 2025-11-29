"""Streaming Parquet writer with batched writes for memory efficiency."""

from pathlib import Path
from typing import Dict, Any, List, Optional
import pyarrow as pa
import pyarrow.parquet as pq


class StreamingParquetWriter:
    """Write data to Parquet in batches to avoid memory issues."""

    def __init__(
        self,
        filepath: Path,
        schema: pa.Schema,
        batch_size: int = 1000
    ):
        """
        Initialize streaming Parquet writer.

        Args:
            filepath: Path to output Parquet file
            schema: PyArrow schema defining table structure
            batch_size: Number of rows to buffer before writing
        """
        self.filepath = filepath
        self.schema = schema
        self.batch_size = batch_size
        self.buffer: List[Dict[str, Any]] = []
        self.writer: Optional[pq.ParquetWriter] = None

    def write_row(self, row_dict: Dict[str, Any]) -> None:
        """
        Add a row to the buffer, flush if batch_size reached.

        Args:
            row_dict: Dictionary with keys matching schema field names
        """
        self.buffer.append(row_dict)

        if len(self.buffer) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        """Write buffered rows to Parquet file."""
        if not self.buffer:
            return

        # Convert buffer to PyArrow Table
        # Build column arrays from buffered rows
        arrays = {}
        for field in self.schema:
            field_name = field.name
            arrays[field_name] = [row.get(field_name) for row in self.buffer]

        table = pa.table(arrays, schema=self.schema)

        # Write to file
        if self.writer is None:
            # First write - create file
            self.writer = pq.ParquetWriter(
                self.filepath,
                self.schema,
                compression='snappy'
            )

        self.writer.write_table(table)

        # Clear buffer
        self.buffer = []

    def close(self) -> None:
        """Flush remaining rows and close writer."""
        self.flush()
        if self.writer:
            self.writer.close()
            self.writer = None
        elif not self.filepath.exists():
            # Create empty file if no data was written
            empty_table = pa.table({field.name: [] for field in self.schema}, schema=self.schema)
            pq.write_table(empty_table, self.filepath, compression='snappy')
