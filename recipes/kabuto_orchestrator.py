# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Kabuto payloads and launching Kabuto shadercache jobs."""

import json
from recipe_engine import post_process
from recipe_engine.recipe_api import InfraFailure, StepFailure
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

from PB.recipes.chromeos.kabuto_orchestrator import (
    KabutoOrchestratorProperties)
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.build import Build

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'failures',
    'git',
]


PROPERTIES = KabutoOrchestratorProperties
INFRA_BUCKET = 'infra'
STAGING_BUCKET = 'staging'


def _launch_builders(api: RecipeApi, bucket: str, builder: str,
                     is_staging: bool, count=1, input_properties=None,
                     step_name='', timeout_hours=3) -> list:
  """
  Launch builders using api.bitbucket.run and return the list of builds.

  Args:
    api: Recipe API.
    bucket: the bucket the builder resides in on LUCI.
    builder: the name of the builder to launch.
    is_staging: whether to run the staging version -- prepends 'staging-'
                to the supplied builder name.
    count: the number of these builders to launch (for sharding.)
    input_properties: the input properties JSON to supply to the builder.
    step_name: customize the name of the step. Defaults to the builder name.
    timeout_hours: timeout (in hours) to wait on the launched builders
                   to complete.

  Returns:
    A list of builds (results of api.buildbucket.run).
  """

  # Use the builder name if the step name isn't defined.
  step_name = step_name if step_name else builder

  # Default to an empty dict if no input properties were specified.
  # This avoids a crash when accessing the dict below (since it's bad practice
  # to have argument={} in a function definition.)
  input_properties = input_properties if input_properties else {}

  with api.step.nest(step_name):
    builder = f'staging-{builder}' if is_staging else builder
    requests = []
    for i in range(0, count):
      input_properties['shard'] = f'{i}'
      requests.append(
          api.buildbucket.schedule_request(bucket=bucket, builder=builder,
                                           properties=input_properties))

    # Yield execution on the child build and return the properties when
    # the job is complete..
    builds = api.buildbucket.run(requests, timeout=60 * 60 * timeout_hours)

    # Check for FAILURE or INFRA_FAILURE on the completed child builder.
    # Sets the appropriate status on the current step in the orchestrator
    # so it propogates up and stops it from continuing past.
    for build in builds:
      if build.status != common_pb2.SUCCESS:
        build_url = f'https://cr-buildbucket.appspot.com/build/{build.id}'
        failure = None
        with api.step.nest('inspect failure') as presentation:
          presentation.step_text = build.summary_markdown
          presentation.links[build_url] = build_url
          if build.status == common_pb2.INFRA_FAILURE:
            presentation.status = api.step.INFRA_FAILURE
            failure = InfraFailure
          else:
            presentation.status = api.step.FAILURE
            failure = StepFailure
        raise failure(f'{builder} failed\n{build_url}')

  return builds


