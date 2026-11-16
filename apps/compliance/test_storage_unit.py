import os
from unittest import TestCase
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import override_settings

if not settings.configured and not os.getenv("DJANGO_SETTINGS_MODULE"):
    settings.configure(SECRET_KEY="unit-tests", USE_TZ=True)

from .storage import R2ObjectStorageDeletionAdapter  # noqa: E402


class StoragePurgeTests(TestCase):
    def setUp(self):
        self.enterContext(
            override_settings(
                R2_ENDPOINT_URL="https://r2.example.test",
                R2_ACCESS_KEY_ID="key",
                R2_SECRET_ACCESS_KEY="unit-secret",
                R2_BUCKET_PRIVATE="private",
                R2_BUCKET_PUBLIC_DERIVED="derived",
            )
        )
        self.adapter = R2ObjectStorageDeletionAdapter.__new__(R2ObjectStorageDeletionAdapter)
        self.adapter.client = Mock()
        self.adapter.client.delete_objects.return_value = {}

    def test_large_purge_is_split_into_provider_supported_batches(self):
        self.assertEqual(self.adapter.delete_keys([f"object-{i}" for i in range(1001)]), 2002)
        self.assertEqual(
            [
                len(call.kwargs["Delete"]["Objects"])
                for call in self.adapter.client.delete_objects.call_args_list
            ],
            [1000, 1, 1000, 1],
        )
        self.assertEqual(
            {call.kwargs["Bucket"] for call in self.adapter.client.delete_objects.call_args_list},
            {"private", "derived"},
        )

    def test_partial_provider_failure_is_never_success(self):
        self.adapter.client.delete_objects.return_value = {"Errors": [{"Code": "AccessDenied"}]}
        with self.assertRaisesRegex(RuntimeError, "^erasure_storage_unavailable$"):
            self.adapter.delete_keys(["private-object"])

    def test_network_failure_is_sanitized_and_retryable(self):
        self.adapter.client.delete_objects.side_effect = OSError("private upstream detail")
        with self.assertRaisesRegex(RuntimeError, "^erasure_storage_unavailable$"):
            self.adapter.delete_keys(["private-object"])

    def test_empty_purge_does_not_call_provider(self):
        self.assertEqual(self.adapter.delete_keys([]), 0)
        self.adapter.client.delete_objects.assert_not_called()

    @patch("apps.compliance.storage.boto3.client")
    def test_missing_storage_settings_fail_closed(self, client):
        with override_settings(R2_BUCKET_PRIVATE=""):
            with self.assertRaisesRegex(RuntimeError, "r2_not_configured"):
                R2ObjectStorageDeletionAdapter()
        client.assert_not_called()
