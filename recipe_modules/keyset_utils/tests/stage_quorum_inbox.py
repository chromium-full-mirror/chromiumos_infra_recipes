# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for stage_quorum_inbox in keyset_utils recipe module."""

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
  work_dir = api.path.start_dir / "work"
  inbox_dir = api.path.start_dir / "inbox"
  artifacts_to_stage = list(
      api.properties.get("artifacts_to_stage",
                         api.properties.get("files_to_stage", [])))
  api.keyset_utils.stage_quorum_inbox(work_dir, inbox_dir, artifacts_to_stage)


def GenTests(api: recipe_test_api.RecipeTestApi):
  yield api.test(
      "basic",
      api.properties(artifacts_to_stage=["artifact_a.json", "artifact_b.bin"]),
      api.step_data(
          "stage quorum inbox.discover quorum inbox artifacts",
          api.file.listdir([
              "artifact_a.json",
              "artifact_b.bin",
              "unrelated_file.txt",
          ]),
      ),
      api.post_check(
          post_process.MustRun,
          "stage quorum inbox.stage artifact_a.json",
      ),
      api.post_check(
          post_process.MustRun,
          "stage quorum inbox.stage artifact_b.bin",
      ),
      api.post_check(
          post_process.DoesNotRun,
          "stage quorum inbox.stage unrelated_file.txt",
      ),
      api.post_check(
          post_process.LogContains,
          "stage quorum inbox",
          "staged_artifacts",
          ["artifact_a.json", "artifact_b.bin"],
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "missing-artifact",
      api.properties(
          artifacts_to_stage=["artifact_a.json", "missing_artifact.bin"]),
      api.step_data(
          "stage quorum inbox.discover quorum inbox artifacts",
          api.file.listdir([
              "artifact_a.json",
              "other_file.bin",
          ]),
      ),
      api.post_check(post_process.StepTextContains, 'stage quorum inbox',
                     ['staged 1 artifact(s)']),
      api.post_check(post_process.StepTextContains, 'stage quorum inbox',
                     ['missing 1 artifact(s)']),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "all-missing-artifacts",
      api.properties(artifacts_to_stage=["nonexistent.bin"]),
      api.step_data(
          "stage quorum inbox.discover quorum inbox artifacts",
          api.file.listdir(["other_file.bin"]),
      ),
      api.post_check(
          post_process.SummaryMarkdownRE,
          r".*Quorum inbox staging failed: none of the specified artifacts were found\..*",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "empty-artifacts-to-stage",
      api.properties(artifacts_to_stage=[]),
      api.post_check(
          post_process.SummaryMarkdownRE,
          r".*Quorum inbox staging failed: no artifacts specified to stage\..*",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )
