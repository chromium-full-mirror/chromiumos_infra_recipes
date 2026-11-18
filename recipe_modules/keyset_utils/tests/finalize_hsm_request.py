# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for finalize_hsm_request in keyset_utils recipe module."""

from PB.chromite.api import signing
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

DEPS = [
    "recipe_engine/assertions",
    "recipe_engine/path",
    "recipe_engine/properties",
    "keyset_utils",
]


def RunSteps(api: recipe_api.RecipeApi):
  req = signing.FinalizeKeysHsmRequest(
      keyset_name=api.properties.get("keyset_name", ""),
  )
  configured = api.keyset_utils.finalize_hsm_request(
      req,
      api.path.start_dir / "release-keys",
      "signing:latest",
      api.properties.get("is_staging", False),
      api.path.start_dir / "work",
  )
  api.assertions.assertEqual(configured.dry_run,
                             api.properties.get("is_staging", False))


def GenTests(api: recipe_test_api.RecipeTestApi):
  yield api.test(
      "basic",
      api.properties(keyset_name="FooPreMPKeys", is_staging=True),
      api.post_check(
          post_process.LogEquals,
          "requested keyset",
          "keyset_name",
          "FooPreMPKeys",
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "missing-keyset-name-failure",
      api.post_check(
          post_process.SummaryMarkdownRE,
          r".*`keyset_name` \(in `finalize_keys_hsm_request`\) must be specified.*",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "keyset-exists-failure",
      api.properties(keyset_name="FooPreMPKeys"),
      api.path.exists(api.path.start_dir /
                      "release-keys/keyset/public/FooPreMPKeys"),
      api.post_check(
          post_process.SummaryMarkdownRE,
          r".*Keyset `FooPreMPKeys` already exists.*",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )
