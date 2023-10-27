# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import re
from typing import Generator

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from PB.recipes.chromeos.chromeos_cbuildbot import (ChromeosCbuildbotProperties)
from recipe_engine.recipe_api import InfraFailure
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/legacy_annotation',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'depot_tools/gitiles',
    'bot_cost',
    'chromite',
    'easy',
    'gcloud',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = ChromeosCbuildbotProperties


def RunSteps(api: RecipeApi,
             properties: ChromeosCbuildbotProperties) -> result_pb2.RawResult:
  result = result_pb2.RawResult(status=common_pb2.SUCCESS,)

  try:
    DoRunSteps(api, properties)
  except InfraFailure as ex:  #pragma: no cover
    result.status = common_pb2.INFRA_FAILURE
    result.summary_markdown = MakeSummaryMarkdown(api, ex)
    raise
  except StepFailure as ex:
    result.status = common_pb2.FAILURE
    result.summary_markdown = MakeSummaryMarkdown(api, ex)
    raise

  return result


def DoRunSteps(api: RecipeApi, properties: ChromeosCbuildbotProperties) -> None:
  # Copy input properties to output properties. cbuildbot makes some
  # assumptions on the presence of input properties in output properties.
  # See b/243052729 for context.
  input_properties = api.properties.thaw()
  api.easy.set_properties_step(
      step_name='copy input properties to output properties',
      **input_properties)

  # Get parameters specified in the tryjob description.
  cbb_extra_args = api.properties.get('cbb_extra_args', [])

  # If cbb_extra_args is a non-empty string, translate from json to list.
  if cbb_extra_args and isinstance(cbb_extra_args, str):
    cbb_extra_args = json.loads(cbb_extra_args)

  # Apply our adjusted configuration.
  api.chromite.configure(CBB_EXTRA_ARGS=cbb_extra_args)

  # Fetch chromite and pinned depot tools.
  api.chromite.checkout_chromite()

  # Update or install goma client via cipd.
  api.chromite.m.goma.initialize(also_bq_upload=True)
  api.chromite.m.goma.client_version = api.properties.get(
      'cbb_goma_client_type')

  with api.chromite.with_system_python(), \
    api.gcloud.cleanup_gce_disks(), \
    api.gcloud.cleanup_mounted_disks(), \
    api.bot_cost.build_cost_context():
    source_cache_branch = (
        properties.source_cache_branch or api.chromite.chromite_branch)
    recipe_mount_path = api.gcloud.setup_cache_disk(
        cache_name='chromeos', branch=source_cache_branch,
        disk_type='pd-standard', disk_size='1024GB', recipe_mount=True,
        mount_existing=True,
        recovery_snapshot=properties.recovery_source_cache_snapshot)
    api.easy.set_properties_step(recipe_mount_path=recipe_mount_path)
    api.chromite.run()


def MakeSummaryMarkdown(api: RecipeTestApi, failure: StepFailure) -> str:
  lines = []
  lines.append(failure.reason)

  cbb_config = api.properties.get('cbb_config', None)
  if cbb_config:
    lines.append('builder: %s' % cbb_config)

  buildset = api.properties.get('buildset', '')
  m = re.match(r'^cros/ma(in|ster)_buildbucket_id/(\d+)$', buildset)
  if m:
    lines.append('[main](https://ci.chromium.org/b/%s)' % m.groups()[0])

  return '\n\n'.join(lines)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:

  common_properties = {
      'buildername': 'Test',
      'bot_id': 'test_builder',
      'buildbucket': {
          'build': {
              'id': '12345'
          }
      },
  }

  # Test a minimal invocation.
  yield api.test(
      'swarming-builder',
      api.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj',
          cbb_config='swarming-build-config',
      ),
  )

  # Tests the summary_markdown generation, only works on failure for now
  yield api.test(
      'swarming-builder-fails',
      api.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj',
          cbb_config='swarming-build-config',
          buildset='cros/main_buildbucket_id/8904538489270332096',
      ),
      api.step_data('cbuildbot_launch [swarming-build-config]',
                    api.legacy_annotation.failure_step),
      # TODO (b/275363240): audit this test.
      status='FAILURE')

  # Test a plain tryjob.
  yield api.test(
      'tryjob-simple',
      api.properties(cbb_config='tryjob_config',
                     cbb_extra_args='["--remote-trybot"]',
                     email='user@google.com', **common_properties),
  )

  # Test a tryjob with a branch and CLs.
  yield api.test(
      'tryjob-complex',
      api.properties(
          cbb_config='tryjob_config',
          cbb_extra_args='["--remote-trybot", "-b", "release-R65-10323.B",'
          ' "-g", "900169", "-g", "902706"]', email='user@google.com',
          **common_properties),
  )

  # Test a tryjob with a branch and CLs.
  yield api.test(
      'main-builder',
      api.properties(branch='', cbb_branch='worker_branch',
                     cbb_config='main_config', **common_properties),
  )

  # Test a tryjob with a branch and CLs.
  yield api.test(
      'complex-worker-builder',
      api.properties(branch='', cbb_branch='worker_branch',
                     cbb_config='worker_config', cbb_master_build_id=123,
                     **common_properties),
  )

  # Test empty string args.
  yield api.test(
      'empty-string-args',
      api.properties(cbb_config='tryjob_config', cbb_extra_args='',
                     email='user@google.com', **common_properties),
  )

  # Test tuple args. I'm not sure what mechanism gets them here, but it
  # can happen.
  yield api.test(
      'tuple-args',
      api.properties(cbb_config='tryjob_config',
                     cbb_extra_args=('--remote-trybot', '-foo'),
                     email='user@google.com', **common_properties),
  )

  yield api.test(
      'goma-canary',
      api.properties(
          cbb_config='amd64-generic-goma-canary-chromium-pfq-informational',
          cbb_goma_canary=True, email='user@google.com', **common_properties),
  )

  # Source Cache disk.
  yield api.test(
      'source-cache-builder',
      api.properties(branch='', cbb_branch='main',
                     cbb_config='amd64-generic-msan-fuzzer',
                     **common_properties),
  )