def RunSteps(api: RecipeApi, properties: KabutoOrchestratorProperties) -> None:
  if properties.use_release_build_artifacts and not properties.manifest_branch:
    raise StepFailure(
        'must set manifest_branch if use_release_build_artifacts is true')
  if properties.manifest_branch and not properties.milestone or properties.milestone and not properties.manifest_branch:
    raise StepFailure('manifest_branch and milestone must both be specified.')
  gerrit_cl_ref = properties.gerrit_cl_ref
  # Default to 1 shard if number is not provided.
  shard_count = 1 if not properties.shard_count else properties.shard_count
  # Default to no config override
  kabuto_config_override = None if not properties.kabuto_config_override else properties.kabuto_config_override
  # Get individual build timeouts from properties or use reasonable default
  # An extra hour is added to each default to ensure the orchestrator waits
  # long enough for the child to launch and complete successfully.
  shadercache_timeout = 9 if not properties.shadercache_timeout else properties.shadercache_timeout
  paygen_timeout = 7 if not properties.paygen_timeout else properties.paygen_timeout
  uprev_timeout = 13 if not properties.uprev_timeout else properties.uprev_timeout

  bucket = STAGING_BUCKET if api.build_menu.is_staging else INFRA_BUCKET

  manifest_branch = None if not properties.manifest_branch else properties.manifest_branch
  milestone = None if not properties.milestone else properties.milestone

  ### Build and upload a Kabuto payload.
  # If the payload_gs_url was supplied as an input property skip the build
  # and use the supplied payload.
  if properties.payload_gs_url:
    paygen_output_props = {'payload_gs_url': properties.payload_gs_url}
  else:
    paygen_input_props = {
        'destination_gs_bucket': 'kabuto_cache',
        'destination_gs_path': 'test-recipe-payloads/',
        'use_release_build_artifacts': properties.use_release_build_artifacts
    }
    if manifest_branch:
      paygen_input_props['manifest_branch'] = manifest_branch
      paygen_input_props['milestone'] = milestone
    if gerrit_cl_ref and api.build_menu.is_staging:
      paygen_input_props['gerrit_cl_ref'] = gerrit_cl_ref
    if kabuto_config_override:
      paygen_input_props['kabuto_config_override'] = kabuto_config_override
    if properties.borealis_remote_url:
      paygen_input_props['borealis_remote_url'] = properties.borealis_remote_url
    if properties.kabuto_path:
      paygen_input_props['kabuto_path'] = properties.kabuto_path
    # Launch the Kabuto paygen builder.
    paygen_build = _launch_builders(api, bucket, 'kabuto_paygen',
                                    api.build_menu.is_staging, 1,
                                    paygen_input_props, 'paygen build',
                                    timeout_hours=paygen_timeout)
    paygen_build = paygen_build[0]
    paygen_output_props = paygen_build.output.properties

  # Create the shadercache input properties from the paygen's payload_gs_url.
  shadercache_input_props = {}
  if 'payload_gs_url' in paygen_output_props:
    payload_gs_url = paygen_output_props['payload_gs_url']
    # Extra the bucket from the GS URL.
    payload_bucket = payload_gs_url.lstrip('gs://').split('/')[0]
    # Extra the path from the GS URL.
    payload_path = str.join('/', payload_gs_url.lstrip('gs://').split('/')[1:])
    shadercache_input_props = {
        'payload_gs_bucket': payload_bucket,
        'payload_gs_path': payload_path
    }
  if manifest_branch:
    shadercache_input_props['manifest_branch'] = manifest_branch
    shadercache_input_props['milestone'] = milestone
  if gerrit_cl_ref and api.build_menu.is_staging:
    shadercache_input_props['gerrit_cl_ref'] = gerrit_cl_ref
  if kabuto_config_override:
    shadercache_input_props['kabuto_config_override'] = kabuto_config_override
  if properties.borealis_remote_url:
    shadercache_input_props[
        'borealis_remote_url'] = properties.borealis_remote_url

  ### Build Kabuto shadercaches on sandboxed builders
  shadercache_builds = _launch_builders(api, bucket, 'build_kabuto_shadercache',
                                        api.build_menu.is_staging, shard_count,
                                        shadercache_input_props,
                                        'shadercache build',
                                        timeout_hours=shadercache_timeout)

  # Combine the multiple outputs from the builders into a single list.
  all_uprev_info = []
  for shadercache_build in shadercache_builds:
    if 'uprev_info' in shadercache_build.output.properties:
      # The output property is a dict represented as a string, but for it to be
      # proper JSON when passed as an input_property we need to use json.loads
      # so that it remains properly JSON formatted.
      uprev_info = json.loads(shadercache_build.output.properties['uprev_info'])
      all_uprev_info.append(uprev_info)
  # Prepare the cumulative uprev information.
  # Use json.dumps to convert back to a JSON-compatible formatted string.
  uprev_input_props = {'uprev_info': json.dumps(all_uprev_info)}
  if manifest_branch:
    uprev_input_props['manifest_branch'] = manifest_branch
    uprev_input_props['milestone'] = milestone
  if gerrit_cl_ref and api.build_menu.is_staging:
    uprev_input_props['gerrit_cl_ref'] = gerrit_cl_ref
  if kabuto_config_override:
    uprev_input_props['kabuto_config_override'] = kabuto_config_override
  if properties.borealis_remote_url:
    uprev_input_props['borealis_remote_url'] = properties.borealis_remote_url
  if properties.kabuto_path:
    uprev_input_props['kabuto_path'] = properties.kabuto_path

  ### Uprev the ebuilds with new shadercaches.
  _launch_builders(api, bucket, 'kabuto_shadercache_uprev',
                   api.build_menu.is_staging, 1, uprev_input_props,
                   'uprev build', timeout_hours=uprev_timeout)


