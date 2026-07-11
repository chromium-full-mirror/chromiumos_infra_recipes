# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for keyset_utils recipe module."""

from PB.chromite.api import signing
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

DEPS = [
    "recipe_engine/file",
    "recipe_engine/path",
    "recipe_engine/properties",
    "recipe_engine/step",
    "keyset_utils",
]


def RunSteps(api: recipe_api.RecipeApi):
  req = signing.CreateKeysHsmRequest(
      keyset_name=api.properties.get("keyset_name", ""),
  )

  _, error_msg = api.keyset_utils.create_hsm_request(
      req,
      api.path.start_dir / "release-keys",
      "signing:latest",
      api.properties.get("is_staging", False),
      build_target=api.properties.get("build_target", ""),
      is_mp=api.properties.get("is_mp"),
  )
  if error_msg:
    return result_pb2.RawResult(
        status=common_pb2.FAILURE,
        summary_markdown=f"### Keyset Validation Failed\n\n{error_msg}",
    )
  return None


def GenTests(api: recipe_test_api.RecipeTestApi):
  yield api.test(
      "keyset-name-exists-failure",
      api.properties(keyset_name="AtlasMPKeys-v2"),
      api.path.exists(api.path.start_dir /
                      "release-keys/keyset/public/AtlasMPKeys-v2"),
      api.post_check(
          post_process.SummaryMarkdownRE,
          r".*Keyset `AtlasMPKeys-v2` already exists.*",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "keyset-name-success",
      api.properties(keyset_name="AtlasMPKeys-v3"),
      api.post_check(
          post_process.LogEquals,
          "requested keyset",
          "keyset_name",
          "AtlasMPKeys-v3",
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "target-calc-next",
      api.properties(
          build_target="atlas",
          is_mp=True,
      ),
      api.step_data(
          "calc next keyset version.list existing keysets",
          api.file.listdir(["AtlasMPKeys-v2"]),
      ),
      api.post_check(
          post_process.LogEquals,
          "requested keyset",
          "keyset_name",
          "AtlasMPKeys-v3",
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "target-calc-v1",
      api.properties(
          build_target="atlas",
          is_mp=True,
      ),
      api.step_data(
          "calc next keyset version.list existing keysets",
          api.file.listdir([]),
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "target-calc-version-gap",
      api.properties(
          build_target="atlas",
          is_mp=True,
      ),
      api.step_data(
          "calc next keyset version.list existing keysets",
          api.file.listdir(["AtlasMPKeys-v9", "AtlasMPKeys-v16"]),
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "target-calc-separate-streams-mp",
      api.properties(
          build_target="atlas",
          is_mp=True,
      ),
      api.step_data(
          "calc next keyset version.list existing keysets",
          api.file.listdir(["AtlasMPKeys-v5", "AtlasPreMPKeys-v12"]),
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "target-calc-separate-streams-premp",
      api.properties(
          build_target="atlas",
          is_mp=False,
      ),
      api.step_data(
          "calc next keyset version.list existing keysets",
          api.file.listdir(["AtlasMPKeys-v5", "AtlasPreMPKeys-v12"]),
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "missing-target-and-keyset-failure",
      api.post_check(
          post_process.SummaryMarkdownRE,
          r".*Either `keyset_name`.*or `build_target`.*must be specified.*",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )
