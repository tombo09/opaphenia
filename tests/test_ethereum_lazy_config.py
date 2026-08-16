import logging
import os
import subprocess
import sys
import unittest
import asyncio
from unittest.mock import patch


from app import utils
from app import thought_delivery


class EthereumLazyConfigurationTests(unittest.TestCase):
    def test_import_main_without_eth_pk(self):
        env = os.environ.copy()
        env.pop("ETH_PK", None)
        result = subprocess.run(
            [sys.executable, "-c", "import app.main"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_startup_and_unrelated_endpoint_without_eth_pk(self):
        from app import main

        with (
            patch.dict(os.environ, {}, clear=False),
            patch.object(main, "init_db"),
            patch.object(main, "run_migrations"),
            patch.object(main, "start_recovery_worker") as start_worker,
            patch.object(main, "start_email_outbox_worker") as start_email_worker,
            patch.object(
                main, "start_rate_limit_cleanup_worker"
            ) as start_cleanup_worker,
        ):
            os.environ.pop("ETH_PK", None)
            stop = unittest.mock.Mock()
            thread = unittest.mock.Mock()
            start_worker.return_value = (stop, thread)
            email_stop = unittest.mock.Mock()
            email_thread = unittest.mock.Mock()
            start_email_worker.return_value = (email_stop, email_thread)
            cleanup_stop = unittest.mock.Mock()
            cleanup_thread = unittest.mock.Mock()
            start_cleanup_worker.return_value = (cleanup_stop, cleanup_thread)
            async def run_lifespan():
                async with main.lifespan(main.app):
                    return next(
                        route.endpoint
                        for route in main.app.routes
                        if getattr(route, "path", None) == "/"
                    )()

            response = asyncio.run(run_lifespan())
            self.assertEqual(response.status_code, 200)
            stop.set.assert_called_once()
            email_stop.set.assert_called_once()
            cleanup_stop.set.assert_called_once()

    def test_signer_missing_fails_cleanly(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ETH_PK", None)
            with (
                patch.object(thought_delivery, "_claim") as claim,
                self.assertRaisesRegex(
                    utils.EthereumConfigurationError,
                    "Ethereum signing is unavailable",
                ) as raised,
            ):
                thought_delivery.prepare_thought(123)
        claim.assert_not_called()
        self.assertNotIn("0x", str(raised.exception))

    def test_signer_works_when_key_is_supplied(self):
        private_key = "0x" + "1" * 64
        with patch.dict(os.environ, {"ETH_PK": private_key}):
            signer = utils.get_ethereum_signer()
        self.assertEqual(signer.account.address, signer.address)
        self.assertNotEqual(signer.address, private_key)

    def test_invalid_key_never_appears_in_exception_or_logs(self):
        private_key = "not-a-valid-private-key-secret"
        logger = logging.getLogger("app.thought_delivery")
        with (
            patch.dict(os.environ, {"ETH_PK": private_key}),
            self.assertLogs(logger, level="ERROR") as captured,
        ):
            with self.assertRaises(utils.EthereumConfigurationError) as raised:
                utils.get_ethereum_signer()
            logger.error("Ethereum signing configuration is invalid")
        output = str(raised.exception) + "\n" + "\n".join(captured.output)
        self.assertNotIn(private_key, output)


if __name__ == "__main__":
    unittest.main()
