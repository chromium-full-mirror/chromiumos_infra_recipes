# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for executing ChromeOS VM test suite.

This recipe runs out-of-band on VM test swarming bot.
"""

import contextlib

DEPS = [
  'depot_tools/gsutil',
  'recipe_engine/archive',
  'recipe_engine/context',
  'recipe_engine/file',
  'recipe_engine/path',
  'recipe_engine/properties',
  'recipe_engine/python',
  'recipe_engine/raw_io',
  'recipe_engine/step',
  'cros_sdk',
  'cros_source',
  'cros_test',
  'overlayfs',
]

# Magic paths:
# api.path['cleanup'] = recipe managed temp directory.
# api.path['cache'] = swarming managed "named cache" directory.

def RunSteps(api):
  with _test_env_context(api):
    if api.properties['test_type'] == 'tast_vm':
      api.cros_test.run_tast_test(api.properties['build_target'],
                                  api.properties['test_suite'],
                                  api.properties['test_exprs'])
    else:
      api.cros_test.run_vm_test(api.properties['build_target'],
                                api.properties['test_suite'])

@contextlib.contextmanager
def _test_env_context(api):
  """Returns a test environment context.

  Prepares a fresh environment to run VM / Tast tests, and returns a
  context with everything in place.
  """
  download_path = api.path['cleanup'].join('downloads')

  image_artifact = 'image.zip'
  autotest_artifacts = [
    'autotest_packages.tar',
    'control_files.tar',
    'test_suites.tar.bz2'
  ]

  gs_path = api.properties['gs_path']
  gs_bucket = api.properties['gs_bucket']
  download_files([image_artifact] + autotest_artifacts,
                 api.gsutil, gs_bucket, gs_path, download_path)

  # Prepare repo source.
  # This is needed because cros_run_vm_test requires chromite, as well
  # as other source dependencies that aren't easy to bundle.
  # TODO(yshaul): Add init_opts=dict(groups=['minilayout']).
  #               Minilayout currently crashes when building chroot.
  api.cros_source.ensure_synced_cache(
      manifest_url=api.cros_source.EXTERNAL_MANIFEST_URL)

  api.file.ensure_directory('ensure cros_sdk dir',
                              api.path['cache'].join('cros_sdk'))
  api.cros_sdk.configure(chroot_parent_path=api.path['cache'].join('cros_sdk'))

  ws_path = api.cros_source.workspace_path
  with api.cros_source.checkout_overlays_context(), api.context(cwd=ws_path):
    # The chroot is normally created implicitely with the first cros_sdk call.
    # However, we need the chroot to be created in advance, since we need
    # to copy the autotest files to the chroot *before* running cros_sdk.
    api.cros_sdk('ensure chroot', ['--create'])

    api.archive.extract('extract image',
                        download_path.join(image_artifact),
                        api.cros_test.image_path,
                        include_files=['chromiumos_qemu_image.bin', 'id_rsa'])

    # Autotest requires a very specific setup for vm testing to work.
    # Autotest must reside in src/third_party/autotest/files, and a
    # build-specific copy in /builds/<build_target>/usr/local/build/autotest.
    autotest_path = ws_path.join('src', 'third_party', 'autotest', 'files')
    api.file.ensure_directory('ensure autotest dir', autotest_path)

    # until we get all artifacts in a single tarball: crbug/932210
    api.file.ensure_directory('ensure extract dir',
                              download_path.join('extract'))
    for artifact in autotest_artifacts:
      # We extract to a temp first rather than the target dir because
      # archive.extract requires that target dir not yet exist
      api.archive.extract('extract %s' % artifact,
                          download_path.join(artifact),
                          download_path.join('extract', artifact))

      copy_tree('copy %s' % artifact,
                api.python.inline,
                download_path.join('extract', artifact, 'autotest', '*'),
                autotest_path)

    # Autotest requires a special setup to exist in chroot/build/build_target.
    # Constructing the setup directly in the chroot leads to all kinds
    # of permission errors, as well as creating cleanup work.
    # Instead, we simply create the setup we want in <cleanup>/chroot_build,
    # and overlay that over the cached chroot.
    chroot_ws_path = api.path['cleanup'].join('chroot_ws')
    lowerdir_path = api.cros_sdk.chroot_path
    upperdir_path = chroot_ws_path.join('upper')
    mount_path = chroot_ws_path.join('chroot')

    chroot_build_path = upperdir_path.join('build',
                                           api.properties['build_target'],
                                           'usr', 'local')
    api.file.ensure_directory('ensure build chroot dir',
                              chroot_build_path.join('build', 'autotest'))
    api.file.ensure_directory('ensure autotest required dir',
                              chroot_build_path.join('client', 'packages'))
    api.file.ensure_directory('ensure chroot mount', mount_path)

    copy_tree('copy autotest to chroot',
              api.python.inline,
              autotest_path.join('*'),
              chroot_build_path.join('build', 'autotest'))

    with api.overlayfs.cleanup_context():
      api.overlayfs.mount('chrootmount', lowerdir_path, mount_path,
                          upperdir_path=upperdir_path)

      # now reconfigure cros_sdk to use our new overlay
      api.cros_sdk.configure(chroot_parent_path=chroot_ws_path)
      yield

def download_files(files, gsutil, gs_bucket, gs_path, dest_path):
  for filename in files:
    gsutil.download(gs_bucket,
                    '%s/%s' % (gs_path, filename),
                    dest_path.join(filename))

def copy_tree(name, py, src, dest):
  """Shell out to bash cp to perform copy operations.

  Use in place of file api's copytree method, as copytree can be quite slow,
  and we have to merge several source directories to a single target directory.
  """
  py(name,
     """
import os
os.system("cp -rn %s %s")
     """ % (src, dest))


def GenTests(api):
  yield (
    api.test('vm_test') +
    api.properties(
      test_type='vm',
      build_target='build_target',
      test_suite='test_suite',
      gs_path='path/to/image',
      gs_bucket='image-bucket'
    )
  )

  yield (api.test('tast_test') +
         api.properties(test_type='tast_vm', build_target='build_target',
                        test_suite='test_suite', test_exprs=["test_expr"],
                        gs_path='path/to/image', gs_bucket='image-bucket'))
