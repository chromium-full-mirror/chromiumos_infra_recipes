# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for quorum artifact and build helpers in keyset_utils recipe module."""

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

DEPS = [
    "recipe_engine/assertions",
    "recipe_engine/file",
    "recipe_engine/path",
    "recipe_engine/properties",
    "recipe_engine/step",
    "keyset_utils",
]


def RunSteps(api: recipe_api.RecipeApi):
  out_props = {}
  if "signing_docker_image" in api.properties:
    out_props["signing_docker_image"] = api.properties["signing_docker_image"]
  if "quorum_inbox_uri" in api.properties:
    out_props["quorum_inbox_uri"] = api.properties["quorum_inbox_uri"]

  quorum_build = build_pb2.Build(id=api.properties.get("quorum_build_id", 0))
  quorum_build.output.properties.update(out_props)
  api.step.empty("inspect quorum build")
  docker_image = api.keyset_utils.get_docker_image(quorum_build)
  if "expected_docker_image" in api.properties:
    api.assertions.assertEqual(docker_image,
                               api.properties["expected_docker_image"])

  inbox_artifacts, outbox_artifacts = api.keyset_utils.download_quorum_artifacts(
      work_dir=api.path.start_dir / "work",
      quorum_build=quorum_build,
      keyset_name="FooPreMPKeys",
      quorum_inbox_bucket=api.properties.get("quorum_inbox_bucket", ""),
  )
  api.assertions.assertEqual(inbox_artifacts,
                             ["artifact_a.bin", "artifact_b.json"])
  api.assertions.assertEqual(outbox_artifacts, ["custodian1/artifact_a.pao"])


def GenTests(api: recipe_test_api.RecipeTestApi):
  yield api.test(
      "basic",
      api.properties(
          quorum_build_id=87654321,
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
      "fallback-docker-image-and-uri-bucket",
      api.properties(
          quorum_build_id=87654321,
          quorum_inbox_uri=(
              "gs://uri-quorum-bucket/quorum_inbox/FooPreMPKeys/87654321"),
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
          "gs://uri-quorum-bucket/quorum_outbox/FooPreMPKeys/87654321/",
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      "missing-bucket-failure",
      api.properties(quorum_build_id=87654321),
      api.post_check(
          post_process.SummaryMarkdownRE,
          r".*Quorum artifact download failed: quorum bucket is required\..*",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      "missing-build-id-failure",
      api.properties(quorum_inbox_bucket="test-quorum-bucket"),
      api.post_check(
          post_process.SummaryMarkdownRE,
          r".*Quorum artifact download failed: `quorum_build_id` is required\..*",
      ),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )
