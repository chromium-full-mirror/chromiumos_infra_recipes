# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for Upreving Guest VM version pin files.

This recipe copies a VM image artifact from the chromeos-image-archive to the
localmirror and then modifies the Guest VM's version pin to match this version.

"""

from collections import defaultdict
from typing import Dict
from typing import List

from RECIPE_MODULES.chromeos.gerrit.api import Label
from google.protobuf import json_format
from google.protobuf import timestamp_pb2
from google.protobuf.struct_pb2 import Struct

from PB.chromiumos.builder_config import BuilderConfig as bc
from PB.go.chromium.org.luci.buildbucket.proto import build as bb_build
from PB.go.chromium.org.luci.buildbucket.proto \
  import builder_common as bb_builder_common
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       bb_service)
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common
from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.recipes.chromeos.uprev_guest_vm_pin import UprevGuestVmPinProperties
from PB.recipes.chromeos.uprev_guest_vm_pin import VmBoardImage
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi


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


def _gs_path(bucket: str, path: str) -> str:
  """Returns the full gs:// path for bucket and path."""
  return 'gs://' + bucket + '/' + path


def _version_comparator(a: str, b: str) -> bool:
  """ Returns true if version |a| is greater than or equal to |b|

  |a| and |b| are expected to be strings of numbers separated by |.|
  """
  a_parts = [int(part) for part in a.split('.')]
  b_parts = [int(part) for part in b.split('.')]
  return a_parts > b_parts


def _sanitize_version_number(version: str) -> str:
  """ Removes the R prefix and converts the '- to ebuild compatible '.'
      e.g. R80-1234.0.1 -> 80.1234.0.1
  """
  sanitized_version = version[1:]
  return sanitized_version.replace('-', '.')


def _validate_properties(properties: UprevGuestVmPinProperties):
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


def FindPostsubmitBuilds(
    api: RecipeApi, board: str,
    version_build_map: Dict[str, Dict[str, Dict[str, Build]]]):
  # Find successful builds that started within the last 36 hours. This
  # should cover everything we're interested in, since we run once per
  # day.
  builds = api.buildbucket.search(
      predicate=bb_service.BuildPredicate(
          builder=bb_builder_common.BuilderID(
              project='chromeos',
              bucket='postsubmit',
              builder='{}-postsubmit'.format(board),
          ), create_time=bb_common.TimeRange(
              start_time=timestamp_pb2.Timestamp(
                  seconds=api.buildbucket.build.create_time.ToSeconds() -
                  36 * 60 * 60)), status=bb_common.SUCCESS))

  for build in builds:
    branch = build.input.gitiles_commit.ref.split('/')[-1]
    version = build.output.properties['chromeos_version']
    version_build_map[branch][version][board] = build


def FindReleaseBuilds(api: RecipeApi, board: str,
                      version_build_map: Dict[str, Dict[str, Dict[str,
                                                                  Build]]]):
  prefix = '{}-'.format(board)
  for builder in api.buildbucket.list_builders('chromeos', 'release'):
    if not builder.startswith(prefix):
      # Unrelated builder, skip.
      continue

    # Builders get named '{board}-release-{branch}', except if the
    # branch starts with 'release-' in which case the extra 'release-'
    # is dropped. This strictly isn't a reversable transformation, but
    # in practice release branches always have 'R' as the next
    # character and nothing else does, so we use that to find the
    # actual branch name.
    suffix = builder[len(prefix):]
    if suffix.startswith('release-R'):
      branch = suffix
    else:
      # Drop 'release-' for main and stabilize branches.
      branch = suffix[8:]

    with api.step.nest(branch):
      builds = api.buildbucket.search(
          predicate=bb_service.BuildPredicate(
              builder=bb_builder_common.BuilderID(
                  project='chromeos',
                  bucket='release',
                  builder=builder,
              ), create_time=bb_common.TimeRange(
                  start_time=timestamp_pb2.Timestamp(
                      seconds=api.buildbucket.build.create_time.ToSeconds() -
                      72 * 60 * 60)), status=bb_common.SUCCESS))

      for build in builds:
        version = build.output.properties['chromeos_version']
        version_build_map[branch][version][board] = build


def CopyPostsubmitImage(api: RecipeApi, board: str, build: Build,
                        vm_property_map: Dict[str, Struct],
                        sanitized_version: str):
  tmp_dir = api.path.mkdtemp(prefix='archive-staging')
  with api.context(cwd=tmp_dir):
    build_artifact_bucket = str(
        build.output.properties['artifacts']['gs_bucket'])
    build_artifact_path = str(build.output.properties['artifacts']['gs_path'])
    src_path = '{}/{}'.format(build_artifact_path, 'image.zip')
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
    api.gsutil.upload('*.tbz', dst_bucket, dst_path)


def CopyReleaseImage(api: RecipeApi, board: str, build: Build,
                     vm_property_map: Dict[str, Struct],
                     sanitized_version: str):
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

  api.gsutil.copy(src_bucket, '{}/{}.tar.xz'.format(src_path, _base_vm_name),
                  dst_bucket, '{}/'.format(dst_path),
                  name='copy {} base image'.format(board))
  api.gsutil.copy(src_bucket, '{}/{}.tar.xz'.format(src_path, _test_vm_name),
                  dst_bucket, '{}/'.format(dst_path),
                  name='copy {} test image'.format(board))


def RunSteps(api: RecipeApi, properties: UprevGuestVmPinProperties):
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
            FindReleaseBuilds(api, board, version_build_map)

          if len(version_build_map) == 0:
            raise StepFailure('unable to find builds for {}'.format(board))

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
              CopyReleaseImage(api, board, build, vm_property_map,
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
              Label.BOT_COMMIT: 1,
              Label.COMMIT_QUEUE: 2,
          }
          api.gerrit.set_change_labels(change, labels)
          api.gerrit.submit_change(change)


def GenTests(api: RecipeTestApi):
  buildbucket_search_step = 'get latest build version.query-{}.buildbucket.search'

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

  buildbucket_builder_list_step = 'get latest build version.query-{}.buildbucket.builders'

  mock_builder_list = [
      'tatl-release-main',
      'tael-release-main',
      'tatl-release-R108-15183.B',
      'tael-release-R108-15183.B',
      'tatl-release-R107-15117.B',
      'tael-release-R107-15117.B',
      'tatl-release-R102-14695.B',
      'tael-release-R102-14695.B',
      'tatl-release-stabilize-15129.B',
      'tael-release-stabilize-15129.B',
      'tatl-release-stabilize-15185.B',
      'tael-release-stabilize-15185.B',
      'eve-release-main',
  ]

  mock_builder_list_tatl = api.buildbucket.simulated_list_builders(
      mock_builder_list, step_name=buildbucket_builder_list_step.format('tatl'))

  mock_builder_list_tael = api.buildbucket.simulated_list_builders(
      mock_builder_list, step_name=buildbucket_builder_list_step.format('tael'))

  buildbucket_rubik_search_step = 'get latest build version.query-{}.{}.buildbucket.search'

  mock_tatl_rubik_main_search = api.buildbucket.simulated_search_results(
      _generate_release_build_set('tatl', 'main', [1, 2, 3]),
      step_name=buildbucket_rubik_search_step.format('tatl', 'main'))

  mock_tael_rubik_main_search = api.buildbucket.simulated_search_results(
      _generate_release_build_set('tael', 'main', [1, 2, 3]),
      step_name=buildbucket_rubik_search_step.format('tael', 'main'))

  mock_tatl_rubik_R108_search = api.buildbucket.simulated_search_results(
      _generate_release_build_set('tatl', 'release-R108-15183.B', [1, 2, 3]),
      step_name=buildbucket_rubik_search_step.format('tatl',
                                                     'release-R108-15183.B'))

  mock_tael_rubik_R108_search = api.buildbucket.simulated_search_results(
      _generate_release_build_set('tael', 'release-R108-15183.B', [1, 2, 3]),
      step_name=buildbucket_rubik_search_step.format('tael',
                                                     'release-R108-15183.B'))

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
      status='FAILURE',
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
      'uprev-termina-rubik-success',
      api.properties(**termina_release_properties),
      api.git.diff_check(True),
      mock_builder_list_tatl,
      mock_builder_list_tael,
      mock_tatl_rubik_main_search,
      mock_tael_rubik_main_search,
      mock_tatl_rubik_R108_search,
      mock_tael_rubik_R108_search,
  )

  yield api.test(
      'no-version-file',
      api.properties(**termina_properties),
      api.properties(versionFile=''),
      status='FAILURE',
  )

  yield api.test(
      'no-vm-board-images',
      api.properties(**termina_properties),
      api.properties(vmBoardImages=[]),
      status='FAILURE',
  )

  yield api.test(
      'no-board',
      api.properties(**termina_properties),
      api.properties(vmBoardImages=[
          json_format.MessageToDict(
              VmBoardImage(
                  board='',
                  destination_gs_bucket='termina-component-testing',
                  destination_gs_path='uprev-test/amd64',
              ))
      ]),
      status='FAILURE',
  )

  yield api.test(
      'no-destination-gs-bucket',
      api.properties(**termina_properties),
      api.properties(vmBoardImages=[
          json_format.MessageToDict(
              VmBoardImage(
                  board='tatl',
                  destination_gs_bucket='',
                  destination_gs_path='uprev-test/amd64',
              ))
      ]),
      status='FAILURE',
  )

  yield api.test(
      'no-destination-gs-path',
      api.properties(**termina_properties),
      api.properties(vmBoardImages=[
          json_format.MessageToDict(
              VmBoardImage(
                  board='tatl',
                  destination_gs_bucket='termina-component-testing',
                  destination_gs_path='',
              ))
      ]),
      status='FAILURE',
  )

  yield api.test(
      'unknown-build-type',
      api.properties(**termina_properties),
      api.properties(builderType=123),
      status='FAILURE',
  )

  yield api.test(
      'no-version-diff',
      api.properties(**termina_properties),
      api.git.diff_check(False),
      mock_tatl_build_search_success,
      mock_tael_build_search_success,
  )

  yield api.test(
      'no-latest-postsubmit-build',
      api.properties(**termina_properties),
      api.buildbucket.simulated_search_results(
          [],
          step_name='get latest build version.query-tatl.buildbucket.search'),
      status='FAILURE',
  )

  yield api.test(
      'no-acls',
      api.properties(**termina_properties),
      api.properties(userAcls=[], groupAcls=[]),
      api.git.diff_check(True),
      mock_tatl_build_search_success,
      mock_tael_build_search_success,
  )


# Helper function to create a set of parameterized buildbucket build objects.
def _generate_postsubmit_build_set(ids: List[int], board: str) -> List[Build]:
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


def _generate_release_build_set(board: str, branch: str,
                                ids: List[int]) -> List[Build]:
  builds = []
  for idx, build_id in enumerate(ids, 1):
    input_ = Struct()
    output = Struct()
    output['chromeos_version'] = '{}-1.2.{}'.format(branch[8:-8], build_id)
    output['artifact_link'] = \
      'gs://chromeos-image-archive/{}-release/{}' \
      .format(board, output['chromeos_version'])

    builds.append(
        bb_build.Build(id=idx, status=bb_common.SUCCESS,
                       input=bb_build.Build.Input(properties=input_),
                       output=bb_build.Build.Output(properties=output)))

  return builds
