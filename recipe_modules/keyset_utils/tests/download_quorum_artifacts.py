# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for quorum artifact and build helpers in keyset_utils recipe module."""

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (
    builder_common as builder_common_pb2,)
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

DEPS = [
    "recipe_engine/assertions",
    "recipe_engine/buildbucket",
    "recipe_engine/file",
    "recipe_engine/path",
    "recipe_engine/properties",
    "recipe_engine/step",
    "keyset_utils",
]


def RunSteps(api: recipe_api.RecipeApi):
  in_props = {}
  if "quorum_build_inbox_bucket" in api.properties:
    in_props["quorum_inbox_bucket"] = (
        api.properties["quorum_build_inbox_bucket"])
  out_props = {}
  if "signing_docker_image" in api.properties:
    out_props["signing_docker_image"] = api.properties["signing_docker_image"]

  quorum_build = build_pb2.Build(
      id=api.properties.get("quorum_build_id", 0),
      status=common_pb2.Status.Value(
          api.properties.get("quorum_build_status", "SUCCESS")),
      builder=builder_common_pb2.BuilderID(
          project="chromeos",
          bucket=api.properties.get("quorum_build_bucket", ""),
          builder="hsm-manager",
      ),
  )
  quorum_build.input.properties.update(in_props)
  quorum_build.output.properties.update(out_props)
  api.step.empty("inspect quorum build")
  is_staging = api.properties.get("is_staging", False)
  quorum_inbox_bucket = api.properties.get("quorum_inbox_bucket", "")

  docker_image = api.keyset_utils.get_docker_image(quorum_build)
  if "expected_docker_image" in api.properties:
    api.assertions.assertEqual(docker_image,
                               api.properties["expected_docker_image"])

  api.keyset_utils.validate_quorum_build(
      quorum_build,
      is_staging=is_staging,
      quorum_inbox_bucket=quorum_inbox_bucket,
  )

  inbox_artifacts, outbox_artifacts = api.keyset_utils.download_quorum_artifacts(
      work_dir=api.path.start_dir / "work",
      quorum_build=quorum_build,
      keyset_name="FooPreMPKeys",
  )
  api.assertions.assertEqual(inbox_artifacts,
                             ["artifact_a.bin", "artifact_b.json"])
  api.assertions.assertEqual(outbox_artifacts, ["custodian1/artifact_a.pao"])


