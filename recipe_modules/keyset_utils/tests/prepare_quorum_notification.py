# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for prepare_quorum_notification in keyset_utils recipe module."""

from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

DEPS = [
    "recipe_engine/properties",
    "keyset_utils",
]


def RunSteps(api: recipe_api.RecipeApi):
  is_staging = bool(api.properties.get("is_staging", False))
  api.keyset_utils.prepare_quorum_notification(
      keyset_name="test-keys",
      inbox_uri="gs://test-bucket/test-keys/123",
      is_staging=is_staging,
  )


def GenTests(api: recipe_test_api.RecipeTestApi):
  """Test cases for prepare_quorum_notification."""

  yield api.test(
      "staging",
      api.properties(is_staging=True),
      api.post_check(
          post_process.MustRun,
          "prepare quorum notification",
      ),
      api.post_check(
          post_process.MustRun,
          "prepare quorum notification.set quorum notification properties",
      ),
      api.post_check(
          post_process.PropertyEquals,
          "subject",
          "[STAGING] Quorum artifacts staged for test-keys",
      ),
      api.post_check(
          post_process.PropertyEquals,
          "inbox_uri",
          "gs://test-bucket/test-keys/123",
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "prod",
      api.properties(is_staging=False),
      api.post_check(
          post_process.MustRun,
          "prepare quorum notification",
      ),
      api.post_check(
          post_process.MustRun,
          "prepare quorum notification.set quorum notification properties",
      ),
      api.post_check(
          post_process.PropertyEquals,
          "subject",
          "Quorum artifacts staged for test-keys",
      ),
      api.post_check(
          post_process.PropertyEquals,
          "inbox_uri",
          "gs://test-bucket/test-keys/123",
      ),
      api.post_process(post_process.DropExpectation),
  )
