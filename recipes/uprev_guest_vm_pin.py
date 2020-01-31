# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for Upreving Guest VM version pin files.

This recipe copies a VM image artifact from the chromeos-image-archive to the
localmirror and then modifies the Guest VM's version pin to match this version.

"""
import os

from google.protobuf import json_format
from google.protobuf import struct_pb2

from PB.chromiumos.common import PackageInfo
from PB.go.chromium.org.luci.buildbucket.proto import rpc as bb_rpc
from PB.go.chromium.org.luci.buildbucket.proto import build as bb_build
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common
from PB.recipes.chromeos.uprev_guest_vm_pin import UprevGuestVmPinProperties

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


def RunSteps(api, properties):
  with api.step.nest('validate properties') as step:
    if not properties.version_file:
      raise ValueError('must set version_file')

    if not properties.board:
      raise ValueError('must set board')

    if not properties.destination_bucket:
      raise ValueError('must set destination_bucket')

    step.presentation.step_text = 'all properties good'

  with api.step.nest('get latest postsubmit build version'):
    builder_name = '{}-postsubmit'.format(properties.board)
    builds = api.buildbucket.search(
        predicate=bb_rpc.BuildPredicate(
            builder=bb_build.BuilderID(
                project='chromeos',
                bucket='postsubmit',
                builder=builder_name,
            ), status=bb_common.SUCCESS), limit=1)

    if not len(builds) == 1:
      raise api.step.StepFailure(
          'unable to find latest build for {}'.format(builder_name))

    build = builds[0]
    build_artifact_bucket = str(
        build.output.properties['artifacts']['gs_bucket'])
    build_artifact_path = str(build.output.properties['artifacts']['gs_path'])
    version = str(build.output.properties['chromeos_version'])

    # sanitized_version removes the R prefix and converts the '- to ebuild
    # compatible '.'
    # e.g. R80-1234.0.1 -> 80.1234.0.1
    sanitized_version = version[1:]
    sanitized_version = sanitized_version.replace('-', '.')

  with api.cros_source.checkout_overlays_context():
    api.cros_source.ensure_synced_cache()
    version_path = api.cros_source.workspace_path.join(
        properties.version_file)
    package_path = api.path.dirname(version_path)
    package = os.path.basename(package_path)

    with api.step.nest('try uprev version file') as step:
      api.file.write_raw(name='version file', dest=version_path,
                          data=sanitized_version)

      with api.context(cwd=api.path.abs_to_path(package_path)):
        if not api.git.diff_check(version_path):
          step.presentation.step_text = (
              'skipping uprev for {}. version unchanged').format(package)
          return

    with api.step.nest('commit uprev'), \
          api.context(cwd=api.path.abs_to_path(package_path)):
      project = api.repo.project_info(project=api.git.repository_root())
      api.repo.start('uprev-guest-vm', projects=[project.name])

      message = '{}: updating version pin to latest - {}'.format(
          package, sanitized_version)
      api.git.add([version_path])
      api.git.commit(message)

    with api.step.nest('copy images to localmirror'):
      tmp_dir = api.path.mkdtemp(prefix='archive-staging')
      with api.context(cwd=tmp_dir):
        src_suburl = '{}/{}'.format(build_artifact_path, "image.zip")
        api.gsutil.download(build_artifact_bucket, src_suburl, './')
        api.archive.extract('unzip image archive',
                            api.context.cwd.join('image.zip'),
                            api.context.cwd.join('image'))

        base_tar = (
            api.archive.package(api.context.cwd).with_dir(
                api.context.cwd.join(_base_vm_name)).archive(
                    'archive base guest VM',
                    api.context.cwd.join(_base_vm_name + '.tbz'), 'tbz'))
        test_tar = (
            api.archive.package(api.context.cwd).with_dir(
                api.context.cwd.join(_test_vm_name)).archive(
                    'archive test guest VM',
                    api.context.cwd.join(_test_vm_name + '.tbz'), 'tbz'))

        dst_bucket = properties.destination_bucket
        dst_suburl = 'distfiles/{}/{}/'.format(properties.board,
                                              sanitized_version)
        api.gsutil.upload("*.tbz", dst_bucket, dst_suburl)

    with api.step.nest('generate CL'):
      change = api.gerrit.create_change(
          project=project.name, reviewers=["tbegin@google.com"], topic=package)

      # TODO(tbegin): Change label to COMMIT_QUEUE: 2 after initial testing
      labels = {
          api.gerrit.Label.BOT_COMMIT: 1,
          api.gerrit.Label.COMMIT_QUEUE: 1,
      }
      api.gerrit.set_change_labels(change, labels)


def GenTests(api):
  properties = json_format.MessageToDict(
      UprevGuestVmPinProperties(
          version_file=('src/private-overlays/project-wilco-private/'
                        'chromeos-base/chromeos-dtc-vm/VERSION-PIN'),
          board='sludge',
          destination_bucket='chromeos-localmirror-private',
      ))

  build_artifacts = {
    'gs_path': 'postsubmit-sludge/R80-1.2.3-123456',
    'gs_bucket': 'chromeos-image-archive'
  }
  build_properties = struct_pb2.Struct()
  build_properties['chromeos_version'] = 'R80-1.2.3'
  build_properties['artifacts'] = build_artifacts

  mock_build_search = api.buildbucket.simulated_search_results([
      bb_build.Build(id=1, status=bb_common.SUCCESS,
                     output=bb_build.Build.Output(properties=build_properties))
  ], step_name='get latest postsubmit build version.buildbucket.search')

  yield (api.test('uprev-sludge') + api.properties(**properties) +
         api.git.diff_check(True) + mock_build_search)

  yield (api.test('no-version-file') + api.properties(**properties) +
         api.properties(versionFile='') + api.expect_exception('ValueError'))

  yield (api.test('no-board') + api.properties(**properties) +
         api.properties(board='') + api.expect_exception('ValueError'))

  yield (api.test('no-destination-bucket') + api.properties(**properties) +
         api.properties(destination_bucket='') +
         api.expect_exception('ValueError'))

  yield (api.test('no-version-diff') + api.properties(**properties) +
         api.git.diff_check(False) + mock_build_search)

  yield (api.test('no-latest-postsubmit-build') + api.properties(
      **properties) + api.buildbucket.simulated_search_results(
          [],
          step_name='get latest postsubmit build version.buildbucket.search'))