def GenTests(api: RecipeTestApi) -> None:

  def paygen_child_data() -> Build:
    paygen_child_data = build_pb2.Build(id=8922054662172514000,
                                        status='SUCCESS')
    paygen_child_data.output.properties[
        'payload_gs_url'] = 'gs://kabuto_cache/kabuto_payload.tar.xz'
    return paygen_child_data

  def shadercache_child_data() -> Build:
    shadercache_child_data = build_pb2.Build(id=8922054662172514001,
                                             status='SUCCESS')
    shadercache_child_data.output.properties[
        'uprev_info'] = '{\"a\": 1, \"b\": 2}'
    return shadercache_child_data

  def child_builder_failure() -> Build:
    failed_child_data = build_pb2.Build(id=8922054662172514000,
                                        status='FAILURE')
    return failed_child_data

  def child_builder_infra_failure() -> Build:
    failed_child_data = build_pb2.Build(id=8922054662172514000,
                                        status='INFRA_FAILURE')
    return failed_child_data

  good_props = {}
  yield api.test(
      'basic',
      api.properties(**good_props),
  )

  props = good_props.copy()
  props[
      'kabuto_config_override'] = '{"build_shader_cache": {"soft_timeout_seconds": 3}}'
  yield api.test(
      'kabuto-config-override',
      api.properties(**props),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['kabuto_path'] = 'src/platform/borealis-private/tools/kabuto'
  props[
      'borealis_remote_url'] = 'https://chrome-internal.googlesource.com/chromeos/platform/borealis-private'
  yield api.test(
      'kabuto-passthru-props',
      api.properties(**props),
      api.post_check(
          post_process.LogContains, 'paygen build.buildbucket.run.schedule',
          'request', [
              '"kabuto_path": "src/platform/borealis-private/tools/kabuto"',
              '"borealis_remote_url": "https://chrome-internal.googlesource.com/chromeos/platform/borealis-private"'
          ]),
      api.post_check(
          post_process.LogContains,
          'shadercache build.buildbucket.run.schedule', 'request', [
              '"borealis_remote_url": "https://chrome-internal.googlesource.com/chromeos/platform/borealis-private"'
          ]),
      api.post_check(
          post_process.LogContains, 'uprev build.buildbucket.run.schedule',
          'request', [
              '"kabuto_path": "src/platform/borealis-private/tools/kabuto"',
              '"borealis_remote_url": "https://chrome-internal.googlesource.com/chromeos/platform/borealis-private"'
          ]),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['manifest_branch'] = 'release-R105-14989.B'
  props['milestone'] = 105
  yield api.test(
      'manifest-branch',
      api.properties(**props),
  )

  props = good_props.copy()
  props['manifest_branch'] = 'release-R105-14989.B'
  yield api.test(
      'manifest-no-milestone',
      api.properties(**props),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  props = good_props.copy()
  props['milestone'] = 105
  yield api.test(
      'milestone-no-manifest',
      api.properties(**props),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  props = good_props.copy()
  props['gerrit_cl_ref'] = 'refs/changes/12/345678'
  yield api.test(
      'gerrit-cl-ref',
      api.properties(**props),
      api.buildbucket.generic_build(bucket='staging'),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['manifest_branch'] = 'release-R105-14989.B'
  props['milestone'] = 105
  props['use_release_build_artifacts'] = True
  yield api.test(
      'use-release-build-artifacts', api.properties(**props),
      api.post_check(post_process.LogContains,
                     'paygen build.buildbucket.run.schedule', 'request', [
                         '"manifest_branch": "release-R105-14989.B"',
                         '"use_release_build_artifacts": true'
                     ]))

  props = good_props.copy()
  props['use_release_build_artifacts'] = True
  yield api.test('release-build-but-no-manifest-branch',
                 api.properties(**props),
                 api.post_process(post_process.DropExpectation),
                 status='FAILURE')

  props = good_props.copy()
  props[
      'payload_gs_url'] = 'gs://kabuto_cache/recipe-payloads/kabuto_payload.tar.xz'
  yield api.test(
      'skip-paygen-step',
      api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'paygen build'),
  )

  yield api.test(
      'paygen-mock',
      api.buildbucket.simulated_collect_output(
          [paygen_child_data()], 'paygen build.buildbucket.run.collect'))

  yield api.test(
      'shadercache-mock',
      api.buildbucket.simulated_collect_output(
          [shadercache_child_data()],
          'shadercache build.buildbucket.run.collect'))

  props = good_props.copy()
  props['shard_count'] = '2'
  yield api.test(
      'shard_count',
      api.properties(**props),
  )

  yield api.test(
      'child-builder-failure',
      api.buildbucket.simulated_collect_output(
          [child_builder_failure()], 'paygen build.buildbucket.run.collect'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'child-builder-infra-failure',
      api.buildbucket.simulated_collect_output(
          [child_builder_infra_failure()],
          'paygen build.buildbucket.run.collect'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )
