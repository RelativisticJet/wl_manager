"""
Integration tests for pipeline architecture and complex POST handlers.

Tests verify that the pipeline abstraction layer works correctly,
all domain modules are integrated properly, and pipeline functions
handle errors gracefully.

No Docker container or Splunk runtime required.
"""

import pytest
import sys
from pathlib import Path

# Add bin/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "bin"))


class TestPipelineArchitecture:
    """Tests verifying the pipeline architecture works correctly."""

    def test_pipelines_module_imports(self):
        """wl_pipelines module can be imported and provides expected exports."""
        import importlib
        pipes = importlib.import_module('wl_pipelines')

        assert hasattr(pipes, 'save_csv_pipeline')
        assert hasattr(pipes, 'create_csv_pipeline')
        assert hasattr(pipes, 'revert_csv_pipeline')
        assert hasattr(pipes, 'create_rule_pipeline')
        assert hasattr(pipes, 'remove_rule_pipeline')
        assert hasattr(pipes, 'remove_csv_pipeline')
        assert hasattr(pipes, 'restore_csv_pipeline')

    def test_pipeline_return_tuples(self):
        """Pipeline functions return (success, message, data) tuples."""
        import importlib
        pipes = importlib.import_module('wl_pipelines')

        result = pipes.save_csv_pipeline("nonexistent.csv", [], user="test")
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)
        assert isinstance(result[2], dict)
