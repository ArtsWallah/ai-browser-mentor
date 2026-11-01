import os
import logging
from pathlib import Path
import numpy as np
import pytest

from app.services.memory_diagnostics import (
    is_memory_diagnostics_enabled,
    read_proc_status,
    read_proc_meminfo,
    read_cgroup_memory_stats,
    get_memory_stats,
    format_memory_diagnostic,
    log_memory_checkpoint,
    ENV_ENABLE_MEMORY_DIAGNOSTICS,
    ENV_CGROUP_ROOT,
)


class TestMemoryDiagnosticsConfiguration:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv(ENV_ENABLE_MEMORY_DIAGNOSTICS, raising=False)
        assert is_memory_diagnostics_enabled() is False

    @pytest.mark.parametrize("falsy_value", ["0", "false", "no", "off", "FALSE", "", "random"])
    def test_disabled_for_falsy_values(self, monkeypatch, falsy_value):
        monkeypatch.setenv(ENV_ENABLE_MEMORY_DIAGNOSTICS, falsy_value)
        assert is_memory_diagnostics_enabled() is False

    @pytest.mark.parametrize("truthy_value", ["1", "true", "yes", "on", "True", "TRUE", " true "])
    def test_enabled_for_truthy_values(self, monkeypatch, truthy_value):
        monkeypatch.setenv(ENV_ENABLE_MEMORY_DIAGNOSTICS, truthy_value)
        assert is_memory_diagnostics_enabled() is True


class TestProcParsingAndStats:
    def test_parse_proc_status_and_meminfo_conversion(self, tmp_path):
        proc_dir = tmp_path / "proc"
        proc_dir.mkdir()
        status_file = proc_dir / "status"
        meminfo_file = proc_dir / "meminfo"

        # 102400 kB = 100.0 MB, 153600 kB = 150.0 MB
        status_file.write_text(
            "Name:\tpython\n"
            "VmPeak:\t204800 kB\n"
            "VmSize:\t180000 kB\n"
            "VmHWM:\t153600 kB\n"
            "VmRSS:\t102400 kB\n",
            encoding="utf-8"
        )

        # 2097152 kB = 2048.0 MB, 4194304 kB = 4096.0 MB
        meminfo_file.write_text(
            "MemTotal:\t4194304 kB\n"
            "MemFree:\t1048576 kB\n"
            "MemAvailable:\t2097152 kB\n",
            encoding="utf-8"
        )

        stats = get_memory_stats(proc_root=proc_dir, cgroup_root=tmp_path / "empty_cg")
        assert stats["pid"] == os.getpid()
        assert stats["rss_mb"] == 100.0
        assert stats["peak_rss_mb"] == 150.0
        assert stats["sys_available_mb"] == 2048.0
        assert stats["sys_total_mb"] == 4096.0

    def test_parse_proc_status_fallback_to_vmrss_when_vmhwm_missing(self, tmp_path):
        proc_dir = tmp_path / "proc"
        proc_dir.mkdir()
        status_file = proc_dir / "status"
        status_file.write_text(
            "Name:\tpython\n"
            "VmRSS:\t51200 kB\n",
            encoding="utf-8"
        )

        stats = get_memory_stats(proc_root=proc_dir, cgroup_root=tmp_path / "empty_cg")
        assert stats["rss_mb"] == 50.0
        assert stats["peak_rss_mb"] == 50.0

    def test_graceful_fallback_when_proc_unavailable(self, tmp_path):
        non_existent_dir = tmp_path / "does_not_exist"
        stats = get_memory_stats(proc_root=non_existent_dir, cgroup_root=non_existent_dir)

        assert isinstance(stats, dict)
        assert stats["pid"] == os.getpid()
        assert stats["rss_mb"] is None
        assert stats["sys_available_mb"] is None
        assert stats["sys_total_mb"] is None
        assert stats["container_memory_used_mb"] is None
        assert stats["container_memory_limit_mb"] is None
        assert stats["container_memory_peak_mb"] is None
        assert stats["container_memory_percent"] is None


class TestCgroupMemoryMetrics:
    def test_cgroup_v2_complete_metrics(self, tmp_path):
        cg = tmp_path / "cgroup_v2"
        cg.mkdir()

        # 209715200 bytes = 200.0 MB used
        (cg / "memory.current").write_text("209715200\n", encoding="utf-8")
        # 524288000 bytes = 500.0 MB limit
        (cg / "memory.max").write_text("524288000\n", encoding="utf-8")
        # 314572800 bytes = 300.0 MB peak
        (cg / "memory.peak").write_text("314572800\n", encoding="utf-8")

        stats = read_cgroup_memory_stats(cgroup_root=cg)
        assert stats["container_memory_used_mb"] == 200.0
        assert stats["container_memory_limit_mb"] == 500.0
        assert stats["container_memory_peak_mb"] == 300.0
        assert stats["container_memory_percent"] == 40.0

    def test_cgroup_v2_unlimited_max(self, tmp_path):
        cg = tmp_path / "cgroup_v2_unlimited"
        cg.mkdir()

        (cg / "memory.current").write_text("104857600\n", encoding="utf-8")
        (cg / "memory.max").write_text("max\n", encoding="utf-8")

        stats = read_cgroup_memory_stats(cgroup_root=cg)
        assert stats["container_memory_used_mb"] == 100.0
        assert stats["container_memory_limit_mb"] is None
        assert stats["container_memory_peak_mb"] is None
        assert stats["container_memory_percent"] is None

    def test_cgroup_v1_subfolder_metrics(self, tmp_path):
        cg = tmp_path / "cgroup_v1"
        mem_dir = cg / "memory"
        mem_dir.mkdir(parents=True)

        # 104857600 bytes = 100.0 MB used
        (mem_dir / "memory.usage_in_bytes").write_text("104857600\n", encoding="utf-8")
        # 209715200 bytes = 200.0 MB limit
        (mem_dir / "memory.limit_in_bytes").write_text("209715200\n", encoding="utf-8")
        # 157286400 bytes = 150.0 MB peak
        (mem_dir / "memory.max_usage_in_bytes").write_text("157286400\n", encoding="utf-8")

        stats = read_cgroup_memory_stats(cgroup_root=cg)
        assert stats["container_memory_used_mb"] == 100.0
        assert stats["container_memory_limit_mb"] == 200.0
        assert stats["container_memory_peak_mb"] == 150.0
        assert stats["container_memory_percent"] == 50.0

    def test_cgroup_v1_flat_folder_metrics(self, tmp_path):
        cg = tmp_path / "cgroup_v1_flat"
        cg.mkdir()

        (cg / "memory.usage_in_bytes").write_text("52428800\n", encoding="utf-8")
        (cg / "memory.limit_in_bytes").write_text("104857600\n", encoding="utf-8")

        stats = read_cgroup_memory_stats(cgroup_root=cg)
        assert stats["container_memory_used_mb"] == 50.0
        assert stats["container_memory_limit_mb"] == 100.0
        assert stats["container_memory_percent"] == 50.0

    @pytest.mark.parametrize("unlimited_limit", ["9223372036854771712", "9223372036854775807", "1152921504606846976"])
    def test_cgroup_v1_unlimited_limits(self, tmp_path, unlimited_limit):
        cg = tmp_path / f"cg_v1_unlim_{unlimited_limit[:6]}"
        cg.mkdir()

        (cg / "memory.usage_in_bytes").write_text("104857600\n", encoding="utf-8")
        (cg / "memory.limit_in_bytes").write_text(f"{unlimited_limit}\n", encoding="utf-8")

        stats = read_cgroup_memory_stats(cgroup_root=cg)
        assert stats["container_memory_used_mb"] == 100.0
        assert stats["container_memory_limit_mb"] is None
        assert stats["container_memory_percent"] is None

    def test_cgroup_missing_files_graceful(self, tmp_path):
        empty_cg = tmp_path / "empty_cgroup"
        empty_cg.mkdir()

        stats = read_cgroup_memory_stats(cgroup_root=empty_cg)
        assert stats["container_memory_used_mb"] is None
        assert stats["container_memory_limit_mb"] is None
        assert stats["container_memory_peak_mb"] is None
        assert stats["container_memory_percent"] is None

    def test_cgroup_partially_missing_files(self, tmp_path):
        cg = tmp_path / "partial_cg"
        cg.mkdir()

        # memory.peak is absent (common on older kernels)
        (cg / "memory.current").write_text("209715200\n", encoding="utf-8")
        (cg / "memory.max").write_text("419430400\n", encoding="utf-8")

        stats = read_cgroup_memory_stats(cgroup_root=cg)
        assert stats["container_memory_used_mb"] == 200.0
        assert stats["container_memory_limit_mb"] == 400.0
        assert stats["container_memory_peak_mb"] is None
        assert stats["container_memory_percent"] == 50.0

    def test_cgroup_malformed_values(self, tmp_path):
        cg = tmp_path / "malformed_cg"
        cg.mkdir()

        (cg / "memory.current").write_text("corrupted_text\n", encoding="utf-8")
        (cg / "memory.max").write_text("NaN\n", encoding="utf-8")
        (cg / "memory.peak").write_text("", encoding="utf-8")

        stats = read_cgroup_memory_stats(cgroup_root=cg)
        assert stats["container_memory_used_mb"] is None
        assert stats["container_memory_limit_mb"] is None
        assert stats["container_memory_peak_mb"] is None
        assert stats["container_memory_percent"] is None

    def test_cgroup_zero_limit_prevents_zero_division(self, tmp_path):
        cg = tmp_path / "zero_limit_cg"
        cg.mkdir()

        (cg / "memory.current").write_text("104857600\n", encoding="utf-8")
        (cg / "memory.max").write_text("0\n", encoding="utf-8")

        stats = read_cgroup_memory_stats(cgroup_root=cg)
        assert stats["container_memory_used_mb"] == 100.0
        assert stats["container_memory_limit_mb"] == 0.0
        assert stats["container_memory_percent"] is None

    def test_cgroup_negative_limit_handled_safely(self, tmp_path):
        cg = tmp_path / "neg_limit_cg"
        cg.mkdir()

        (cg / "memory.current").write_text("104857600\n", encoding="utf-8")
        (cg / "memory.max").write_text("-524288000\n", encoding="utf-8")

        stats = read_cgroup_memory_stats(cgroup_root=cg)
        assert stats["container_memory_used_mb"] == 100.0
        assert stats["container_memory_limit_mb"] is None
        assert stats["container_memory_percent"] is None


class TestFormatMemoryDiagnostic:
    def test_format_with_complete_numeric_metrics(self):
        stats = {
            "pid": 9999,
            "rss_mb": 128.5,
            "peak_rss_mb": 256.0,
            "sys_available_mb": 1024.75,
            "container_memory_used_mb": 200.0,
            "container_memory_limit_mb": 512.0,
            "container_memory_peak_mb": 250.0,
            "container_memory_percent": 39.06,
        }
        msg = format_memory_diagnostic("test_checkpoint", stats)
        assert "[MEMORY-DIAGNOSTIC]" in msg
        assert "pid=9999" in msg
        assert "checkpoint='test_checkpoint'" in msg
        assert "rss_mb=128.50" in msg
        assert "peak_rss_mb=256.00" in msg
        assert "sys_available_mb=1024.75" in msg
        assert "container_memory_used_mb=200.00" in msg
        assert "container_memory_limit_mb=512.00" in msg
        assert "container_memory_peak_mb=250.00" in msg
        assert "container_memory_percent=39.06%" in msg

    def test_format_with_missing_metrics(self):
        stats = {
            "pid": 1234,
            "rss_mb": None,
            "peak_rss_mb": None,
            "sys_available_mb": None,
            "container_memory_used_mb": None,
            "container_memory_limit_mb": None,
            "container_memory_peak_mb": None,
            "container_memory_percent": None,
        }
        msg = format_memory_diagnostic("startup", stats)
        assert "[MEMORY-DIAGNOSTIC]" in msg
        assert "pid=1234" in msg
        assert "checkpoint='startup'" in msg
        assert "rss_mb=N/A" in msg
        assert "peak_rss_mb=N/A" in msg
        assert "sys_available_mb=N/A" in msg
        assert "container_memory_used_mb=N/A" in msg
        assert "container_memory_limit_mb=N/A" in msg
        assert "container_memory_peak_mb=N/A" in msg
        assert "container_memory_percent=N/A" in msg

    def test_format_contains_no_user_or_page_content(self):
        stats = {
            "pid": 1234,
            "rss_mb": 50.0,
            "peak_rss_mb": 60.0,
            "sys_available_mb": 500.0,
            "container_memory_used_mb": 80.0,
            "container_memory_limit_mb": 256.0,
            "container_memory_peak_mb": 90.0,
            "container_memory_percent": 31.25,
        }
        msg = format_memory_diagnostic("page_ingest_begin", stats)
        tokens = msg.split()
        assert tokens[0] == "[MEMORY-DIAGNOSTIC]"
        assert any(t.startswith("pid=") for t in tokens)
        assert any(t.startswith("checkpoint=") for t in tokens)
        assert any(t.startswith("rss_mb=") for t in tokens)
        assert any(t.startswith("peak_rss_mb=") for t in tokens)
        assert any(t.startswith("sys_available_mb=") for t in tokens)
        assert any(t.startswith("container_memory_used_mb=") for t in tokens)
        assert any(t.startswith("container_memory_limit_mb=") for t in tokens)
        assert any(t.startswith("container_memory_peak_mb=") for t in tokens)
        assert any(t.startswith("container_memory_percent=") for t in tokens)


class TestLogMemoryCheckpoint:
    def test_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.delenv(ENV_ENABLE_MEMORY_DIAGNOSTICS, raising=False)
        result = log_memory_checkpoint("test_checkpoint")
        assert result is None

    def test_logs_and_returns_stats_when_enabled(self, monkeypatch, tmp_path):
        monkeypatch.setenv(ENV_ENABLE_MEMORY_DIAGNOSTICS, "true")
        proc_dir = tmp_path / "proc"
        proc_dir.mkdir()
        (proc_dir / "status").write_text("VmRSS: 20480 kB\n", encoding="utf-8")

        cg_dir = tmp_path / "cg"
        cg_dir.mkdir()
        (cg_dir / "memory.current").write_text("52428800\n", encoding="utf-8")
        (cg_dir / "memory.max").write_text("104857600\n", encoding="utf-8")

        logged_messages = []
        test_logger = logging.getLogger("test_mem_diag")
        test_logger.setLevel(logging.INFO)

        class ListHandler(logging.Handler):
            def emit(self, record):
                logged_messages.append(record.getMessage())

        handler = ListHandler()
        test_logger.addHandler(handler)

        result = log_memory_checkpoint(
            "test_checkpoint",
            proc_root=proc_dir,
            cgroup_root=cg_dir,
            custom_logger=test_logger,
        )

        assert result is not None
        assert result["rss_mb"] == 20.0
        assert result["container_memory_used_mb"] == 50.0
        assert result["container_memory_limit_mb"] == 100.0
        assert result["container_memory_percent"] == 50.0
        assert len(logged_messages) == 1
        assert "checkpoint='test_checkpoint'" in logged_messages[0]
        assert "container_memory_used_mb=50.00" in logged_messages[0]
        assert "container_memory_percent=50.00%" in logged_messages[0]

    def test_force_logs_even_when_disabled(self, monkeypatch, tmp_path):
        monkeypatch.delenv(ENV_ENABLE_MEMORY_DIAGNOSTICS, raising=False)
        proc_dir = tmp_path / "proc"
        proc_dir.mkdir()
        (proc_dir / "status").write_text("VmRSS: 10240 kB\n", encoding="utf-8")

        result = log_memory_checkpoint(
            "forced_checkpoint",
            proc_root=proc_dir,
            cgroup_root=tmp_path / "empty_cg",
            force=True
        )
        assert result is not None
        assert result["rss_mb"] == 10.0

    def test_exception_in_logger_never_raises(self, monkeypatch):
        monkeypatch.setenv(ENV_ENABLE_MEMORY_DIAGNOSTICS, "true")

        class FaultyLogger:
            def info(self, msg):
                raise RuntimeError("Logger crashed")

        result = log_memory_checkpoint("safe_test", custom_logger=FaultyLogger())
        assert result is None


class TestCheckpointIntegration:
    def test_vector_store_create_index_invokes_checkpoints(self, monkeypatch):
        from app.services import vector_store

        checkpoints_seen = []

        def mock_checkpoint(name, *args, **kwargs):
            checkpoints_seen.append(name)
            return {"pid": 1}

        monkeypatch.setattr(vector_store, "log_memory_checkpoint", mock_checkpoint)

        dummy_embeddings = np.zeros((2, 384), dtype=np.float32)
        dummy_chunks = ["chunk1", "chunk2"]
        page_id = "test_memory_diag_page_123"

        try:
            vector_store.create_index(page_id, dummy_embeddings, dummy_chunks)
            assert "faiss_index_create_begin" in checkpoints_seen
            assert "faiss_index_create_complete" in checkpoints_seen
        finally:
            vector_store.delete_index(page_id)

    def test_embedding_service_invokes_checkpoints(self, monkeypatch):
        from app.services import embedding_service

        checkpoints_seen = []

        def mock_checkpoint(name, *args, **kwargs):
            checkpoints_seen.append(name)
            return {"pid": 1}

        monkeypatch.setattr(embedding_service, "log_memory_checkpoint", mock_checkpoint)

        class DummyModel:
            def embed(self, texts, **kwargs):
                return [np.zeros(384, dtype=np.float32) for _ in texts]

        monkeypatch.setattr(embedding_service, "get_model", lambda: DummyModel())

        embedding_service.embed_texts(["hello world"])
        assert "embedding_generation_begin" in checkpoints_seen
        assert "embedding_generation_complete" in checkpoints_seen

    def test_scamshield_load_model_invokes_checkpoints(self, monkeypatch, tmp_path):
        from app import scamshield_service
        import joblib

        checkpoints_seen = []

        def mock_checkpoint(name, *args, **kwargs):
            checkpoints_seen.append(name)
            return {"pid": 1}

        monkeypatch.setattr(scamshield_service, "log_memory_checkpoint", mock_checkpoint)
        monkeypatch.setattr("app.services.model_integrity.verify_model_artifact", lambda path: True)

        dummy_model = {
            "model_type": "per_tactic_binary_v1",
            "tactics": [],
            "models": {},
            "thresholds": {},
        }
        model_file = tmp_path / "dummy_scamshield.joblib"
        joblib.dump(dummy_model, model_file)

        monkeypatch.setenv("SCAMSHIELD_MODEL_PATH", str(model_file))
        scamshield_service.load_model.cache_clear()

        try:
            model = scamshield_service.load_model()
            assert model["model_type"] == "per_tactic_binary_v1"
            assert "scamshield_model_load_begin" in checkpoints_seen
            assert "scamshield_model_load_complete" in checkpoints_seen
        finally:
            scamshield_service.load_model.cache_clear()
