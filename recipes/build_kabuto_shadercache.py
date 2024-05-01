# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building Borealis shadercache using Kabuto."""

from PB.recipes.chromeos.build_kabuto_shadercache import (
    BuildKabutoShadercacheProperties)
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'depot_tools/gsutil',
    'build_menu',
    'easy',
    'failures',
    'git',
]

PROPERTIES = BuildKabutoShadercacheProperties

_MILESTONE_USES_INPUT_MANIFEST_BRANCH = 122


GS_BUCKET = 'kabuto_cache'
LOCAL_PAYLOAD_FILENAME = 'kabuto_payload.tar.gz'


def _upload_kabuto_logs(api: RecipeTestApi) -> None:
  """Tars and uploads the contents of borealis/kabuto/logs/."""
  time_now_utc = api.time.utcnow().strftime('%Y-%m-%d-%H%M%S')
  kabuto_log_tarball = f'kabuto_logs_{time_now_utc}.tar'
  kabuto_log_path = 'tools/kabuto/logs/'

  api.step('bundle kabuto logs',
           ['tar', 'cvf', kabuto_log_tarball, kabuto_log_path])

  # Hardcoded for now to facilitate dev, this will be changed later.
  upload_path = f'test-recipe-payloads/logs/{kabuto_log_tarball}'
  api.gsutil.upload(kabuto_log_tarball, GS_BUCKET, upload_path)


def _fetch_kabuto_payload(api: RecipeTestApi, payload_gs_bucket: str,
                          payload_gs_path: str) -> None:
  """Download the property-provided Kabuto payload (Mesa headers) from GS."""
  api.gsutil.download(payload_gs_bucket, payload_gs_path,
                      LOCAL_PAYLOAD_FILENAME)


def RunSteps(api: RecipeApi,
             properties: BuildKabutoShadercacheProperties) -> None:
  # Validate that the inputs we minimally require were passed.
  with api.step.nest('validate properties') as presentation:
    if not properties.payload_gs_bucket:
      raise StepFailure('must set payload_gs_bucket')
    if not properties.payload_gs_path:
      raise StepFailure('must set payload_gs_path')
    if not properties.borealis_remote_url:
      properties.borealis_remote_url = 'https://chrome-internal.googlesource.com/chromeos/platform/borealis-private'

    presentation.step_text = 'all properties good'

  return DoRunSteps(api, properties)


def DoRunSteps(api: RecipeTestApi,
               properties: BuildKabutoShadercacheProperties) -> None:
  # This recipe should only run on bots with docker pre-installed.  Abort
  # immediately if that is not the case.
  # TODO(pobega): add a test case for when Docker is missing (here and in
  # Borealis rootfs.)
  api.step('check docker install', ['docker', 'help'])

  borealis_checkout = api.path.mkdtemp('borealis')
  with api.context(cwd=borealis_checkout):
    with api.step.nest('clone kabuto'):
      # Clone Borealis, Kabuto is in borealis/tools/kabuto.
      api.git.clone(properties.borealis_remote_url)
      # Check out a manifest branch. Manifest branch has priority
      # over other Kabuto checkouts if multiple are provided.
      if properties.manifest_branch:
        api.git.checkout(properties.manifest_branch, force=True)
      # Check out a specific Kabuto commit ref from the tree
      elif properties.kabuto_commit_ref and api.build_menu.is_staging:
        api.git.checkout(properties.kabuto_commit_ref, force=True)
      # Check out a specific Kabuto CL ref from Gerrit (staging only)
      elif properties.gerrit_cl_ref and api.build_menu.is_staging:
        with api.step.nest('Checkout Gerrit CL'):
          api.git.fetch(properties.borealis_remote_url)
          api.git.fetch_ref(properties.borealis_remote_url,
                            properties.gerrit_cl_ref)
          api.git.checkout('FETCH_HEAD', force=True)

    # Download Mesa headers for Kabuto to ingest.
    with api.step.nest('fetch kabuto payload'):
      _fetch_kabuto_payload(api, properties.payload_gs_bucket,
                            properties.payload_gs_path)

      # Untar Mesa headers into our Kabuto checkout
      api.step('untar kabuto payload',
               ['tar', 'xvf', LOCAL_PAYLOAD_FILENAME, '-C', 'tools/kabuto/in/'])

    # Run Kabuto.
    # TODO(pobega): For now we want to skip failures so that we can upload logs,
    # this will be changed to using deferred for prod.
    with api.failures.ignore_exceptions():
      kabuto_cmd = ['./tools/kabuto/kabuto', '--gcs', '--no-interactive']
      # Override local Kabuto config if provided.
      if properties.kabuto_config_override:
        kabuto_cmd.append('--kabuto-config-override')
        kabuto_cmd.append(properties.kabuto_config_override)
      # Provide input-manifest-branch if relevant.
      if properties.manifest_branch and properties.milestone >= _MILESTONE_USES_INPUT_MANIFEST_BRANCH:
        kabuto_cmd.append(
            f'--input-manifest-branch={properties.manifest_branch}')
      if properties.shard:
        # If a shard number is specified we use that shard's config from
        # Kabuto's input directory.
        shard = int(properties.shard)
        shard_cmd_args = [
            f'--kabuto-config=tools/kabuto/in/prod/shard-{shard}/kabuto.json'
        ]
        # The shard config directory is different depending on if we are
        # doing a staging build or not (to avoid overwriting prod artifacts.)
        if api.build_menu.is_staging:
          shard_cmd_args = [
              f'--kabuto-config=tools/kabuto/in/staging/shard-staging-{shard}/kabuto.json'
          ]
        kabuto_cmd = kabuto_cmd + shard_cmd_args
      api.step('run kabuto', kabuto_cmd)

    # Upload Kabuto's logs to Google Storage.
    with api.step.nest('upload kabuto logs'):
      _upload_kabuto_logs(api)

    # Get info on newly compiled shadercaches for uprev.
    # If this step fails we can continue with an empty updated_artifacts,
    # this can (rarely) happen in sharding situations.
    updated_artifacts = '{}'
    with api.failures.ignore_exceptions():
      updated_artifacts = api.file.read_text(
          'Read updated_artifacts.json',
          api.path.join(borealis_checkout,
                        'tools/kabuto/out/updated_artifacts.json'))

    # Set our output properties for the orchestrator to read.
    api.easy.set_properties_step(uprev_info=updated_artifacts)


def GenTests(api: RecipeTestApi) -> None:
  good_props = {
      'payload_gs_bucket': 'kabuto_cache',
      'payload_gs_path': 'test-recipe-payloads/kabuto_volteer.tar.gz'
  }
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
      api.post_process(
          post_process.StepCommandContains,
          'run kabuto',
          [
              './tools/kabuto/kabuto',
              '--gcs',
              '--no-interactive',
              '--kabuto-config-override',
              '{"build_shader_cache": {"soft_timeout_seconds": 3}}',
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  del props['payload_gs_bucket']
  yield api.test(
      'missing-payload-GS-bucket',
      api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'fetch kabuto payload'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  props = good_props.copy()
  del props['payload_gs_path']
  yield api.test(
      'missing-payload-GS-path',
      api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'fetch kabuto payload'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  # We explicitly want to test shard-0 here since in testing, 0 == False
  # made the command not update properly.
  props = good_props.copy()
  props['shard'] = '0'
  yield api.test(
      'shard-specified',
      api.properties(**props),
      api.post_process(
          post_process.StepCommandContains,
          'run kabuto',
          [
              './tools/kabuto/kabuto', '--gcs', '--no-interactive',
              '--kabuto-config=tools/kabuto/in/prod/shard-0/kabuto.json'
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['shard'] = '0'
  yield api.test(
      'staging-shard',
      api.properties(**props),
      api.buildbucket.generic_build(bucket='staging'),
      api.post_process(
          post_process.StepCommandContains,
          'run kabuto',
          [
              './tools/kabuto/kabuto', '--gcs', '--no-interactive',
              '--kabuto-config=tools/kabuto/in/staging/shard-staging-0/kabuto.json'
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['manifest_branch'] = 'release-R114-15437.B'
  yield api.test(
      'manifest_branch',
      api.properties(**props),
      api.post_process(
          post_process.StepCommandContains,
          'clone kabuto.git checkout',
          [
              'git',
              'checkout',
              '--force',
              'release-R114-15437.B',
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['kabuto_commit_ref'] = '17e956ddabe4cba4c247dd39ebfd3e29eca5ff89'
  yield api.test(
      'kabuto_commit_ref',
      api.properties(**props),
      api.buildbucket.generic_build(bucket='staging'),
      api.post_process(
          post_process.StepCommandContains,
          'clone kabuto.git checkout',
          [
              'git',
              'checkout',
              '--force',
              '17e956ddabe4cba4c247dd39ebfd3e29eca5ff89',
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['gerrit_cl_ref'] = 'refs/changes/75/5888475/2'
  yield api.test(
      'gerrit_cl_ref',
      api.properties(**props),
      api.buildbucket.generic_build(bucket='staging'),
      api.post_check(post_process.MustRun,
                     'clone kabuto.Checkout Gerrit CL.git fetch'),
      api.post_process(
          post_process.StepCommandContains,
          'clone kabuto.Checkout Gerrit CL.git fetch (2)',
          [
              'git',
              'fetch',
              'https://chrome-internal.googlesource.com/chromeos/platform/borealis-private',
              'refs/changes/75/5888475/2:',
          ],
      ),
      api.post_check(post_process.MustRun,
                     'clone kabuto.Checkout Gerrit CL.git rev-parse'),
      api.post_process(
          post_process.StepCommandContains,
          'clone kabuto.Checkout Gerrit CL.git checkout',
          [
              'git',
              'checkout',
              '--force',
              'FETCH_HEAD',
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['gerrit_cl_ref'] = 'refs/changes/12/345678'
  yield api.test(
      'skip-cl-ref-prod',
      api.properties(**props),
      api.post_check(post_process.DoesNotRun,
                     'clone kabuto.Checkout Gerrit CL'),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['shard'] = '0'
  props['manifest_branch'] = 'release-R122-12345.B'
  props['milestone'] = 122
  yield api.test(
      'input-manifest-branch',
      api.properties(**props),
      api.post_process(
          post_process.StepCommandContains,
          'run kabuto',
          [
              './tools/kabuto/kabuto', '--gcs', '--no-interactive',
              '--input-manifest-branch=release-R122-12345.B',
              '--kabuto-config=tools/kabuto/in/prod/shard-0/kabuto.json'
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['shard'] = '0'
  props['manifest_branch'] = 'release-R121-12345.B'
  props['milestone'] = 121
  yield api.test(
      'no-input-manifest-branch-before-122',
      api.properties(**props),
      api.post_process(
          post_process.StepCommandContains,
          'run kabuto',
          [
              './tools/kabuto/kabuto', '--gcs', '--no-interactive',
              '--kabuto-config=tools/kabuto/in/prod/shard-0/kabuto.json'
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )
