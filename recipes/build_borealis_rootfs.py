# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a Borealis rootfs image."""

import re
from typing import Generator

from RECIPE_MODULES.chromeos.gerrit.api import Label

from PB.recipes.chromeos.build_borealis_rootfs import (
    BuildBorealisRootfsProperties)
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'depot_tools/depot_tools',
    'depot_tools/gsutil',
    'build_menu',
    'cros_sdk',
    'cros_source',
    'gerrit',
    'git',
    'repo',
    'src_state',
]


PROPERTIES = BuildBorealisRootfsProperties

_PANTHEON_PREFIX = 'https://pantheon.corp.google.com/storage/browser'


def _gs_path(bucket: str, path: str) -> str:
  """Returns the full gs:// path for bucket and path."""
  return 'gs://' + bucket + '/' + path


def RunSteps(api: RecipeApi, properties: BuildBorealisRootfsProperties) -> None:
  with api.step.nest('validate properties') as presentation:
    if not properties.package_info.category:
      raise StepFailure('must set package_info.category')
    if not properties.package_info.package_name:
      raise StepFailure('must set package_info.package_name')
    if not properties.destination_gs_bucket:
      raise StepFailure('must set destination_gs_bucket')
    if not properties.destination_gs_path:
      raise StepFailure('must set destination_gs_path')

    presentation.step_text = 'all properties good'

  commit = None
  if properties.manifest_branch:
    commit = api.src_state.internal_manifest.as_gitiles_commit_proto
    commit.ref = 'refs/heads/{}'.format(properties.manifest_branch)

  with api.build_menu.configure_builder(commit=commit, missing_ok=True), \
    api.build_menu.setup_workspace(), api.cros_sdk.cleanup_context():
    api.cros_sdk.create_chroot(timeout_sec=None)

    return DoRunSteps(api, properties)


def DoRunSteps(api: RecipeApi,
               properties: BuildBorealisRootfsProperties) -> None:
  checkout_path = api.cros_source.workspace_path
  chroot_path = api.build_menu.chroot.path
  out_dir = api.build_menu.chroot.out_path
  borealis_path = checkout_path / 'src/platform/borealis'
  with api.context(cwd=borealis_path), api.depot_tools.on_path():
    # This recipe should only run on bots with docker pre-installed.  Abort
    # immediately if that is not the case.
    api.step('check docker install', ['docker', 'help'])

    # Following the instructions at
    # src/platform/borealis/docs/build-and-deploy.md
    # TODO(davidriley): Perform the build steps in parallel.
    api.step('borealis_kernel', [
        './tools/borealis_kernel.py', f'--chroot={chroot_path}',
        f'--out-dir={out_dir}'
    ])

    borealis_build_cmd = [
        './tools/build_full.py', '--no-cache', f'--chroot={chroot_path}',
        f'--out-dir={out_dir}'
    ]
    if properties.disable_arch_sig_validation:
      borealis_build_cmd.append('--disable-arch-sig-validation')
    if properties.docker_variant:
      borealis_build_cmd.append('--variant')
      borealis_build_cmd.append(properties.docker_variant)

    api.step('borealis build_full.py', borealis_build_cmd)
    api.step('convert_docker_image', ['./tools/convert_docker_image.py'])

    # Version the archive.
    version = api.time.utcnow().strftime('%Y.%m.%d.%H%M%S')
    if properties.manifest_branch:
      # Extract the version number from the provided manifest branch
      milestone_number_regex = r'^release-R([0-9]+)-'
      match = re.search(milestone_number_regex, properties.manifest_branch)
      milestone_number = match.group(1)
      # Prepend the milestone into the version in a way ebuilds can uprev
      version = milestone_number + '.' + version

    package_name = properties.package_info.package_name
    archive_name = package_name + '-' + version + '.tar.xz'

    with api.step.nest('upload VM imaage') as presentation:
      bucket_url = _gs_path(properties.destination_gs_bucket,
                            properties.destination_gs_path)
      api.step('uprev_dlc', [
          './tools/uprev_dlc.py', '--archive', archive_name, '--bucket_url',
          bucket_url, '--nouprev', f'--chroot={chroot_path}',
          f'--out-dir={out_dir}'
      ])
      presentation.links['VM image'] = api.path.join(
          _PANTHEON_PREFIX, properties.destination_gs_bucket,
          properties.destination_gs_path, archive_name)

    # Do not build if we are in manifest branch.
    if not properties.manifest_branch and properties.build_tast_binaries:
      api.step('borealis tast taball', [
          './tools/build_tast_binaries.py', '--no-output-append-date',
          '--output=public-borealis-tast-binaries-' + version,
          f'--chroot={chroot_path}', f'--out-dir={out_dir}'
      ])
      tast_archive_name = 'public-borealis-tast-binaries-' + version + '.tar.zst'
      with api.step.nest('upload tast tarball') as presentation:
        bucket_url = properties.destination_gs_bucket
        path_url = properties.destination_gs_path
        api.gsutil.upload(tast_archive_name, bucket_url, path_url)
        presentation.links['tarball'] = api.path.join(_PANTHEON_PREFIX,
                                                      bucket_url, path_url,
                                                      tast_archive_name)

    # If the version_file is not set, skip updating the version_file
    if not properties.version_file:
      return

    with api.step.nest('update VERSION-PIN') as presentation:
      version_path = api.cros_source.workspace_path.joinpath(
          properties.version_file)
      package_path = api.path.dirname(version_path)
      version_basename = api.path.basename(version_path)
      metadata_path = api.path.join(package_path, 'metadata.xml')

      with api.step.nest('write version pin file'):
        api.file.write_raw(name='version file', dest=version_path, data=version)

      # Copy metadata.xml (written by tools/build_full.py).
      api.file.copy(
          'copy metadata.xml file',
          borealis_path / 'metadata.xml',
          metadata_path,
      )

      with api.step.nest('commit version pin file and metadata.xml'), \
            api.context(cwd=api.path.abs_to_path(package_path)):
        project = api.repo.project_info(project=api.git.repository_root())
        api.repo.start('uprev-borealis-pin', projects=[project.name])

        message = '{}: updating version pin {} to {}\n\n'.format(
            version_basename, package_name, version)
        message += 'CL generated by job {}'.format(api.buildbucket.build_url())

        api.git.add([version_path, metadata_path])
        api.git.commit(message)

      # Upload CL to gerrit as long as not in staging.
      if not api.build_menu.is_staging:
        with api.step.nest('upload CL to gerrit'):
          change = api.gerrit.create_change(project=project.name,
                                            topic=package_name)
          labels = {
              Label.BOT_COMMIT: 1,
              Label.COMMIT_QUEUE: 2,
          }
          api.gerrit.set_change_labels(change, labels)

          presentation.links['CL'] = api.gerrit.parse_gerrit_change_url(change)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  good_props = {
      'version_file': ('src/private-overlays/chromeos-overlay/chromeos-base/'
                       'borealis-dlc/VERSION_PIN'),
      'package_info': {
          'category': 'chromeos-base',
          'package_name': 'borealis-dlc',
      },
      'destination_gs_bucket': 'chromeos-localmirror-private',
      'destination_gs_path': 'borealis',
      'build_tast_binaries': False,
  }
  yield api.test(
      'basic',
      api.properties(**good_props),
  )

  # version-pin is optional, if not set, it still passes but would not update
  # the PIN.
  props = good_props.copy()
  del props['version_file']
  yield api.test(
      'no-version_file',
      api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['docker_variant'] = 'chroot'
  yield api.test(
      'docker_variant chroot',
      api.properties(**props),
      api.post_process(
          post_process.StepCommandContains, 'borealis build_full.py', [
              './tools/build_full.py', '--no-cache',
              '--chroot=[CACHE]/cros_chroot/chroot',
              '--out-dir=[CACHE]/cros_chroot/out', '--variant', 'chroot'
          ]),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['disable_arch_sig_validation'] = True
  yield api.test(
      'disable-arch-sig-validation',
      api.properties(**props),
      api.post_process(post_process.StepCommandContains,
                       'borealis build_full.py', [
                           './tools/build_full.py', '--no-cache',
                           '--chroot=[CACHE]/cros_chroot/chroot',
                           '--out-dir=[CACHE]/cros_chroot/out',
                           '--disable-arch-sig-validation'
                       ]),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['build_tast_binaries'] = True
  yield api.test(
      'build_tast_binaries',
      api.properties(**props),
      api.post_check(post_process.MustRun, 'upload tast tarball'),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  yield api.test(
      'no-build_tast_binaries',
      api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'upload tast tarball'),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  del props['package_info']
  yield api.test(
      'no-package_info',
      api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  props = good_props.copy()
  props['package_info'] = good_props['package_info'].copy()
  del props['package_info']['package_name']
  yield api.test(
      'no-package_info.package_name',
      api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  props = good_props.copy()
  del props['destination_gs_bucket']
  yield api.test(
      'no-destination_gs_bucket',
      api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  props = good_props.copy()
  del props['destination_gs_path']
  yield api.test(
      'no-destination_gs_path',
      api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
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
      api.post_process(post_process.StepCommandContains,
                       'upload VM imaage.uprev_dlc', [
                           '--archive',
                           'borealis-dlc-105.2012.05.14.125327.tar.xz',
                       ]),
      api.post_process(post_process.DropExpectation),
  )

  props = good_props.copy()
  props['manifest_branch'] = 'abcdefg'
  yield api.test(
      'bad-manifest-branch',
      api.properties(**props),
      api.expect_exception('AttributeError'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )
