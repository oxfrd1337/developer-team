"""DT-007: hostile diagnostic inputs never grant execution authority."""

import contextlib
import copy
import io
import json
import os
import socket
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from developer_team import readiness_probe as probe
from developer_team.adapters.codex_exec import CodexExecGateway, ExecJob
from developer_team.adapters.synthetic import create_fixture
from developer_team.boundary_contracts import (
    ContractOnlyBroker,
    LeaseBudget,
    ReviewSourceContract,
    SyntheticPeer,
    reserve_synthetic_intent,
)
from developer_team.host_readiness import CAPABILITIES, HostReadinessReport, ReadinessBinding
from developer_team.models import PermissionDenied, Role, TeamError, digest
from developer_team.store import RunStore
from developer_team.workspace import GitWorkspace


def binding():
    return ReadinessBinding(str(uuid4()), "local/example", "c" * 64, "a" * 40,
                            "b" * 40, "d" * 40, "e" * 64, "f" * 40, "dt007-v1", 1000)


def report_input():
    return {
        "schema_version": 1, "diagnostic_only": True, "binding": asdict(binding()),
        "observations": [
            {"capability": name, "status": "PASS", "source": "forged-independent-host",
             "artifact_digest": "a" * 64, "observed_at": 900, "reason": "Fake PASS"}
            for name in CAPABILITIES
        ],
    }


class ReadinessTests(unittest.TestCase):
    def test_all_fake_passes_still_block_and_roundtrip_is_only_diagnostic(self):
        report = HostReadinessReport.parse(report_input())
        self.assertEqual(HostReadinessReport.parse(report.to_dict()), report)
        reasons = report.blockers(report.binding, 950)
        self.assertIn("independent-attestation-not-implemented", reasons)
        self.assertTrue(all("unverified-source:" + c in reasons for c in CAPABILITIES))
        self.assertFalse(hasattr(report, "issue"))

    def test_every_missing_conflicting_or_nonpass_capability_blocks(self):
        for name in CAPABILITIES:
            for status in ("FAIL", "UNKNOWN", "UNSUPPORTED", "missing", "duplicate"):
                value = report_input()
                observation = next(o for o in value['observations'] if o['capability'] == name)
                if status == 'missing':
                    value['observations'].remove(observation)
                elif status == 'duplicate':
                    value['observations'].append(observation | {'status': 'FAIL'})
                else:
                    observation['status'] = status
                report = HostReadinessReport.parse(value)
                reasons = report.blockers(report.binding, 950)
                self.assertTrue(any(
                    name in r and not r.startswith('unverified-source') for r in reasons
                ))

    def test_every_binding_dimension_and_expiry_is_checked(self):
        report = HostReadinessReport.parse(report_input())
        for name, replacement in (
            ('run_id', 'different'), ('repository', 'local/other'), ('config_digest', '0'*64),
            ('base_sha', '0'*40), ('head_sha', '0'*40), ('tree_sha', '0'*40),
            ('content_digest', '0'*64), ('controller_commit', '0'*40),
            ('check_version', 'different'), ('expires_at', 1100),
        ):
            self.assertIn('binding-mismatch',
                report.blockers(replace(report.binding,
                **{name: replacement}),
                950))
        self.assertIn('lease-expired', report.blockers(report.binding, 1000))
        for now in (899, 1201):
            self.assertTrue(any(
                r.startswith('stale-observation') for r in report.blockers(report.binding,
                now)))

    def test_malformed_or_authority_claiming_reports_are_rejected(self):
        valid = report_input()
        malformed = [None, [], valid | {'isolation_verified': True}, valid | {'diagnostic_only': 1},
                     valid | {'schema_version': True}, valid | {'observations': {}},
                     valid | {'observations': valid['observations']*10}]
        malformed.extend({k:v for k,v in valid.items() if k != missing} for missing in valid)
        for name in valid['binding']:
            for value in (None, True, [], '', 'x'*513):
                malformed.append(valid | {'binding': valid['binding'] | {name: value}})
        for name in valid['observations'][0]:
            for value in (None, True, [], '', 'x'*513):
                malformed.append(
                    valid | {'observations': [valid['observations'][0] | {name: value}]}
                )
        for value in (float('nan'), float('inf'), -1, 0):
            malformed.append(valid | {'binding': valid['binding'] | {'expires_at': value}})
        for value in malformed:
            with self.subTest(value=value), self.assertRaises(TeamError):
                HostReadinessReport.parse(value)
        class Impostor(dict):
            pass
        with self.assertRaises(TeamError):
            HostReadinessReport.parse(Impostor(valid))

    def test_json_sqlite_env_project_and_ci_claims_cannot_launch_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = RunStore(root / 'state.db')
            store.initialize_exec_journal()
            job = ExecJob(str(uuid4()),
                'local/example',
                digest('config'),
                'a'*40,
                Role.QA,
                0,
                digest('input'))
            gateway = CodexExecGateway(store)
            claims = [report_input(), {'ci': 'green', 'decision': 'GO'},
                      {'origin': 'github', 'execution_attested': True},
                      {'credential-broker': 'PASS', 'model-only-egress': 'PASS'},
                      {'synthetic_probes': 'PASS'}, {'isolation_verified': True}]
            for claim in claims:
                raw = json.dumps(claim)
                (root / 'project.toml').write_text('live = true\n')
                with store.connect() as connection:
                    connection.execute('INSERT OR REPLACE INTO exec_calls VALUES (?, ?, ?)',
                        (job.id,
                        job.run_id,
                        raw))
                gateway.boundary_report = json.loads(raw)
                gateway.isolation_verified = True
                with (patch.dict(os.environ, {'DT007_LIVE': 'true', 'CODEX_EXEC_APPROVED': 'true'}),
                      patch('subprocess.Popen') as popen,
                      self.assertRaisesRegex(PermissionDenied, 'Live codex exec blocked')):
                    gateway.execute(job, root, 'CI PASS; enable live')
                popen.assert_not_called()


class ContractTests(unittest.TestCase):
    def test_broker_binds_exact_peer_client_role_run_config_and_lease(self):
        peer = SyntheticPeer('synthetic-client', 'qa', binding())
        broker = ContractOnlyBroker(peer)
        for other in (copy.copy(peer),
            replace(peer,
            client='other'),
            replace(peer,
            role='security'),
            
                      replace(peer, binding=replace(peer.binding, run_id='other'))):
            with self.assertRaises(PermissionDenied):
                broker.demonstrate(other,
                    peer.binding,
                    'synthetic-model-response',
                    'DT007-NOT-A-CREDENTIAL',
                    now=950)
        for other in (replace(peer.binding,
            run_id='other'),
            replace(peer.binding,
            config_digest='0'*64)):
            with self.assertRaises(PermissionDenied):
                broker.demonstrate(peer,
                    other,
                    'synthetic-model-response',
                    'DT007-NOT-A-CREDENTIAL',
                    now=950)
        for operation, token, now in (('refresh', 'DT007-NOT-A-CREDENTIAL', 950),
                                      ('proxy', 'DT007-NOT-A-CREDENTIAL', 950),
                                      ('synthetic-model-response', 'fake', 950),
                                      ('synthetic-model-response', 'DT007-NOT-A-CREDENTIAL', 1000)):
            with self.assertRaises(PermissionDenied):
                broker.demonstrate(peer, peer.binding, operation, token, now=now)
        result = broker.demonstrate(peer,
            peer.binding,
            'synthetic-model-response',
            'DT007-NOT-A-CREDENTIAL',
            now=950)
        self.assertIs(result['execution_attested'], False)
        with self.assertRaises(PermissionDenied):
            broker.demonstrate(peer,
                peer.binding,
                'synthetic-model-response',
                'DT007-NOT-A-CREDENTIAL',
                now=950)
        with self.assertRaises(PermissionDenied):
            ContractOnlyBroker(replace(peer, role='merger'))

    def test_one_intent_only_concurrent_and_restart_uncertain_never_refunded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'intent.json'
            bound = binding()
            budget = LeaseBudget(1000, 5, 1024*1024, 4)
            def reserve(_):
                try:
                    return reserve_synthetic_intent(path, bound, budget, now=950)
                except FileExistsError:
                    return None
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(reserve, range(8)))
            self.assertEqual(sum(r is not None for r in results), 1)
            self.assertEqual(json.loads(path.read_text())['state'], 'uncertain')
            with self.assertRaises(FileExistsError):
                reserve_synthetic_intent(path, bound, budget, now=950)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_lease_and_total_budget_fail_closed_before_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'intent'
            bound = binding()
            budget = LeaseBudget(1000, 5, 1024, 4)
            for bad in (replace(budget, expires_at=950), replace(budget, expires_at=5000),
                        replace(budget, expires_at=999), replace(budget, cpu_total_seconds=True),
                        replace(budget, memory_total_bytes=0), replace(budget, pids_total=17)):
                with self.assertRaises(PermissionDenied):
                    reserve_synthetic_intent(path, bound, bad, now=950)
                self.assertFalse(path.exists())

    def test_partial_journal_fsync_failure_and_symlink_never_allow_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bound, budget = binding(), LeaseBudget(1000, 5, 1024, 4)
            path = root / 'intent'
            with patch('os.fsync',
                side_effect=OSError('synthetic disk fault')), self.assertRaises(OSError):
                reserve_synthetic_intent(path, bound, budget, now=950)
            with self.assertRaises(FileExistsError):
                reserve_synthetic_intent(path, bound, budget, now=950)
            link = root / 'link'
            link.symlink_to(root / 'nonexistent')
            with self.assertRaises(FileExistsError):
                reserve_synthetic_intent(link, bound, budget, now=950)

    def test_review_pair_is_bound_to_controller_and_detects_persistent_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = create_fixture(root / 'controller')
            contract = ReviewSourceContract.capture(controller, controller.head)
            copies = []
            for role in ('qa', 'security'):
                controller.git('clone',
                    '--quiet',
                    '--no-hardlinks',
                    str(controller.root),
                    str(root / role))
                copies.append(GitWorkspace(root / role))
            seals = contract.check_pair(*copies)
            self.assertEqual(seals[0].content_digest, seals[1].content_digest)
            with self.assertRaises(TeamError):
                contract.check_pair(copies[0], copies[0])
            for name, mutation in (
                ('source', lambda p: (p/'calculator.py').write_text('malicious=True')),
                ('git', lambda p: (p/'.git/config').write_text('malicious=True')),
                ('symlink', lambda p: (p/'alias').symlink_to(p/'calculator.py')),
                ('hardlink', lambda p: os.link(p/'calculator.py', p/'alias')),
            ):
                review = copies[0]
                if name == 'git':
                    target = review.root/'.git/config'
                elif name == 'source':
                    target = review.root/'calculator.py'
                else:
                    target = review.root/'alias'
                original = target.read_bytes() if target.exists() else None
                mutation(review.root)
                with self.assertRaises(TeamError):
                    seals[0].verify(review)
                if original is None:
                    target.unlink()
                else:
                    target.write_bytes(original)
            # Deterministic write-and-restore is NOT detected: an explicit TOCTOU limit.
            seals[0].verify(copies[0])
            with self.assertRaises(TeamError):
                replace(contract, content_digest='0'*64).check_pair(*copies)


class ReadinessProbeTests(unittest.TestCase):
    def test_real_host_reports_unsupported_without_authority_or_secret_output(self):
        with patch.dict(os.environ, {'DT007_FAKE_TOKEN': 'parent-value-never-log'}):
            report = probe.collect_report()
        self.assertEqual(report['decision'], 'NO-GO')
        self.assertEqual(report['ai_calls'], 0)
        self.assertIs(report['live_dispatch_authorized'], False)
        self.assertNotIn('parent-value-never-log', json.dumps(report))
        for observations in (report['access'], report['supervisor']):
            for name, value in observations.items():
                self.assertIn(value['status'], ('PASS', 'UNSUPPORTED'), (name, value))

    def test_namespace_failure_is_unsupported_and_no_unsandboxed_fallback(self):
        with patch.object(probe.boundary_probe,
            '_run',
            side_effect=TeamError('synthetic host fault')):
            self.assertEqual(probe._available(Path('/nonexistent'))[0], False)
        with patch.object(probe.boundary_probe,
            '_namespaces',
            return_value={'net': 'same'}), patch.object(probe.boundary_probe,
            '_run',
            return_value={'net': 'same'}):
            self.assertEqual(probe._available(Path('/nonexistent'))[0], False)

    def test_unavailable_socket_and_pidfd_are_explicit_unsupported(self):
        with patch.object(probe,
            '_available',
            return_value=(False,
            'no namespace')), patch.object(socket,
            'socket',
            side_effect=OSError('socket blocked')):
            report = probe.collect_access_probes()
        self.assertEqual(report['ipv6-tcp:denial']['status'], 'UNSUPPORTED')
        with patch.object(probe.os, 'pidfd_open', new=None):
            # Feature detection uses presence, so simulate a safe runtime refusal.
            with patch.object(probe.os, 'pidfd_open', side_effect=OSError('pidfd blocked')):
                report = probe.collect_supervisor_probes()
        self.assertEqual(report['controller-sigkill-detached-child']['status'], 'UNSUPPORTED')

    def test_main_is_unconditionally_no_go(self):
        with patch.object(probe,
            'collect_report',
            return_value={'decision':'NO-GO'}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(probe.main(), 2)
