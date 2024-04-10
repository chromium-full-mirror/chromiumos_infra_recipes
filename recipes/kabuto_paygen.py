# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating a Kabuto payload."""

from typing import Generator

from PB.recipes.chromeos.kabuto_paygen import (KabutoPaygenProperties)
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'depot_tools/depot_tools',
    'depot_tools/gsutil',
    'build_menu',
    'cros_sdk',
    'cros_source',
    'easy',
    'git',
    'src_state',
]


PROPERTIES = KabutoPaygenProperties

_MILESTONE_USES_INPUT_MANIFEST_BRANCH = 122


def _gs_path(api: RecipeApi, bucket: str, path: str) -> str:
  """Returns the full gs:// path for given bucket and path."""
  return 'gs://' + api.path.join(bucket, path)


def RunSteps(api: RecipeApi, properties: KabutoPaygenProperties) -> None:
  with api.step.nest('validate properties') as presentation:
    if not properties.destination_gs_bucket:
      raise StepFailure('must set destination_gs_bucket')
    if not properties.destination_gs_path:
      raise StepFailure('must set destination_gs_path')
    if properties.use_release_build_artifacts and not properties.manifest_branch:
      raise StepFailure(
          'manifest_branch must be set when using release build artifacts')
    if properties.use_postsubmit_build_artifacts and properties.manifest_branch:
      raise StepFailure(
          'manifest_branch must not be set when using postsubmit build artifacts'
      )
    if not properties.borealis_remote_url:
      properties.borealis_remote_url = 'https://chrome-internal.googlesource.com/chromeos/platform/borealis'

    presentation.step_text = 'all properties good'

  commit = None
  if properties.manifest_branch:
    commit = api.src_state.internal_manifest.as_gitiles_commit_proto
    commit.ref = 'refs/heads/{}'.format(properties.manifest_branch)

  with api.build_menu.configure_builder(commit=commit, missing_ok=True), \
    api.build_menu.setup_workspace(), api.cros_sdk.cleanup_context():
    api.cros_sdk.create_chroot(timeout_sec=None)
    api.cros_sdk.update_chroot(timeout_sec=None)

    return DoRunSteps(api, properties)


def DoRunSteps(api: RecipeApi, properties: KabutoPaygenProperties) -> None:
  chroot_path = api.cros_source.workspace_path
  kabuto_path = chroot_path.join('src/platform/borealis/tools/kabuto')
  with api.context(cwd=kabuto_path), api.depot_tools.on_path():
    # If we are operating on a specific Gerrit CL ref on a staging builder we
    # should checkout platform/borealis to it now.
    if properties.gerrit_cl_ref and api.build_menu.is_staging:
      with api.step.nest('Checkout Gerrit CL'):
        api.git.fetch(properties.borealis_remote_url)
        api.git.fetch_ref(properties.borealis_remote_url,
                          properties.gerrit_cl_ref)
        api.git.checkout('FETCH_HEAD', force=True)
    kabuto_cmd = ['./kabuto']
    # Override local Kabuto config if provided.
    if properties.kabuto_config_override:
      kabuto_cmd.append('--kabuto-config-override')
      kabuto_cmd.append(properties.kabuto_config_override)
    # --input-manifest-branch is required in Kabuto from M122 onward to
    # support Spanner metrics. Do not use this flag in earlier releases.
    if properties.manifest_branch and properties.milestone >= _MILESTONE_USES_INPUT_MANIFEST_BRANCH:
      kabuto_cmd.append(f'--input-manifest-branch={properties.manifest_branch}')
    # Build Mesa and fossilize tools.
    if properties.use_release_build_artifacts:
      # Use artifacts from a CrOS release build.
      kabuto_cmd.append('build-fossilize-tools-release')
      if properties.manifest_branch and properties.milestone < _MILESTONE_USES_INPUT_MANIFEST_BRANCH:
        kabuto_cmd.append(f'--manifest-branch={properties.manifest_branch}')
    elif properties.use_postsubmit_build_artifacts:
      # Use artifacts from a CrOS postsubmit build.
      kabuto_cmd.append('build-fossilize-tools-postsubmit')
    else:
      # Default build style, from source.
      kabuto_cmd.append('build-fossilize-tools')

    api.step('build fossilize-tools', kabuto_cmd)

    # TODO(b/282030070): randomize this to avoid collisions.
    time_now_utc = api.time.utcnow()
    time_string = time_now_utc.strftime('%Y%m%d%H%M%S%f')
    payload_filename = 'kabuto_payload-' + time_string + '.tar.xz'

    # Tar payload for upload.
    api.step('tar up payload',
             ['tar', 'cvfJ', payload_filename, '-C', 'in/', 'fossilize_tool/'])

    # Upload payload to GS.
    upload_path = api.path.join(properties.destination_gs_path,
                                payload_filename)
    api.gsutil.upload(payload_filename, properties.destination_gs_bucket,
                      upload_path)

    # Set output properties for orchestrator.
    payload_gs_url = _gs_path(api, properties.destination_gs_bucket,
                              upload_path)
    api.easy.set_properties_step(payload_gs_url=payload_gs_url)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  good_props = {
      'destination_gs_bucket': 'chromeos-localmirror-private',
      'destination_gs_path': 'borealis',
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
          'build fossilize-tools',
          [
              './kabuto', '--kabuto-config-override',
              '{"build_shader_cache": {"soft_timeout_seconds": 3}}',
              'build-fossilize-tools'
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  del props['destination_gs_bucket']
  yield api.test(
      'no-destination_gs_bucket',
      api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'build fossilize-tools'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  props = good_props.copy()
  del props['destination_gs_path']
  yield api.test(
      'no-destination_gs_path',
      api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'build fossilize-tools'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  props = good_props.copy()
  props['gerrit_cl_ref'] = 'refs/changes/75/5888475/2'
  yield api.test(
      'use-cl-ref',
      api.properties(**props),
      api.buildbucket.generic_build(bucket='staging'),
      api.post_check(post_process.MustRun, 'Checkout Gerrit CL.git fetch'),
      api.post_process(
          post_process.StepCommandContains,
          'Checkout Gerrit CL.git fetch (2)',
          [
              'git',
              'fetch',
              'https://chrome-internal.googlesource.com/chromeos/platform/borealis',
              'refs/changes/75/5888475/2:',
          ],
      ),
      api.post_check(post_process.MustRun, 'Checkout Gerrit CL.git rev-parse'),
      api.post_process(
          post_process.StepCommandContains,
          'Checkout Gerrit CL.git checkout',
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
      api.post_check(post_process.DoesNotRun, 'Checkout Gerrit CL'),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['manifest_branch'] = 'release-R105-14989.B'
  yield api.test(
      'branched-manifest',
      api.properties(**props),
      api.post_check(post_process.MustRun,
                     'configure builder.cros_infra_config.gitiles-fetch-ref'),
      api.post_process(
          post_process.StepCommandContains,
          'ensure synced checkout.repo init',
          [
              '--manifest-branch',
              'release-R105-14989.B',
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['manifest_branch'] = 'release-R122-12345.B'
  props['milestone'] = 122
  props['use_release_build_artifacts'] = True
  yield api.test(
      'use-release-artifacts',
      api.properties(**props),
      api.post_process(
          post_process.StepCommandContains,
          'build fossilize-tools',
          [
              './kabuto',
              '--input-manifest-branch=release-R122-12345.B',
              'build-fossilize-tools-release',
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['manifest_branch'] = 'release-R121-12345.B'
  props['milestone'] = 121
  props['use_release_build_artifacts'] = True
  yield api.test(
      'no-input-manifest-branch-before-122',
      api.properties(**props),
      api.post_process(
          post_process.StepCommandContains,
          'build fossilize-tools',
          [
              './kabuto',
              'build-fossilize-tools-release',
              '--manifest-branch=release-R121-12345.B',
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['use_postsubmit_build_artifacts'] = True
  yield api.test(
      'use-postsubmit-artifacts',
      api.properties(**props),
      api.post_process(
          post_process.StepCommandContains,
          'build fossilize-tools',
          [
              './kabuto',
              'build-fossilize-tools-postsubmit',
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['use_release_build_artifacts'] = True
  yield api.test(
      'use-release-artifacts-without-manifest-branch',
      api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'build fossilize-tools'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  props = good_props.copy()
  props['use_postsubmit_build_artifacts'] = True
  props['manifest_branch'] = 'release-R105-14989.B'
  yield api.test(
      'use-postsubmit-artifacts-with-manifest-branch',
      api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'build fossilize-tools'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
