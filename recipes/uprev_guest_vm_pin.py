# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for Upreving Guest VM version pin files.

This recipe copies a VM image artifact from the chromeos-image-archive to the
localmirror and then modifies the Guest VM's version pin to match this version.

"""

from google.protobuf import json_format
from google.protobuf.struct_pb2 import Struct
from recipe_engine.recipe_api import StepFailure

from PB.chromiumos.common import PackageInfo

from PB.go.chromium.org.luci.buildbucket.proto import build as bb_build
from PB.go.chromium.org.luci.buildbucket.proto import builder as bb_builder
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       bb_service)
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common
from PB.recipes.chromeos.uprev_guest_vm_pin import UprevGuestVmPinProperties, VmBoardImage

DEPS = [
    'cros_source',
    'gerrit',
    'git',
    'repo',
    'depot_tools/gsutil',
    'recipe_engine/archive',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

PROPERTIES = UprevGuestVmPinProperties

_base_vm_name = 'guest-vm-base'
_test_vm_name = 'guest-vm-test'


def _gs_path(bucket, path):
  """Returns the full gs:// path for bucket and path."""
  return 'gs://' + bucket + '/' + path


def _version_comparator(a, b):
  """ Returns true if version |a| is greater than or equal to |b|

  |a| and |b| are expected to be strings of numbers separated by |.|
  """
  a_parts = a.split('.')
  b_parts = b.split('.')

  min_length = min(len(a_parts), len(b_parts))

  for i in range(min_length):
    if int(a_parts[i]) > int(b_parts[i]):
      return True

    if int(a_parts[i]) < int(b_parts[i]):
      return False

  # If everything else is equal but |a| has more subversions, |a| is greater.
  return len(a_parts) > len(b_parts)


def _sanitize_version_number(version):
  """ Removes the R prefix and converts the '- to ebuild compatible '.'
      e.g. R80-1234.0.1 -> 80.1234.0.1
  """
  sanitized_version = version[1:]
  return sanitized_version.replace('-', '.')


def _validate_properties(properties):
  """ Helper function that validates all necessary fields are present in the
      |properties| struct. If they are not, ValueErrors are raised.
  """
  if not properties.version_file:
    raise ValueError('must set version_file')

  if not properties.vm_board_images:
    raise ValueError('must set vm_board_images')

  for vm_board_image in properties.vm_board_images:
    board = vm_board_image.board
    if not board:
      raise ValueError('must set board')

    if not vm_board_image.destination_gs_bucket:
      raise ValueError('must set destination_gs_bucket for {}'.format(board))

    if not vm_board_image.destination_gs_path:
      raise ValueError('must set destination_gs_path for {}'.format(board))


def RunSteps(api, properties):
  with api.step.nest('validate properties') as presentation:
    _validate_properties(properties)
    presentation.step_text = 'all properties good'

  with api.step.nest('get latest postsubmit build version'):
    version_build_map = {}
    vm_property_map = {}

    # For each vm board image. Find the 4 latest successful builds. This
    # approximately covers a day of postsubmit runs.
    for vm_board_image in properties.vm_board_images:
      board = vm_board_image.board
      vm_property_map[board] = vm_board_image

      builder_name = '{}-postsubmit'.format(vm_board_image.board)
      board_builds = {}

      with api.step.nest('query-{}'.format(board)):
        board_builds[board] = api.buildbucket.search(
            predicate=bb_service.BuildPredicate(
                builder=bb_builder.BuilderID(
                    project='chromeos',
                    bucket='postsubmit',
                    builder=builder_name,
                ), status=bb_common.SUCCESS), limit=4)

      if not board_builds[board]:
        raise StepFailure(
            'unable to find latest build for {}'.format(builder_name))

      # For each successful build, use the version number as a key and
      # add the build to the version map.
      for build in board_builds[board]:
        version = build.output.properties['chromeos_version']
        if version not in version_build_map:
          version_build_map[version] = {board: build}

        version_build_map[version][board] = build

    # Find the highest common version for all the VMs.
    build_index = '0'
    sanitized_common_version = '0'
    for version, builds in version_build_map.items():
      sanitized_version = _sanitize_version_number(version)
      if len(builds) == len(properties.vm_board_images) and _version_comparator(
          sanitized_version, sanitized_common_version):
        sanitized_common_version = sanitized_version
        build_index = version

    # If no common version can be found, raise an error.
    if sanitized_common_version == '0':
      raise StepFailure('unable to find common build to uprev for all boards')

  with api.cros_source.checkout_overlays_context():
    api.cros_source.ensure_synced_cache()
    version_path = api.cros_source.workspace_path.join(properties.version_file)
    package_path = api.path.dirname(version_path)
    package = api.path.basename(package_path)

    with api.step.nest('try uprev version file') as presentation:
      api.file.write_raw(name='version file', dest=version_path,
                         data=str(sanitized_common_version))

      with api.context(cwd=api.path.abs_to_path(package_path)):
        if not api.git.diff_check(version_path):
          presentation.step_text = (
              'skipping uprev for {}. version unchanged').format(package)
          return

    with api.step.nest('commit uprev'), \
          api.context(cwd=api.path.abs_to_path(package_path)):
      project = api.repo.project_info(project=api.git.repository_root())
      api.repo.start('uprev-guest-vm', projects=[project.name])

      message = '{}: updating version pin to latest - {}'.format(
          package, sanitized_common_version)
      api.git.add([version_path])
      api.git.commit(message)

    with api.step.nest('copy images to destination bucket'):

      for board, build in version_build_map[build_index].items():
        tmp_dir = api.path.mkdtemp(prefix='archive-staging')
        with api.context(cwd=tmp_dir):
          build_artifact_bucket = str(
              build.output.properties['artifacts']['gs_bucket'])
          build_artifact_path = str(
              build.output.properties['artifacts']['gs_path'])
          src_path = '{}/{}'.format(build_artifact_path, "image.zip")
          api.gsutil.download(build_artifact_bucket, src_path, './')
          api.archive.extract('unzip image archive',
                              api.context.cwd.join('image.zip'),
                              api.context.cwd.join('image'))

          base_image_path = api.context.cwd.join('image', _base_vm_name)
          base_tar = api.archive.package(base_image_path).archive(
              'archive base guest VM',
              api.context.cwd.join(_base_vm_name + '.tbz'), 'tbz')

          test_image_path = api.context.cwd.join('image', _test_vm_name)
          test_tar = api.archive.package(test_image_path).archive(
              'archive test guest VM',
              api.context.cwd.join(_test_vm_name + '.tbz'), 'tbz')

          dst_bucket = vm_property_map[board].destination_gs_bucket
          dst_path = '{}/{}/'.format(vm_property_map[board].destination_gs_path,
                                     sanitized_common_version)
          api.gsutil.upload("*.tbz", dst_bucket, dst_path)

        if properties.user_acls or properties.group_acls:
          with api.step.nest('set image permissions on destination'):
            cmd = ['acl', 'ch', '-r']
            for user_acl in properties.user_acls:
              cmd += ['-u', user_acl]

            for group_acl in properties.group_acls:
              cmd += ['-g', group_acl]

            cmd += [_gs_path(dst_bucket, dst_path)]

            api.gsutil(cmd)

    with api.step.nest('generate CL'):
      change = api.gerrit.create_change(project=project.name, topic=package)

      labels = {
          api.gerrit.Label.BOT_COMMIT: 1,
          api.gerrit.Label.COMMIT_QUEUE: 2,
      }
      api.gerrit.set_change_labels(change, labels)


def GenTests(api):
  sludge_properties = json_format.MessageToDict(
      UprevGuestVmPinProperties(
          version_file=('src/private-overlays/project-wilco-private/'
                        'chromeos-base/chromeos-dtc-vm/VERSION-PIN'),
          vm_board_images=[
              VmBoardImage(
                  board='sludge',
                  destination_gs_bucket='chromeos-localmirror-private',
                  destination_gs_path='distfiles/sludge',
              )
          ],
          user_acls=['tony.stark@google.com:OWNER', 'bighead@google.com:READ'],
          group_acls=['koolkids@google.com:READ']))

  sludge_builds = _generate_build_set([3, 2, 1, 0], 'sludge')

  buildbucket_search_step = 'get latest postsubmit build version.query-{}.buildbucket.search'

  mock_sludge_build_search = api.buildbucket.simulated_search_results(
      sludge_builds, step_name=buildbucket_search_step.format('sludge'))

  termina_properties = json_format.MessageToDict(
      UprevGuestVmPinProperties(
          version_file=('src/third_party/chromiumos-overlay/'
                        'chromeos-base/termina-dlc/VERSION-PIN'),
          vm_board_images=[
              VmBoardImage(board='tatl',
                           destination_gs_bucket='termina-component-testing',
                           destination_gs_path='uprev-test/amd64'),
              VmBoardImage(board='tael',
                           destination_gs_bucket='termina-component-testing',
                           destination_gs_path='uprev-test/arm')
          ],
          user_acls=['tony.stark@google.com:OWNER', 'bighead@google.com:READ'],
          group_acls=['koolkids@google.com:READ']))

  tatl_builds_success = _generate_build_set([10, 8, 6, 5], 'tatl')
  tael_builds_success = _generate_build_set([9, 7, 5, 3], 'tael')
  tael_builds_no_common = _generate_build_set([9, 7, 4, 3], 'tael')
  tatl_builds_subversion = _generate_build_set([9, 9.0], 'tatl')
  tael_builds_subversion = _generate_build_set([9, 9.0], 'tael')
  tatl_builds_falloff = _generate_build_set([10.1, 10], 'tatl')
  tael_builds_falloff = _generate_build_set([10.1, 10], 'tael')

  mock_tatl_build_search_success = api.buildbucket.simulated_search_results(
      tatl_builds_success, step_name=buildbucket_search_step.format('tatl'))

  mock_tael_build_search_success = api.buildbucket.simulated_search_results(
      tael_builds_success, step_name=buildbucket_search_step.format('tael'))

  mock_tatl_build_search_subversion = api.buildbucket.simulated_search_results(
      tatl_builds_subversion, step_name=buildbucket_search_step.format('tatl'))

  mock_tael_build_search_subversion = api.buildbucket.simulated_search_results(
      tael_builds_subversion, step_name=buildbucket_search_step.format('tael'))

  mock_tael_build_search_no_common = api.buildbucket.simulated_search_results(
      tael_builds_no_common, step_name=buildbucket_search_step.format('tael'))

  mock_tatl_build_search_falloff = api.buildbucket.simulated_search_results(
      tatl_builds_falloff, step_name=buildbucket_search_step.format('tatl'))

  mock_tael_build_search_falloff = api.buildbucket.simulated_search_results(
      tael_builds_falloff, step_name=buildbucket_search_step.format('tael'))

  yield api.test(
      'uprev-sludge',
      api.properties(**sludge_properties),
      api.git.diff_check(True),
      mock_sludge_build_search,
  )

  yield api.test(
      'uprev-termina',
      api.properties(**termina_properties),
      api.git.diff_check(True),
      mock_tatl_build_search_success,
      mock_tael_build_search_success,
  )

  yield api.test(
      'no-common-builds',
      api.properties(**termina_properties),
      api.git.diff_check(True),
      mock_tatl_build_search_success,
      mock_tael_build_search_no_common,
  )

  yield api.test(
      'version-compare-subversions',
      api.properties(**termina_properties),
      api.git.diff_check(True),
      mock_tatl_build_search_subversion,
      mock_tael_build_search_subversion,
  )

  yield api.test(
      'version-compare-falloff',
      api.properties(**termina_properties),
      api.git.diff_check(True),
      mock_tatl_build_search_falloff,
      mock_tael_build_search_falloff,
  )

  yield api.test(
      'no-version-file',
      api.properties(**sludge_properties),
      api.properties(versionFile=''),
      api.expect_exception('ValueError'),
  )

  yield api.test(
      'no-vm-board-images',
      api.properties(**sludge_properties),
      api.properties(vmBoardImages=[]),
      api.expect_exception('ValueError'),
  )

  yield api.test(
      'no-board',
      api.properties(**sludge_properties),
      api.properties(vmBoardImages=[
          json_format.MessageToDict(
              VmBoardImage(
                  board='',
                  destination_gs_bucket='chromeos-localmirror-private',
                  destination_gs_path='distfiles/sludge',
              ))
      ]),
      api.expect_exception('ValueError'),
  )

  yield api.test(
      'no-destination-gs-bucket',
      api.properties(**sludge_properties),
      api.properties(vmBoardImages=[
          json_format.MessageToDict(
              VmBoardImage(
                  board='sludge',
                  destination_gs_bucket='',
                  destination_gs_path='distfiles/sludge',
              ))
      ]),
      api.expect_exception('ValueError'),
  )

  yield api.test(
      'no-destination-gs-path',
      api.properties(**sludge_properties),
      api.properties(vmBoardImages=[
          json_format.MessageToDict(
              VmBoardImage(
                  board='sludge',
                  destination_gs_bucket='chromeos-localmirror-private',
                  destination_gs_path='',
              ))
      ]),
      api.expect_exception('ValueError'),
  )

  yield api.test(
      'no-version-diff',
      api.properties(**sludge_properties),
      api.git.diff_check(False),
      mock_sludge_build_search,
  )

  yield api.test(
      'no-latest-postsubmit-build',
      api.properties(**sludge_properties),
      api.buildbucket.simulated_search_results(
          [],
          step_name='get latest postsubmit build version.query-sludge.buildbucket.search'
      ),
  )

  yield api.test(
      'no-acls',
      api.properties(**sludge_properties),
      api.properties(userAcls=[], groupAcls=[]) + api.git.diff_check(True),
      mock_sludge_build_search,
  )


# Helper function to create a set of parameterized buildbucket build objects.
def _generate_build_set(ids, board):
  builds = []
  for index, id in enumerate(ids):
    build_artifacts = {
        'gs_path': 'postsubmit-{0}/R80-1.2.{1}-{1}'.format(board, id),
        'gs_bucket': 'chromeos-image-archive'
    }
    properties = Struct()
    properties['chromeos_version'] = 'R80-1.2.{0}'.format(id)
    properties['artifacts'] = build_artifacts

    builds.append(
        bb_build.Build(id=index + 1, status=bb_common.SUCCESS,
                       output=bb_build.Build.Output(properties=properties)))

  return builds
