"""DT-005: real local Python CLI simulators, no AI calls or remote services."""

import json
import os
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from developer_team.adapters.codex_exec import (
    CodexExecGateway,
    ExecJob,
    ExecLimits,
    SimulatedExecProcess,
)
from developer_team.adapters.exec_agents import CodexExecAgents, exec_authority
from developer_team.adapters.synthetic import LocalDelivery, create_fixture
from developer_team.authority import ProjectGrant, RuntimePolicy
from developer_team.config import load_config
from developer_team.engine import Engine
from developer_team.models import PermissionDenied, Role, RunStatus, Stage, TeamError, digest
from developer_team.store import RunStore
from tests.support import EXAMPLE

FIXTURE = Path(__file__).with_name("exec_cli_fixture.py")


class ExecTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = RunStore(self.root / "state.db")
        self.job = ExecJob(
            str(uuid4()), "local/example", digest("config"), "a" * 40, Role.QA, 0, digest("inputs")
        )

    def simulator(self, source):
        path = self.root / "simulator.py"
        path.write_text(source)
        return SimulatedExecProcess(path)

    def gateway(self, source, **kwargs):
        return CodexExecGateway(self.store, self.simulator(source), **kwargs)

    def envelope_source(self, job=None):
        raw = json.dumps((job or self.job).envelope() | {"payload": {"ok": True}})
        return f"print({raw!r})"

    def test_live_is_unconditionally_blocked_before_process_creation(self):
        with patch("subprocess.Popen") as popen:
            with self.assertRaisesRegex(PermissionDenied, "Live codex exec blocked"):
                CodexExecGateway(self.store).execute(self.job, self.root, "hello")
            popen.assert_not_called()

    def test_result_intent_and_duplicate_remain_bound_after_restart(self):
        gateway = self.gateway(self.envelope_source())
        self.assertEqual(gateway.execute(self.job, self.root, "hello"), {"ok": True})
        self.assertEqual(self.store.exec_calls(self.job.run_id)[0]["state"], "completed")
        restarted = CodexExecGateway(RunStore(self.store.path), gateway.simulator)
        with self.assertRaisesRegex(TeamError, "never retry"):
            restarted.execute(self.job, self.root, "hello")
        self.assertEqual(
            [e["kind"] for e in self.store.events(self.job.run_id)],
            ["exec:intent", "exec:completed"],
        )

    def test_timeout_output_exit_encoding_and_malformed_results(self):
        for source in (
            "import time; time.sleep(5)",
            "import sys; sys.stderr.write('x' * 100000)",
            "raise SystemExit(2)",
            "import os; os.write(1, b'\\xff')",
            "print('{}')",
            'print(\'{"x":1,"x":2}\')',
            "import os, signal; os.kill(os.getpid(), signal.SIGTERM)",
        ):
            with self.subTest(source=source):
                job = replace(self.job, cycle=self.job.cycle + 1)
                self.job = job
                gateway = self.gateway(
                    source, limits=ExecLimits(timeout_seconds=1, output_bytes=1024)
                )
                with self.assertRaises(TeamError):
                    gateway.execute(job, self.root, "hello")
                self.assertEqual(self.store.exec_calls(job.run_id)[-1]["state"], "uncertain")

    def test_budget_deadline_and_limit_changes_survive_recreation(self):
        clock = [10.0]
        gateway = self.gateway(
            self.envelope_source(), limits=ExecLimits(max_calls=1), now=lambda: clock[0]
        )
        gateway.execute(self.job, self.root, "hello")
        with self.assertRaisesRegex(TeamError, "budget exhausted"):
            gateway.execute(replace(self.job, cycle=1), self.root, "hello")
        changed = CodexExecGateway(
            self.store, gateway.simulator, ExecLimits(max_calls=2), now=lambda: clock[0]
        )
        with self.assertRaisesRegex(TeamError, "limits changed"):
            changed.execute(replace(self.job, cycle=1), self.root, "hello")
        clock[0] = 400
        with self.assertRaisesRegex(TeamError, "runtime exhausted"):
            gateway.execute(replace(self.job, cycle=1), self.root, "hello")

    def test_unfinished_intent_never_retries_and_interrupt_is_recorded(self):
        gateway = self.gateway(self.envelope_source())
        with patch.object(gateway.simulator, "run", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                gateway.execute(self.job, self.root, "hello")
        self.assertEqual(self.store.exec_calls(self.job.run_id)[0]["state"], "uncertain")
        with self.assertRaises(TeamError):
            gateway.execute(self.job, self.root, "hello")

    def test_stale_role_input_and_sha_results_rejected(self):
        for changes in (
            {"role": Role.SECURITY},
            {"head_sha": "b" * 40},
            {"input_digest": digest("other")},
        ):
            with self.subTest(changes=changes):
                self.job = replace(self.job, cycle=self.job.cycle + 1)
                gateway = self.gateway(self.envelope_source(replace(self.job, **changes)))
                with self.assertRaises(TeamError):
                    gateway.execute(self.job, self.root, "hello")

    def test_environment_and_rlimits(self):
        source = """import os, resource
assert 'DT005_FAKE_SECRET' not in os.environ
assert 'HOME' not in os.environ
assert resource.getrlimit(resource.RLIMIT_AS)[0] == 268435456
assert resource.getrlimit(resource.RLIMIT_CPU)[0] == 5
assert resource.getrlimit(resource.RLIMIT_CORE)[0] == 0
""" + self.envelope_source()
        with patch.dict(os.environ, {"DT005_FAKE_SECRET": "dummy-test-value"}):
            self.gateway(source).execute(self.job, self.root, "hello")

    def test_invalid_limits_and_prompt(self):
        for limits in (
            ExecLimits(max_calls=True),
            ExecLimits(timeout_seconds=0),
            ExecLimits(output_bytes=10**9),
        ):
            with self.assertRaises(PermissionDenied):
                CodexExecGateway(self.store, limits=limits)
        gateway = self.gateway(self.envelope_source())
        with self.assertRaises(PermissionDenied):
            gateway.execute(self.job, self.root, "")
        self.assertEqual(self.store.exec_calls(self.job.run_id), [])

    def engine(self):
        workspace = create_fixture(self.root / "project")
        config = load_config(EXAMPLE)
        _, sealed = workspace.instructions(config)
        grant = ProjectGrant(
            config.id,
            config.repository,
            sealed,
            frozenset({"read", "develop", "pull_request", "exec_simulate"}),
            approved_by="test-controller",
        )
        gateway = CodexExecGateway(self.store, SimulatedExecProcess(FIXTURE))
        agents = CodexExecAgents(gateway, allowed_paths=("calculator.py", "tests/**", "docs/**"))
        delivery = LocalDelivery(workspace, config.repository)
        engine = Engine(
            config=config,
            workspace=workspace,
            agents=agents,
            delivery=delivery,
            store=self.store,
            authority=exec_authority(),
            grant=grant,
            policy=RuntimePolicy(),
        )
        return engine, delivery

    def test_engine_four_calls_separate_review_copies_and_manual_release(self):
        engine, delivery = self.engine()
        run = engine.execute("happy")
        self.assertEqual(run.status, RunStatus.BLOCKED, run.reasons)
        calls = self.store.exec_calls(run.id)
        self.assertEqual(
            [c["job"]["role"] for c in calls],
            ["orchestrator", "developer", "qa", "security"],
        )
        self.assertEqual(calls[2]["job"]["head_sha"], calls[3]["job"]["head_sha"])
        self.assertNotEqual(calls[2]["snapshot"], calls[3]["snapshot"])
        self.assertTrue(all(not Path(c["snapshot"]).exists() for c in calls))
        self.assertTrue(all(c["simulated"] for c in calls))
        verified = [c["controller_verification"] for c in calls]
        self.assertTrue(all(v["source"] == "controller:exec-result-validator-v1" for v in verified))
        self.assertTrue(all(v["execution_attested"] is False for v in verified))
        self.assertEqual(verified[2]["content_digest"], verified[3]["content_digest"])
        self.assertEqual(
            verified[2]["controller_checks_digest"], verified[3]["controller_checks_digest"]
        )
        self.assertNotEqual(verified[2]["inventory_digest"], verified[3]["inventory_digest"])
        self.assertEqual(
            sum(e["kind"] == "exec:controller-verified" for e in self.store.events(run.id)), 4
        )
        self.assertTrue(all(e.origin.value != "codex_cloud" for e in run.evidence))
        self.assertEqual(delivery.merge_calls, 0)

    def test_hidden_and_cross_controller_mutations_block_independent_verification(self):
        original = SimulatedExecProcess.run
        for mode in ("ignored", "git-config", "controller"):
            with self.subTest(mode=mode):
                other = ExecTests()
                other.setUp()
                try:
                    engine, delivery = other.engine()

                    def mutate(
                        simulator,
                        argv,
                        root,
                        limits,
                        *,
                        mutation=mode,
                        controller=engine.workspace.root,
                    ):
                        raw = original(simulator, argv, root, limits)
                        role = json.loads(argv[-1])["job"]["binding"]["role"]
                        if role == "qa":
                            if mutation == "ignored":
                                exclude = root / ".git/info/exclude"
                                exclude.write_text(exclude.read_text() + "\nhidden-output\n")
                                (root / "hidden-output").write_text("synthetic tampering")
                            elif mutation == "git-config":
                                config = root / ".git/config"
                                config.write_text(config.read_text() + "\n# synthetic mutation\n")
                            else:
                                config = controller / ".git/config"
                                config.write_text(config.read_text() + "\n# synthetic mutation\n")
                        return raw

                    with patch.object(SimulatedExecProcess, "run", mutate):
                        run = engine.execute("happy")
                    self.assertEqual(run.status, RunStatus.ESCALATED, run.reasons)
                    self.assertIn("mutated", " ".join(run.reasons))
                    calls = other.store.exec_calls(run.id)
                    self.assertNotIn("controller_verification", calls[-1])
                    self.assertEqual(delivery.merge_calls, 0)
                finally:
                    other.doCleanups()

    def test_simulator_test_claims_cannot_replace_failing_controller_checks(self):
        from developer_team.execution import SyntheticCommandRunner

        engine, delivery = self.engine()
        engine.runner = SyntheticCommandRunner(audit_directory=self.root / "checks")
        original = SyntheticCommandRunner.run

        def failing_check(runner, check, root):
            failing = replace(check, argv=(sys.executable, "-I", "-c", "raise SystemExit(7)"))
            return original(runner, failing, root)

        with patch.object(SyntheticCommandRunner, "run", failing_check):
            run = engine.execute("happy")
        self.assertEqual(run.status, RunStatus.ESCALATED, run.reasons)
        results = [json.loads(p.read_text()) for p in (self.root / "checks").glob("*.json")]
        self.assertTrue(results)
        self.assertTrue(all(r["returncode"] == 7 and r["outcome"] == "fail" for r in results))
        self.assertFalse(
            any(c["job"]["role"] in ("qa", "security") for c in self.store.exec_calls(run.id))
        )
        self.assertEqual(delivery.merge_calls, 0)

    def test_verification_diagnostics_require_completed_transport_and_are_not_reissued(self):
        gateway = self.gateway(self.envelope_source())
        with self.assertRaisesRegex(TeamError, "unique completed"):
            self.store.record_exec_verification(self.job.id, {"execution_attested": True})
        gateway.execute(self.job, self.root, "hello")
        self.store.record_exec_verification(self.job.id, {"execution_attested": False})
        with self.assertRaisesRegex(TeamError, "unique completed"):
            self.store.record_exec_verification(self.job.id, {"execution_attested": True})

    def test_protected_patch_review_mutation_and_contradictory_pass_escalate(self):
        for mode, reason in (
            ("protected", "scope"),
            ("mutate-review", "mutated"),
            ("contradictory", "Contradictory PASS"),
        ):
            with self.subTest(mode=mode):
                other = ExecTests()
                other.setUp()
                try:
                    engine, delivery = other.engine()
                    run = engine.execute(mode)
                    self.assertEqual(run.status, RunStatus.ESCALATED, run.reasons)
                    self.assertIn(reason, " ".join(run.reasons))
                    self.assertEqual(delivery.merge_calls, 0)
                finally:
                    other.doCleanups()

    def test_engine_resume_uses_existing_state_machine(self):
        engine, _ = self.engine()
        run = engine.execute("happy", pause_before=Stage.QA)
        self.assertEqual(run.status, RunStatus.PAUSED)
        self.assertEqual(len(self.store.exec_calls(run.id)), 2)
        run = engine.execute("happy", run_id=run.id)
        self.assertEqual(run.status, RunStatus.BLOCKED, run.reasons)
        self.assertEqual(len(self.store.exec_calls(run.id)), 4)

    def test_missing_exec_grant_and_live_policy_refuse_before_calls(self):
        engine, _ = self.engine()
        for grant, policy in (
            (replace(engine.grant, capabilities=frozenset({"read"})), engine.policy),
            (engine.grant, RuntimePolicy(safe_test_mode=False)),
        ):
            with self.assertRaises((PermissionDenied, TeamError)):
                engine.agents.validate_session(
                    engine.config, engine.effective_digest, self.store, grant, policy
                )
        self.assertEqual(self.store.exec_calls(str(uuid4())), [])

    def test_cpu_and_memory_exhaustion_fail_closed(self):
        for source in ("while True: pass", "x = bytearray(1024 * 1024 * 1024)"):
            with self.subTest(source=source):
                self.job = replace(self.job, cycle=self.job.cycle + 1)
                gateway = self.gateway(source, limits=ExecLimits(cpu_seconds=1))
                with self.assertRaises(TeamError):
                    gateway.execute(self.job, self.root, "hello")
                self.assertEqual(self.store.exec_calls(self.job.run_id)[-1]["state"], "uncertain")

    def test_descendant_is_killed_after_successful_parent(self):
        marker = self.root / "descendant-ran"
        child = f"import time; time.sleep(1); open({str(marker)!r}, 'w').write('unsafe')"
        source = (
            "import subprocess, sys\n"
            f"subprocess.Popen([sys.executable, '-I', '-c', {child!r}], "
            "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        ) + self.envelope_source()
        self.gateway(source).execute(self.job, self.root, "hello")
        # A separate bounded trusted process provides the observation window.
        import subprocess

        subprocess.run(
            [sys.executable, "-I", "-c", "import time; time.sleep(1.2)"], check=True, timeout=3
        )
        self.assertFalse(marker.exists())

    def test_hard_crash_intent_and_total_deadline_discard_results(self):
        gateway = self.gateway(self.envelope_source(), now=lambda: 10)
        record = {
            "id": self.job.id,
            "run_id": self.job.run_id,
            "limits": asdict(ExecLimits()),
            "created_at": 10,
        }
        self.store.reserve_exec_call(record, 10)
        with self.assertRaisesRegex(TeamError, "never retry"):
            gateway.execute(self.job, self.root, "hello")
        with self.assertRaisesRegex(TeamError, "discard output"):
            self.store.check_exec_runtime(self.job.run_id, 311)

    def test_atomic_reservation_prevents_parallel_budget_overspend(self):
        from concurrent.futures import ThreadPoolExecutor

        self.store.initialize_exec_journal()

        def reserve(index):
            record = {
                "id": str(index),
                "run_id": self.job.run_id,
                "limits": {"runtime_seconds": 300, "max_calls": 1},
                "created_at": 10,
            }
            try:
                self.store.reserve_exec_call(record, 10)
            except TeamError:
                return False
            return True

        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(reserve, range(4))), 1)
        self.assertEqual(len(self.store.exec_calls(self.job.run_id)), 1)
