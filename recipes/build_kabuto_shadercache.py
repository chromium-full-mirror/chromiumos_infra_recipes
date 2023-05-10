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
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'depot_tools/gsutil',
    'easy',
    'failures',
    'git',
]

PROPERTIES = BuildKabutoShadercacheProperties

PYTHON_VERSION_COMPATIBILITY = 'PY3'

GS_BUCKET = 'kabuto_cache'
LOCAL_PAYLOAD_FILENAME = 'kabuto_payload.tar.gz'


def _upload_kabuto_logs(api: RecipeTestApi) -> None:
  """Tars and uploads the contents of borealis/kabuto/logs/."""
  time_now_utc = api.time.utcnow().strftime("%Y-%m-%d-%H%M%S")
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
      remote = 'https://chrome-internal.googlesource.com/chromeos/platform/borealis'
      # Clone Borealis, Kabuto is in borealis/tools/kabuto.
      api.git.clone(remote)
      # Check out a specific Kabuto commit ref from the tree
      if properties.kabuto_commit_ref:
        api.git.checkout(properties.kabuto_commit_ref, force=True)
      # Check out a specific Kabuto CL ref from Gerrit
      if properties.kabuto_cl_ref:
        api.git.fetch(remote)
        api.git.fetch_ref(remote, properties.kabuto_cl_ref)
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
      api.step('run kabuto',
               ['./tools/kabuto/kabuto', '--gcs', '--no-interactive'])

    # Upload Kabuto's logs to Google Storage.
    with api.step.nest('upload kabuto logs'):
      _upload_kabuto_logs(api)

    # Get info on newly compiled shadercaches for uprev.
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
  yield api.test('basic', api.properties(**good_props))

  props = good_props.copy()
  del props['payload_gs_bucket']
  yield api.test(
      'missing-payload-GS-bucket',
      api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'fetch kabuto payload'),
      status='FAILURE',
  )

  props = good_props.copy()
  del props['payload_gs_path']
  yield api.test(
      'missing-payload-GS-path',
      api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'fetch kabuto payload'),
      status='FAILURE',
  )

  props = good_props.copy()
  props['kabuto_commit_ref'] = '17e956ddabe4cba4c247dd39ebfd3e29eca5ff89'
  yield api.test(
      'kabuto_commit_ref',
      api.properties(**props),
  )

  props = good_props.copy()
  props['kabuto_cl_ref'] = 'refs/changes/75/5888475/2'
  yield api.test(
      'kabuto_cl_ref',
      api.properties(**props),
  )
