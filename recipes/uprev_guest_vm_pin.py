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

from PB.chromiumos.common import PackageInfo
from PB.recipes.chromeos.uprev_guest_vm_pin import UprevGuestVmPinProperties

DEPS = [
    'cros_source',
    'gerrit',
    'git',
    'repo',
    'depot_tools/gsutil',
    'recipe_engine/archive',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

PROPERTIES = UprevGuestVmPinProperties

_image_archive_bucket = 'chromeos-image-archive'
_latest_image_file = 'LATEST-master'
_base_vm_name = 'base-guest-vm'
_test_vm_name = 'test-guest-vm'

def _get_gs_uri(bucket, suburl):
  return 'gs://%s/%s' % (bucket, suburl)

def RunSteps(api, properties):
  with api.step.nest('validate properties') as step:
    if not properties.version_file:
      raise ValueError('must set version_file')

    if not properties.board:
      raise ValueError('must set board')

    if not properties.destination_bucket:
      raise ValueError('must set destination_bucket')

    step.presentation.step_text = 'all properties good'

  version = ''
  with api.step.nest('copy images to localmirror'):
    src_bucket = _image_archive_bucket
    version_suburl = '{}-postsubmit/{}'.format(properties.board,
                                               _latest_image_file)
    version = api.gsutil.cat(_get_gs_uri(src_bucket, version_suburl),
                             stdout=api.raw_io.output()).stdout

    tmp_dir = api.path.mkdtemp(prefix='archive-staging')
    with api.context(cwd=tmp_dir):
      src_suburl = '{}-postsubmit/{}/{}'.format(properties.board, version,
                                                "image.zip")
      api.gsutil.download(src_bucket, src_suburl, './')
      api.archive.extract('unzip image archive',
                          api.context.cwd.join('image.zip'),
                          api.context.cwd.join('image'),
                          include_files=[_base_vm_name, _test_vm_name])

      # version_num removes the R prefix and converts the '- to ebuild
      # compatible '.'
      # e.g. R80-1234.0.1 -> 80.1234.0.1
      version_num = version[1:]
      version_num = version_num.replace('-', '.')

      base_tar = (api.archive.package(api.context.cwd)
                  .with_dir(api.context.cwd.join(_base_vm_name))
                  .archive('archive base guest VM',
                           api.context.cwd.join(_base_vm_name+'.tbz'), 'tbz'))
      test_tar = (api.archive.package(api.context.cwd)
                  .with_dir(api.context.cwd.join(_test_vm_name))
                  .archive('archive test guest VM',
                           api.context.cwd.join(_test_vm_name+'.tbz'), 'tbz'))

      dst_bucket =  properties.destination_bucket
      dst_suburl = 'distfiles/{}/{}/'.format(properties.board, version_num)
      api.gsutil.upload("*.tbz", dst_bucket, dst_suburl)

  package = api.path.dirname(properties.version_file)
  version_path = api.cros_source.workspace_path.join(properties.version_file)
  with api.step.nest('try uprev version file') as step:
    api.file.write_raw(name='version file',
                       dest=version_path, data=version_num)

    if not api.git.diff_check(version_path):
      step.presentation.step_text = (
          'skipping uprev for {}. version file unchanged').format(package)
      return

  project = None
  with api.step.nest('commit uprev'):
    with api.context(cwd=api.path.abs_to_path(api.path.dirname(version_path))):
      project = api.repo.project_info(project=api.git.repository_root())
    api.repo.start('uprev-guest-vm', projects=[project.name])

    message = '{}: updating version pin to latest - {}'.format(package,
                                                                version_num)
    api.git.add([properties.version_file])
    api.git.commit(message)

  with api.step.nest('generate CL'):
    change = api.gerrit.create_change(
      project=project.name,
      reviewers=["tbegin@google.com"],
      topic=package
    )

    # TODO(tbegin): Change label to COMMIT_QUEUE: 2 after initial testing
    labels = {
      api.gerrit.Label.BOT_COMMIT: 1,
      api.gerrit.Label.COMMIT_QUEUE: 1,
    }
    api.gerrit.set_change_labels(change, labels)


def GenTests(api):
  properties = json_format.MessageToDict(
      UprevGuestVmPinProperties(
        version_file=('chromiumos/src/private-overlays/project-wilco-private/'
                      'chromeos-base/chromeos-dtc-vm/VERSION-PIN'),
        board='sludge',
        destination_bucket='chromeos-localmirror-private',
      ))

  yield (api.test('uprev-sludge') + api.properties(**properties) +
         api.step_data('copy images to localmirror.gsutil cat',
          stdout=api.raw_io.output('R80-1.2.3')) + api.git.diff_check(True))

  yield (api.test('no-version-file') + api.properties(**properties) +
         api.properties(versionFile='') + api.expect_exception('ValueError'))

  yield (api.test('no-board') + api.properties(**properties) +
         api.properties(board='') + api.expect_exception('ValueError'))

  yield (api.test('no-destination-bucket') + api.properties(**properties) +
         api.properties(destination_bucket='') +
         api.expect_exception('ValueError'))

  yield (api.test('no-version-diff') + api.properties(**properties) +
         api.step_data('copy images to localmirror.gsutil cat',
          stdout=api.raw_io.output('R80-1.2.3')) + api.git.diff_check(False))
