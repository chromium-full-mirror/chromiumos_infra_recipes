# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for Upreving Guest VM version pin files.

This recipe copies a VM image artifact from the chromeos-image-archive to the
localmirror and then modifies the Guest VM's version pin to match this version.

"""

from collections import defaultdict

from google.protobuf import json_format, timestamp_pb2
from google.protobuf.struct_pb2 import Struct
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

from PB.chromiumos.builder_config import BuilderConfig as bc

from PB.go.chromium.org.luci.buildbucket.proto import build as bb_build
from PB.go.chromium.org.luci.buildbucket.proto import builder as bb_builder
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       bb_service)
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common
from PB.recipes.chromeos.uprev_guest_vm_pin import \
  (UprevGuestVmPinProperties, VmBoardImage)

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
    'recipe_engine/archive',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'depot_tools/gsutil',
    'cros_source',
    'cros_tags',
    'gerrit',
    'git',
    'repo',
    'src_state',
    'workspace_util',
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
  a_parts = [int(part) for part in a.split('.')]
  b_parts = [int(part) for part in b.split('.')]
  return a_parts > b_parts


def _sanitize_version_number(version):
  """ Removes the R prefix and converts the '- to ebuild compatible '.'
      e.g. R80-1234.0.1 -> 80.1234.0.1
  """
  sanitized_version = version[1:]
  return sanitized_version.replace('-', '.')


def _validate_properties(properties):
  """ Helper function that validates all necessary fields are present in the
      |properties| struct. If they are not, StepFailures are raised.
  """
  if not properties.version_file:
    raise StepFailure('must set version_file')

  if not properties.vm_board_images:
    raise StepFailure('must set vm_board_images')

  if properties.builder_type not in (bc.Id.POSTSUBMIT, bc.Id.RELEASE):
    raise StepFailure('unknown builder_type: ' + str(properties.builder_type))

  for vm_board_image in properties.vm_board_images:
    board = vm_board_image.board
    if not board:
      raise StepFailure('must set board')

    if not vm_board_image.destination_gs_bucket:
      raise StepFailure('must set destination_gs_bucket for {}'.format(board))

    if not vm_board_image.destination_gs_path:
      raise StepFailure('must set destination_gs_path for {}'.format(board))


def FindPostsubmitBuilds(api, board, version_build_map):
  # Find successful builds that started within the last 36 hours. This
  # should cover everything we're interested in, since we run once per
  # day.
  builds = api.buildbucket.search(
      predicate=bb_service.BuildPredicate(
          builder=bb_builder.BuilderID(
              project='chromeos',
              bucket='postsubmit',
              builder='{}-postsubmit'.format(board),
          ), create_time=bb_common.TimeRange(
              start_time=timestamp_pb2.Timestamp(
                  seconds=api.buildbucket.build.create_time.ToSeconds() -
                  36 * 60 * 60)), status=bb_common.SUCCESS))

  if not builds:
    raise StepFailure(
        'unable to find latest build for {}-postsubmit'.format(board))

  for build in builds:
    branch = build.input.gitiles_commit.ref.split('/')[-1]
    version = build.output.properties['chromeos_version']
    version_build_map[branch][version][board] = build


def FindLegacyReleaseBuilds(api, board, version_build_map):
  # For release builds we're interested in builds from multiple
  # branches that don't all build equally often, so instead ask for
  # builds more recent then 3 days ago.
  builds = api.buildbucket.search(
      predicate=bb_service.BuildPredicate(
          builder=bb_builder.BuilderID(
              project='chromeos',
              bucket='general',
              builder='LegacyRelease',
          ), tags=api.cros_tags.tags(cbb_config='{}-release'.format(board)),
          create_time=bb_common.TimeRange(
              start_time=timestamp_pb2.Timestamp(
                  seconds=api.buildbucket.build.create_time.ToSeconds() -
                  72 * 60 * 60)), status=bb_common.SUCCESS))

  if not builds:
    raise StepFailure(
        'unable to find latest build for {}-release'.format(board))

  for build in builds:
    branch = build.output.properties['cbb_branch']
    version = build.output.properties['full_version']
    version_build_map[branch][version][board] = build


def CopyPostsubmitImage(api, board, build, vm_property_map, sanitized_version):
  tmp_dir = api.path.mkdtemp(prefix='archive-staging')
  with api.context(cwd=tmp_dir):
    build_artifact_bucket = str(
        build.output.properties['artifacts']['gs_bucket'])
    build_artifact_path = str(build.output.properties['artifacts']['gs_path'])
    src_path = '{}/{}'.format(build_artifact_path, "image.zip")
    api.gsutil.download(build_artifact_bucket, src_path, './')
    api.archive.extract('unzip image archive',
                        api.context.cwd.join('image.zip'),
                        api.context.cwd.join('image'))

    base_image_path = api.context.cwd.join('image', _base_vm_name)
    api.archive.package(base_image_path).archive(
        'archive base guest VM', api.context.cwd.join(_base_vm_name + '.tbz'),
        'tbz')

    test_image_path = api.context.cwd.join('image', _test_vm_name)
    api.archive.package(test_image_path).archive(
        'archive test guest VM', api.context.cwd.join(_test_vm_name + '.tbz'),
        'tbz')

    dst_bucket = vm_property_map[board].destination_gs_bucket
    dst_path = '{}/{}/'.format(vm_property_map[board].destination_gs_path,
                               sanitized_version)
    api.gsutil.upload("*.tbz", dst_bucket, dst_path)


def CopyLegacyReleaseImage(api, board, build, vm_property_map,
                           sanitized_version):
  build_artifact_path = build.output.properties['artifact_link']

  # The gsutil API takes the bucket name and object path as seperate
  # parameters, but artifact_link contains a gs:// URL, so we have to
  # split up the components.
  #
  # The bucket name is everything from the 6th character (skipping
  # "gs://") to before the next slash, and the object path is
  # everything after that slash.
  idx = build_artifact_path[5:].find('/')
  src_bucket = build_artifact_path[5:5 + idx]
  src_path = build_artifact_path[idx + 6:]

  dst_bucket = vm_property_map[board].destination_gs_bucket
  dst_path = '{}/{}'.format(vm_property_map[board].destination_gs_path,
                            sanitized_version)

  api.gsutil.copy(src_bucket, '{}/{}.tbz'.format(src_path, _base_vm_name),
                  dst_bucket, '{}/{}.tbz'.format(dst_path, _base_vm_name),
                  name='copy {} base image'.format(board))
  api.gsutil.copy(src_bucket, '{}/{}.tbz'.format(src_path, _test_vm_name),
                  dst_bucket, '{}/{}.tbz'.format(dst_path, _test_vm_name),
                  name='copy {} test image'.format(board))


def RunSteps(api, properties):
  with api.step.nest('validate properties') as presentation:
    _validate_properties(properties)
    presentation.step_text = 'all properties good'

  with api.workspace_util.setup_workspace(default_main=True):
    # Sync the cache before we do anything that might touch the workspace.
    api.cros_source.ensure_synced_cache()
    api.cros_source.checkout_tip_of_tree()

    with api.step.nest('get latest build version'):
      vm_property_map = {}

      # A nested dictionary with
      # version_build_map[branch][version][board] containing a build
      # for that board with that version on that branch.
      version_build_map = defaultdict(lambda: defaultdict(lambda: {}))

      for vm_board_image in properties.vm_board_images:
        board = vm_board_image.board
        vm_property_map[board] = vm_board_image

        with api.step.nest('query-{}'.format(board)):
          if properties.builder_type == bc.Id.POSTSUBMIT:
            FindPostsubmitBuilds(api, board, version_build_map)
          elif properties.builder_type == bc.Id.RELEASE:
            FindLegacyReleaseBuilds(api, board, version_build_map)

      # Find the highest common version for all the VMs on each branch.
      version_map = {}
      for branch, rest in sorted(version_build_map.items()):
        build_index = '0'
        sanitized_common_version = '0'

        for version, board_builds in sorted(rest.items()):
          sanitized_version = _sanitize_version_number(version)
          if board_builds.keys(
          ) == vm_property_map.keys() and _version_comparator(
              sanitized_version, sanitized_common_version):
            sanitized_common_version = sanitized_version
            build_index = version

        # If no common version can be found, raise an error.
        if sanitized_common_version == '0':
          raise StepFailure('unable to find common build on branch'
                            ' {} for all boards'.format(branch))

        version_map[branch] = (build_index, sanitized_common_version)

    for branch, (version, sanitized_version) in sorted(version_map.items()):
      with api.step.nest('upreving pin for branch {}'.format(branch)):
        api.cros_source.checkout_branch(api.src_state.internal_manifest.url,
                                        branch, sync_opts={'detach': True})

        version_path = api.cros_source.workspace_path.join(
            properties.version_file)
        package_path = api.path.dirname(version_path)
        package = api.path.basename(package_path)

        with api.step.nest('try uprev version file') as presentation:
          api.file.write_raw(name='version file', dest=version_path,
                             data=str(sanitized_version))

          with api.context(cwd=api.path.abs_to_path(package_path)):
            if not api.git.diff_check(version_path):
              presentation.step_text = (
                  'skipping uprev for {} on {}, version unchanged' \
                  .format(package, branch))
              continue

        with api.step.nest('commit uprev'), \
             api.context(cwd=api.path.abs_to_path(package_path)):
          project = api.repo.project_info(project=api.git.repository_root())
          api.repo.start('uprev-guest-vm-{}'.format(branch),
                         projects=[project.name])

          message = '{}: updating version pin to latest - {}\n\n'.format(
              package, sanitized_version)
          message += 'CL generated by job {}'.format(
              api.buildbucket.build_url())

          api.git.add([version_path])
          api.git.commit(message)

        with api.step.nest('copy images to destination bucket'):
          for board, build in version_build_map[branch][version].items():
            if properties.builder_type == bc.Id.POSTSUBMIT:
              CopyPostsubmitImage(api, board, build, vm_property_map,
                                  sanitized_version)
            elif properties.builder_type == bc.Id.RELEASE:
              CopyLegacyReleaseImage(api, board, build, vm_property_map,
                                     sanitized_version)

            if properties.user_acls or properties.group_acls:
              with api.step.nest(
                  'set image permissions on destination for {}'.format(board)):
                cmd = ['acl', 'ch', '-r']
                for user_acl in properties.user_acls:
                  cmd += ['-u', user_acl]

                for group_acl in properties.group_acls:
                  cmd += ['-g', group_acl]

                dst_bucket = vm_property_map[board].destination_gs_bucket
                dst_path = '{}/{}/'.format(
                    vm_property_map[board].destination_gs_path,
                    sanitized_version)
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
          ], builder_type=bc.Id.POSTSUBMIT,
          user_acls=['tony.stark@google.com:OWNER', 'bighead@google.com:READ'],
          group_acls=['koolkids@google.com:READ']))

  sludge_builds = _generate_postsubmit_build_set([3, 2, 1, 0], 'sludge')

  buildbucket_search_step = 'get latest build version.query-{}.buildbucket.search'

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
          ], builder_type=bc.Id.POSTSUBMIT,
          user_acls=['tony.stark@google.com:OWNER', 'bighead@google.com:READ'],
          group_acls=['koolkids@google.com:READ']))

  tatl_builds_success = _generate_postsubmit_build_set([10, 8, 6, 5], 'tatl')
  tael_builds_success = _generate_postsubmit_build_set([9, 7, 5, 3], 'tael')
  tael_builds_no_common = _generate_postsubmit_build_set([9, 7, 4, 3], 'tael')
  tatl_builds_subversion = _generate_postsubmit_build_set([9, 9.0], 'tatl')
  tael_builds_subversion = _generate_postsubmit_build_set([9, 9.0], 'tael')
  tatl_builds_falloff = _generate_postsubmit_build_set([10.1, 10], 'tatl')
  tael_builds_falloff = _generate_postsubmit_build_set([10.1, 10], 'tael')

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

  termina_release_properties = json_format.MessageToDict(
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
          ], builder_type=bc.Id.RELEASE,
          user_acls=['tony.stark@google.com:OWNER', 'bighead@google.com:READ'],
          group_acls=['koolkids@google.com:READ']))

  tatl_release_builds_success = _generate_legacy_release_build_set(
      'tatl', {
          89: [10, 8, 6, 5],
          88: [5, 4, 2]
      })
  tael_release_builds_success = _generate_legacy_release_build_set(
      'tael', {
          89: [9, 7, 5],
          88: [6, 4, 1]
      })

  tael_release_builds_no_match = _generate_legacy_release_build_set(
      'tael', {
          89: [9, 7, 4],
          88: [6, 3, 1]
      })

  tael_release_builds_partial_match = _generate_legacy_release_build_set(
      'tael', {
          89: [9, 7, 5],
          88: [6, 3, 1]
      })

  mock_tatl_release_build_search_success = api.buildbucket.simulated_search_results(
      tatl_release_builds_success,
      step_name=buildbucket_search_step.format('tatl'))

  mock_tael_release_build_search_success = api.buildbucket.simulated_search_results(
      tael_release_builds_success,
      step_name=buildbucket_search_step.format('tael'))

  mock_tael_release_build_search_no_match = api.buildbucket.simulated_search_results(
      tael_release_builds_no_match,
      step_name=buildbucket_search_step.format('tael'))

  mock_tael_release_build_search_partial_match = api.buildbucket.simulated_search_results(
      tael_release_builds_partial_match,
      step_name=buildbucket_search_step.format('tael'))

  yield api.test(
      'uprev-sludge',
      api.properties(**sludge_properties),
      api.git.diff_check(True),
      mock_sludge_build_search,
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'uprev-termina',
      api.properties(**termina_properties),
      api.git.diff_check(True),
      mock_tatl_build_search_success,
      mock_tael_build_search_success,
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'no-common-builds',
      api.properties(**termina_properties),
      api.git.diff_check(True),
      mock_tatl_build_search_success,
      mock_tael_build_search_no_common,
      api.post_check(post_process.StatusFailure),
  )

  yield api.test(
      'version-compare-subversions',
      api.properties(**termina_properties),
      api.git.diff_check(True),
      mock_tatl_build_search_subversion,
      mock_tael_build_search_subversion,
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'version-compare-falloff',
      api.properties(**termina_properties),
      api.git.diff_check(True),
      mock_tatl_build_search_falloff,
      mock_tael_build_search_falloff,
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'uprev-termina-multibranch-success',
      api.properties(**termina_release_properties),
      api.git.diff_check(True),
      mock_tatl_release_build_search_success,
      mock_tael_release_build_search_success,
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'multibranch-no-version-diff',
      api.properties(**termina_release_properties),
      api.git.diff_check(False),
      mock_tatl_release_build_search_success,
      mock_tael_release_build_search_success,
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'multibranch-no-matching-builds',
      api.properties(**termina_release_properties),
      mock_tatl_release_build_search_success,
      mock_tael_release_build_search_no_match,
      api.post_check(post_process.StatusFailure),
  )

  yield api.test(
      'multibranch-no-matching-builds-on-one-branch',
      api.properties(**termina_release_properties),
      mock_tatl_release_build_search_success,
      mock_tael_release_build_search_partial_match,
      api.post_check(post_process.StatusFailure),
  )

  yield api.test(
      'no-version-file',
      api.properties(**sludge_properties),
      api.properties(versionFile=''),
      api.post_check(post_process.StatusFailure),
  )

  yield api.test(
      'no-vm-board-images',
      api.properties(**sludge_properties),
      api.properties(vmBoardImages=[]),
      api.post_check(post_process.StatusFailure),
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
      api.post_check(post_process.StatusFailure),
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
      api.post_check(post_process.StatusFailure),
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
      api.post_check(post_process.StatusFailure),
  )

  yield api.test(
      'unknown-build-type',
      api.properties(**sludge_properties),
      api.properties(builderType=123),
      api.post_check(post_process.StatusFailure),
  )

  yield api.test(
      'no-version-diff',
      api.properties(**sludge_properties),
      api.git.diff_check(False),
      mock_sludge_build_search,
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'no-latest-postsubmit-build',
      api.properties(**sludge_properties),
      api.buildbucket.simulated_search_results(
          [],
          step_name='get latest build version.query-sludge.buildbucket.search'),
      api.post_check(post_process.StatusFailure),
  )

  yield api.test(
      'no-latest-release-build',
      api.properties(**termina_release_properties),
      api.buildbucket.simulated_search_results(
          [],
          step_name='get latest build version.query-tatl.buildbucket.search'),
      api.post_check(post_process.StatusFailure),
  )

  yield api.test(
      'no-acls',
      api.properties(**sludge_properties),
      api.properties(userAcls=[], groupAcls=[]),
      api.git.diff_check(True),
      mock_sludge_build_search,
      api.post_check(post_process.StatusSuccess),
  )


# Helper function to create a set of parameterized buildbucket build objects.
def _generate_postsubmit_build_set(ids, board):
  builds = []
  for index, bb_id in enumerate(ids):
    build_artifacts = {
        'gs_path': 'postsubmit-{0}/R80-1.2.{1}-{1}'.format(board, bb_id),
        'gs_bucket': 'chromeos-image-archive'
    }
    gitiles_commit = {'ref': 'refs/heads/main'}
    properties = Struct()
    properties['chromeos_version'] = 'R80-1.2.{0}'.format(bb_id)
    properties['artifacts'] = build_artifacts

    builds.append(
        bb_build.Build(
            id=index + 1, status=bb_common.SUCCESS,
            input=bb_build.Build.Input(gitiles_commit=gitiles_commit),
            output=bb_build.Build.Output(properties=properties)))

  return builds


def _generate_legacy_release_build_set(board, ids_by_branch):
  builds = []
  idx = 1
  for (branch, build_ids) in sorted(ids_by_branch.items()):
    for build_id in build_ids:
      properties = Struct()
      properties['cbb_branch'] = 'release-R{}-12345.B'.format(branch)
      properties['full_version'] = 'R{}-1.2.{}'.format(branch, build_id)
      properties['artifact_link'] = \
        'gs://chromeos-image-archive/{}-release/{}' \
        .format(board, properties['full_version'])

      builds.append(
          bb_build.Build(id=idx, status=bb_common.SUCCESS,
                         output=bb_build.Build.Output(properties=properties)))
      idx += 1

  return builds
