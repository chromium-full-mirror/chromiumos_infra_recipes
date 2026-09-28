# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for Qualbot.

This recipe directly invokes the auto_qual_main script to bypass bbagent API restrictions
and enable streaming child steps using the legacy annotator Wrapper.
"""

import json

from google.protobuf import json_format
from PB.chromite.api.qualbot import RunQualbotResponse
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.qualbot import QualbotProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    "recipe_engine/buildbucket",
    "recipe_engine/cipd",
    "recipe_engine/context",
    "recipe_engine/file",
    "recipe_engine/path",
    "recipe_engine/properties",
    "recipe_engine/runtime",
    "recipe_engine/step",
    "recipe_engine/time",
    "src_state",
    "build_menu",
    "cros_build_api",
    "easy",
]

PROPERTIES = QualbotProperties


def RunSteps(api: RecipeApi, properties: QualbotProperties):
  protoc_path = api.path.dirname(
      api.cipd.ensure_tool(
          "infra/3pp/tools/protoc/${platform}",
          "version:3@32.1",
          executable_path="bin/protoc",
      ))
  with api.context(env_prefixes={"PATH": [protoc_path]}):
    with api.build_menu.configure_builder(
        missing_ok=True), api.build_menu.setup_workspace():
      run_qualbot(api, properties)


def run_qualbot(api: RecipeApi, properties: QualbotProperties):
  """Run the auto qual script locally."""
  with api.step.nest("Run Qualbot") as presentation:
    run_annotations_luciexe = api.cipd.ensure_tool(
        "infra/tools/run_annotations/${platform}", "latest")

    json_output_path = api.path.mkdtemp(
        prefix="qualbot_output").joinpath("qualbot.json")
    script_path = api.src_state.workspace_path.joinpath("infra",
                                                        "fw_qual_automation",
                                                        "auto_qual_main.py")

    cmd = [
        run_annotations_luciexe,
        "--",
        "vpython3",
        script_path,
        "--log-level",
        "INFO",
        "--json-out",
        json_output_path,
        properties.request.task,
        "--add-message",
        f"Cr-Build-Id: {api.buildbucket.build.id}\n"
        f"Cr-Build-Url: https://cr-buildbucket.appspot.com/build/{api.buildbucket.build.id}",
        "--bot",
    ]

    is_staging = False
    if api.buildbucket.build.builder.bucket == "staging":
      is_staging = True
    if properties.request.is_staging:
      is_staging = True

    if is_staging:
      if properties.request.task == "analyze-test-efforts":
        cmd.append("--test-tables")
      elif properties.request.task == "auto-schedule":
        cmd.append("--dry-run")
      elif properties.request.task == "pipeline":
        cmd.append("--dry-run")
    else:
      cmd.append("--upload")

    retcode = 0
    try:
      api.step.sub_build(
          "call auto_qual_main",
          cmd,
          build_pb2.Build(),
      )
    except api.step.StepFailure as e:
      retcode = e.retcode if e.retcode is not None else -1

    try:
      # Attempt to read the QualBot JSON response that was stored at the end of the script
      qualbot_response = api.file.read_json(
          "read qualbot output",
          json_output_path,
          test_data={
              "launched_tests": [{
                  "test_effort_id": "9999",
                  "test_url": "fake"
              }]
          },
      )
    except api.step.StepFailure:
      qualbot_response = {}

    # We hydrate the dict back to a response object for presentation property if needed
    try:
      response_obj = json_format.Parse(
          json.dumps(qualbot_response),
          RunQualbotResponse(),
          ignore_unknown_fields=True,
      )
      presentation.properties["qualbot_response"] = response_obj
    except json_format.ParseError:
      pass

    for launched_test in qualbot_response.get("launched_tests", []):
      link_name = ""
      if launched_test.get("test_effort_id"):
        link_name += f"{launched_test.get('test_effort_id')}:"
      if launched_test.get("test_effort_name"):
        link_name += launched_test.get("test_effort_name")
      if link_name and launched_test.get("test_url"):
        presentation.links[link_name] = launched_test.get("test_url")

    if retcode != 0:
      raise api.step.StepFailure(f"Run Qualbot Failed (return code {retcode})")


def GenTests(api: RecipeTestApi):

  def mock_sub_build(status=common_pb2.SUCCESS):
    b = build_pb2.Build()
    b.status = status
    return api.step.sub_build(b)

  yield api.build_menu.test(
      "success",
      api.step_data(
          "Run Qualbot.call auto_qual_main",
          mock_sub_build(),
      ),
      api.post_check(
          post_process.StepSuccess,
          "Run Qualbot.call auto_qual_main",
      ),
  )

  def check_link(check, steps, link_name, expected_link):
    check(steps["Run Qualbot"].links[link_name] == expected_link)

  yield api.build_menu.test(
      "success-with-response",
      api.step_data(
          "Run Qualbot.call auto_qual_main",
          mock_sub_build(),
      ),
      api.step_data(
          "Run Qualbot.read qualbot output",
          api.file.read_json({
              "launched_tests": [{
                  "test_effort_id":
                      "4388",
                  "test_effort_name":
                      "fatcat-ruby-AP-16650.58.0-EC-16667.2.46-RO/RW",
                  "test_url":
                      "https://android-build.corp.google.com/abtd/run/L81200030126644839",
                  "location":
                      "LOCATION_INTERNAL",
              }]
          }),
      ),
      api.post_check(
          check_link,
          "4388:fatcat-ruby-AP-16650.58.0-EC-16667.2.46-RO/RW",
          "https://android-build.corp.google.com/abtd/run/L81200030126644839",
      ),
      api.post_check(
          post_process.StepSuccess,
          "Run Qualbot.call auto_qual_main",
      ),
  )

  yield api.build_menu.test(
      "service-endpoint-failure-response-available",
      api.step_data(
          "Run Qualbot.call auto_qual_main",
          mock_sub_build(common_pb2.FAILURE),
          retcode=2,
      ),
      api.step_data(
          "Run Qualbot.read qualbot output",
          api.file.read_json({
              "failure_reason": "FAILURE_SCHEDULE_PUSH_ERROR",
          }),
      ),
      api.post_check(
          post_process.StepFailure,
          "Run Qualbot",
      ),
      status="FAILURE",
  )

  yield api.build_menu.test(
      "service-endpoint-failure-no-response",
      api.step_data(
          "Run Qualbot.call auto_qual_main",
          mock_sub_build(common_pb2.FAILURE),
          retcode=1,
      ),
      api.step_data("Run Qualbot.read qualbot output", retcode=1),
      api.post_check(
          post_process.StepFailure,
          "Run Qualbot",
      ),
      status="FAILURE",
  )

  yield api.build_menu.test(
      "staging-builder",
      api.buildbucket.generic_build(builder="staging-qualbot-pipeline",
                                    bucket="staging"),
      api.step_data(
          "Run Qualbot.call auto_qual_main",
          mock_sub_build(),
      ),
      api.post_check(
          post_process.MustRun,
          "Run Qualbot.call auto_qual_main",
      ),
  )

  yield api.build_menu.test(
      "staging-analyze-test-efforts",
      api.properties(
          QualbotProperties(request={
              "task": "analyze-test-efforts",
              "is_staging": True
          })),
      api.step_data(
          "Run Qualbot.call auto_qual_main",
          mock_sub_build(),
      ),
      api.post_check(
          post_process.MustRun,
          "Run Qualbot.call auto_qual_main",
      ),
  )

  yield api.build_menu.test(
      "staging-auto-schedule",
      api.properties(
          QualbotProperties(request={
              "task": "auto-schedule",
              "is_staging": True
          })),
      api.step_data(
          "Run Qualbot.call auto_qual_main",
          mock_sub_build(),
      ),
      api.post_check(
          post_process.MustRun,
          "Run Qualbot.call auto_qual_main",
      ),
  )

  yield api.build_menu.test(
      "staging-pipeline",
      api.properties(
          QualbotProperties(request={
              "task": "pipeline",
              "is_staging": True
          })),
      api.step_data(
          "Run Qualbot.call auto_qual_main",
          mock_sub_build(),
      ),
      api.post_check(
          post_process.MustRun,
          "Run Qualbot.call auto_qual_main",
      ),
  )

  yield api.build_menu.test(
      "parse-error",
      api.step_data(
          "Run Qualbot.call auto_qual_main",
          mock_sub_build(),
      ),
      api.step_data(
          "Run Qualbot.read qualbot output",
          api.file.read_json({
              "failure_reason": {
                  "foo": "bar"
              },
          }),
      ),
      api.post_check(
          post_process.MustRun,
          "Run Qualbot.call auto_qual_main",
      ),
  )