def GenTests(api: recipe_test_api.RecipeTestApi):
  prod_build = api.buildbucket.build(
      build_pb2.Build(
          builder=builder_common_pb2.BuilderID(
              project="chromeos",
              bucket="prod",
              builder="hsm-manager",
          )))
  staging_build = api.buildbucket.build(
      build_pb2.Build(
          builder=builder_common_pb2.BuilderID(
              project="chromeos",
              bucket="staging",
              builder="staging-hsm-manager",
          )))

  yield api.test(
      "basic",
      prod_build,
      api.properties(
          quorum_build_id=87654321,
          quorum_build_bucket="prod",
          quorum_build_inbox_bucket="test-quorum-bucket",
          signing_docker_image="signing:quorum-123",
          expected_docker_image="signing:quorum-123",
          quorum_inbox_bucket="test-quorum-bucket",
      ),
      api.step_data(
          "download quorum artifacts.list quorum inbox artifacts",
          api.file.listdir(["artifact_b.json", "artifact_a.bin"]),
      ),
      api.step_data(
          "download quorum artifacts.list quorum outbox artifacts",
          api.file.listdir(["custodian1/artifact_a.pao"]),
      ),
      api.post_check(
          post_process.StepTextEquals,
          "validate quorum build",
          "validated bucket `prod`",
      ),
      api.post_check(
          post_process.MustRun,
          "download quorum artifacts.gsutil download quorum inbox",
      ),
      api.post_check(
          post_process.MustRun,
          "download quorum artifacts.gsutil download quorum outbox",
      ),
      api.post_check(
          post_process.LogEquals,
          "download quorum artifacts",
          "inbox_uri",
          "gs://test-quorum-bucket/quorum_inbox/FooPreMPKeys/87654321/",
      ),
      api.post_check(
          post_process.LogEquals,
          "download quorum artifacts",
          "outbox_uri",
          "gs://test-quorum-bucket/quorum_outbox/FooPreMPKeys/87654321/",
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "fallback-docker-image-and-inbox-bucket",
      staging_build,
      api.properties(
          is_staging=True,
          quorum_build_id=87654321,
          quorum_build_bucket="staging",
          quorum_build_inbox_bucket="inbox-quorum-bucket",
          expected_docker_image=(
              "us-docker.pkg.dev/chromeos-release-bot/signing/signing:latest:"),
      ),
      api.step_data(
          "download quorum artifacts.list quorum inbox artifacts",
          api.file.listdir(["artifact_b.json", "artifact_a.bin"]),
      ),
      api.step_data(
          "download quorum artifacts.list quorum outbox artifacts",
          api.file.listdir(["custodian1/artifact_a.pao"]),
      ),
      api.post_check(post_process.StepWarning, "inspect quorum build"),
      api.post_check(
          post_process.LogEquals,
          "download quorum artifacts",
          "outbox_uri",
          "gs://inbox-quorum-bucket/quorum_outbox/FooPreMPKeys/87654321/",
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "staging-cross-bucket-warning",
      staging_build,
      api.properties(
          is_staging=True,
          quorum_build_id=87654321,
          quorum_build_bucket="prod",
          quorum_build_inbox_bucket="prod-quorum-bucket",
          quorum_inbox_bucket="staging-quorum-bucket",
          signing_docker_image="signing:quorum-123",
      ),
      api.step_data(
          "download quorum artifacts.list quorum inbox artifacts",
          api.file.listdir(["artifact_b.json", "artifact_a.bin"]),
      ),
      api.step_data(
          "download quorum artifacts.list quorum outbox artifacts",
          api.file.listdir(["custodian1/artifact_a.pao"]),
      ),
      api.post_check(post_process.StepWarning, "validate quorum build"),
      api.post_check(
          post_process.LogContains,
          "validate quorum build",
          "warning",
          [
              "is from bucket `prod`, expected `staging`",
              "Quorum bucket `staging-quorum-bucket` does not match "
              "pre-quorum build bucket `prod-quorum-bucket`",
          ],
      ),
      api.post_check(
          post_process.LogEquals,
          "download quorum artifacts",
          "inbox_uri",
          "gs://prod-quorum-bucket/quorum_inbox/FooPreMPKeys/87654321/",
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "prod-status-not-success-failure",
      prod_build,
      api.properties(
          quorum_build_id=87654321,
          quorum_build_status="FAILURE",
          quorum_build_bucket="prod",
      ),
      api.post_check(
          post_process.SummaryMarkdownRE,
          r".*Pre-quorum build 87654321 has status FAILURE; expected SUCCESS\..*",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "prod-bucket-mismatch-failure",
      prod_build,
      api.properties(
          quorum_build_id=87654321,
          quorum_build_bucket="staging",
          quorum_build_inbox_bucket="test-quorum-bucket",
      ),
      api.post_check(
          post_process.SummaryMarkdownRE,
          r".*Pre-quorum build 87654321 is from bucket `staging`, expected `prod`\..*",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "prod-bucket-override-failure",
      prod_build,
      api.properties(
          quorum_build_id=87654321,
          quorum_build_bucket="prod",
          quorum_build_inbox_bucket="inbox-bucket",
          quorum_inbox_bucket="arbitrary-bucket",
      ),
      api.post_check(
          post_process.SummaryMarkdownRE,
          r".*Quorum bucket `arbitrary-bucket` does not match pre-quorum build bucket `inbox-bucket`\..*",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "missing-bucket-failure",
      staging_build,
      api.properties(
          is_staging=True,
          quorum_build_id=87654321,
          quorum_build_bucket="staging",
      ),
      api.post_check(
          post_process.SummaryMarkdownRE,
          r".*Pre-quorum build 87654321 is missing `quorum_inbox_bucket` input property\..*",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "missing-build-id-failure",
      api.properties(quorum_inbox_bucket="test-quorum-bucket"),
      api.post_check(
          post_process.SummaryMarkdownRE,
          r".*Quorum build validation failed: `quorum_build_id` is required\..*",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )
